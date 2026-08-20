# 对「阶段一-fix-LLM空字段导致Pydantic校验失败」的评估与建议

> **面向**：Trae（开发助手）  
> **目的**：供 Trae 思考判断，决定是否采纳建议、如何排优先级  
> **背景**：2026-06-11，运行 `python3 frost_agent.py "新能源汽车"` 时 Step 1 崩溃，开发日志记录了根因分析和修复方案。本评估基于代码阅读 + 与项目负责人的讨论。  
> **评估立场**：协作式建议，非权威指令

---

## 一、对开发日志的总体评估

**结论：根因分析准确，修复方案务实，但缺少对「静默降级」风险的讨论。**

### 1.1 做得好的地方

| 维度 | 评价 |
|------|------|
| **根因分析** | 准确。同时指向 Prompt 侧（未要求字段非空）和代码侧（`min_length=1` 收紧后未做兜底），没有甩锅给 LLM 或 Pydantic |
| **修复方案选择** | 正确。三种方案中选了最优解：代码层 `or` 硬兜底，不改 `models.py` 放松约束（保持审计能力），也不仅依赖 prompt 软约束 |
| **遗留问题识别** | 准确指出「不可观测」——下次再发生同样情况时，仍然看不到 LLM 原始响应 |

### 1.2 验证结果

我对照代码验证了日志中的每个断言，全部属实：

- 崩溃点在 `_run_step1()` 第 488-495 行 ✅
- `reasoning` 有 `min_length=1` 约束（`models.py:35-42`）✅
- 两种可能导致空字符串（JSON 解析成功但 summary 为空 / JSON 解析失败）✅
- 修复已实施在三处（`frost_agent.py:490, 517, 522`）✅
- Step 5 不需要修复（`reasoning` 至少包含 `"独立Evaluator审查完成。结果: {overall}。"`）✅

---

## 二、发现的深层问题：静默降级 + 异常传递缺失

### 2.1 修复引入了「静默降级」风险

`or` fallback 防止了崩溃，但如果 LLM **频繁**返回空字段（比如某些特定行业更容易触发），系统会**静默地**用占位符替代真实推理：

```python
reasoning = parsed.get("summary", "")[:300] or "（LLM 未返回摘要，已从搜索结果生成）"
```

这个降级发生后：
- **Step 2 不知道** —— 它看到的是 Step 1 的摘要，不知道这个摘要是 LLM 归纳的还是代码硬兜底的
- **Step 5 不知道** —— Evaluator 审查最终报告文本，可能报告看起来还行，但根因是「Step 1 的信息基础就不扎实」
- **使用者不知道** —— 除非他去看 stdout 日志（而日志在阶段二会被写入文件，使用者根本不会看）

**这意味着：一个「隐性降级」的报告，可能顺利通过 Step 5 自检，最终交付给使用者，而使用者完全不知道 Step 1 曾经崩过一次。**

### 2.2 当前架构缺少「跨步骤异常传递」机制

开发日志建议「在阶段二的 Session Event Log 升级中纳入」原始响应日志。但这个问题**不需要等阶段二**——核心缺失不是「日志不够详细」，而是**「各步骤的异常状态没有汇聚到最终检查点」**。

当前代码的问题：
- Step 1 的 `or` fallback 防止了崩溃 ✅
- 但降级信息只存在于 stdout 的某一行日志里 ❌
- Step 5 看不到这个信息 ❌
- 使用者更看不到 ❌

---

## 三、给 Trae 的具体建议（分优先级）

### P0：当前 bugfix 中顺手做（改动很小，架构意义大）

#### 建议 1：在 `StepOutput` 中增加 `quality_flags` 字段

这是核心建议。把「每一步的异常」汇聚到 `state` 中，让 Step 6（输出）统一感知并呈现给使用者。

```python
# models.py — StepOutput 增加字段
class StepOutput(BaseModel):
    # ... 现有字段 ...
    quality_flags: list[str] = Field(
        default_factory=list,
        description="该步骤发生的质量降级标记。示例：['llm_empty_field:summary', 'search_partial_failure:2/3']",
    )
```

当 Step 1 发生 fallback：

```python
# frost_agent.py:490 附近
reasoning = parsed.get("summary", "")[:300]
quality_flags = []
if not reasoning:
    quality_flags.append("llm_empty_field:summary")
    reasoning = "（LLM 未返回摘要，已从搜索结果生成）"

state.steps.append(StepOutput(
    step_id=step_id, step_label="信息收集",
    reasoning=reasoning,
    quality_flags=quality_flags,  # 新增
    # ... 其他字段不变
))
```

Step 2/3 同理，任何「代码兜底替代 LLM 产出」的场景都应该写入 `quality_flags`。

#### 建议 2：Step 6 汇总 `quality_flags`，在报告尾部增加「生成过程异常记录」

```python
# frost_agent.py — _run_step6() 中，在方法论附注之前

def _build_quality_flags_section(state: ReportState) -> str:
    flags = []
    for step in state.steps:
        for flag in step.quality_flags:
            flags.append(f"- **{step.step_label}**: {flag}")
    if not flags:
        return ""
    return (
        "\n\n---\n\n"
        "## ⚠️ 生成过程异常记录\n\n"
        "以下步骤在生成过程中遇到异常，已使用兜底策略完成：\n\n"
        + "\n".join(flags)
        + "\n\n**建议：人工复核上述步骤的产出质量。**\n"
    )
```

这样使用者能在报告末尾直接看到「Step 1 的 summary 被降级过」，不需要翻日志。

#### 建议 3：在 `call_llm()` 返回处增加原始响应日志（当前 bugfix 中顺便做）

开发日志把这项列为「遗留问题，阶段二解决」。但其实可以顺手做——在 `_parse_json_response` 调用前加一行：

```python
# frost_agent.py — call_llm() 返回后或 _parse_json_response() 前
logger.log("llm_raw_response", {"text": llm_result["text"][:1000]})
```

成本很低（已经改了 4 行，再加 1 行），不需要等阶段二的 Session Event Log 升级。

### P1：当前 bugfix 中同步做

#### 建议 4：Prompt 侧同步增加非空约束

开发日志说「没有选择修改 prompt 层面强制非空，因为 prompt 是软约束」。这个判断对，但**两者应该并行**——在 prompt 中增加约束可以降低触发概率，代码兜底保证不崩溃。

```python
# context_builder.py — STEP_TASKS["1_info_collection"] 中
"输出 JSON 格式，包含 summary、official_definitions、... 字段。"
"注意：summary 字段不可为空，必须包含对搜索结果的归纳摘要（至少 50 字）。"
```

### P2：阶段一收尾验证

#### 建议 5：用「新能源汽车」重复运行 3-5 次，观察触发频率

日志没有分析为什么偏偏是「新能源汽车」触发了这个问题，而之前的「低空经济物流」「汽车」没有。可能的解释：
- 「新能源汽车」比「汽车」更宽泛，搜索返回的信息量更大/更杂，LLM 在长上下文压力下更容易把需要归纳的 `summary` 留空
- Tavily 对「新能源汽车」返回的结果结构不同
- LLM 的非确定性导致偶发

**如果是系统性问题**（某些行业更容易触发），那么当前的修复虽然防止了崩溃，但会导致这些行业的 Step 1 推理痕迹被降级为占位符，**报告质量会隐性下降**。建议用「新能源汽车」重复运行 3-5 次，统计 `quality_flags` 触发频率。

### P3：阶段二考虑

#### 建议 6：让 Evaluator 检查 `quality_flags`

当前 Evaluator 的设计约束是「只看最终报告文本，不接收 Step 1-4 的 reasoning」。这个约束是为了防止 Self-Evaluation Bias，但也导致 Evaluator 无法发现「步骤级降级」。

阶段二可以考虑：Evaluator 在审查报告文本的同时，也检查 `quality_flags`。如果存在降级标记（如 `llm_empty_field:summary`），即使报告文本看起来合格，也应：
- 降低总体置信度（如从 "high" 降为 "medium"）
- 或强制要求人工复核
- 或在 `fixes_required` 中增加「建议重新运行 Step 1」

---

## 四、两种 Warning 的区分（帮助 Trae 理解架构）

| | **Step 1-4 的 `quality_flags`** | **Step 5 的 `_build_self_check_warning()`** |
|---|---|---|
| **面向谁** | 报告使用者（报告尾部） | 报告使用者（报告头部） |
| **触发条件** | 某一步的 LLM 产出异常，代码用兜底替代 | 报告整体未通过 C1-C5 自检 |
| **性质** | 工程可观测性：「系统内部发生了降级」 | 方法论自检：「这份报告可能不合格」 |
| **当前实现** | ❌ 缺失（建议新增） | ✅ 已实现 |
| **谁负责** | Orchestrator / 各步骤实现 | Independent Evaluator |

**关键洞察**：Step 5 的 Evaluator **不应该**也**不可能**替代 `quality_flags` 的职责。Evaluator 看的是最终报告文本，它不知道 Step 1 的 `reasoning` 是 LLM 写的还是代码兜底的。这两者是互补的：
- `quality_flags` 回答「这份报告在生成过程中有没有被降级？」
- Step 5 回答「这份报告的最终文本质量是否合格？」

一个报告可能同时满足：① `quality_flags` 为空（无降级）+ ② Step 5 pass（质量合格）——这是理想情况；
也可能满足：① `quality_flags` 有标记（有降级）+ ② Step 5 pass（文本看起来还行）——这是**静默降级的危险情况**。

---

## 五、下一步行动清单

| 优先级 | 行动 | 改动范围 | 估计工作量 |
|--------|------|---------|-----------|
| **P0** | `StepOutput` 增加 `quality_flags` 字段 | `models.py` + 3 处 `StepOutput` 构造 | 10 分钟 |
| **P0** | Step 6 汇总 `quality_flags` 输出到报告尾部 | `frost_agent.py` — `_run_step6()` | 15 分钟 |
| **P0** | `call_llm()` 返回处增加原始响应日志 | `frost_agent.py` — `_run_step1()` / `_run_step()` | 5 分钟 |
| **P1** | Step 1 prompt 增加 `summary` 非空约束 | `context_builder.py` — `STEP_TASKS` | 2 分钟 |
| **P2** | 「新能源汽车」重复运行 3-5 次，统计触发频率 | 终端运行 + 观察 `quality_flags` | 20 分钟 |
| **P3** | 阶段二：Evaluator 检查 `quality_flags` | `evaluator.py` + `frost_agent.py` — `_run_step5()` | 阶段二规划 |

**总计当前 bugfix 增量**：约 30 分钟，改动 3 个文件（`models.py`, `frost_agent.py`, `context_builder.py`），新增约 20 行代码。

---

## 六、核心判断

开发日志的修复方案（`or` 硬兜底）是**正确的短期止血**，但它只解决了「不崩溃」，没有解决「不可观测」和「不可传递」。

如果不增加 `quality_flags` 机制，未来可能出现这样的场景：
- 分析师拿到一份 Step 5 自检 pass 的报告
- 但 Step 1 的摘要其实是代码兜底的占位符
- 分析师基于这份「看起来合格」的报告做决策
- 而系统没有任何地方告诉他「这份报告的地基曾经松动过」

`quality_flags` 不是过度设计，它是**让「兜底」从「隐藏的技术债」变成「显式的质量声明」**的关键机制。建议 Trae 在当前 bugfix 中顺手实现。

---

*评估人：协作式评估者*  
*日期：2026-06-08*  
*版本：v1.0*
