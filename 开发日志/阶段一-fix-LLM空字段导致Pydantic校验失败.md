# fix: LLM 返回空字段导致 Pydantic 校验失败

> 日期：2026-06-11 | 触发行业：「新能源汽车」

---

## 一、现象

用户在终端执行 `python3 frost_agent.py "新能源汽车"`，Step 1（信息收集）搜索完成后，Agent 崩溃：

```
[错误] 1 validation error for StepOutput
reasoning
  String should have at least 1 character [type=string_too_short, input_value='', input_type=str]
```

堆栈指向 `_run_step1()` 第 488-495 行：`StepOutput(...)` 构造时 `reasoning` 为空字符串，违反 `min_length=1` 约束。

## 二、原因分析

出问题的代码（`frost_agent.py:490`）：

```python
reasoning=parsed.get("summary", "")[:300],
```

`parsed` 来自 `_parse_json_response(llm_result["text"])`，有三层容错：直接解析 → 代码块提取 → 花括号提取。解析成功时返回 LLM 产出的 JSON 对象，失败时返回 `{"raw_response": ..., "parse_error": "..."}`。

两种可能都会导致 `reasoning` 为空：

| 场景 | `parsed` 内容 | `parsed.get("summary", "")` 结果 |
|------|--------------|--------------------------------|
| JSON 解析成功，但 LLM 把 `summary` 写成了 `""` | `{"summary": "", "official_definitions": [...], ...}` | `""` |
| JSON 解析失败（三层容错全不通过） | `{"raw_response": "...", "parse_error": "..."}` | `""`（没有 `summary` 键） |

**但在现有日志体系下无法区分是哪种情况**，因为崩溃前没有打印 LLM 原始响应。

根因指向两点：

1. **Prompt 侧**：Step 1 任务指令（`context_builder.py:20-26`）只列出了 `summary` 字段名，没有要求不可为空：
   ```
   输出 JSON 格式，包含 summary、official_definitions、key_regulations、
   structural_factors、adjacent_industries、data_gaps 字段。
   ```
   LLM（DeepSeek-V4-Pro）在长上下文压力下，可能把容易摘录的字段（定义、政策名）填好，但需要归纳的 `summary` 留空。

2. **代码侧**：`reasoning` 字段收紧为 `min_length=1` 是在 `models.py:35-42` 的设计决策——强制每步输出推理痕迹。但这意味着代码必须能承受 LLM 产出的任意变体，不能假设 LLM 一定遵循格式。

## 三、修复方式

分三层递进修复：

### 3.1 代码硬兜底：`or` fallback（止血）

在三处构造 `StepOutput` 的代码中加入 `or` fallback，防止 Pydantic 校验崩溃：

**`_run_step1()`（`frost_agent.py:490`）**：

```python
# 修改前
reasoning=parsed.get("summary", "")[:300],

# 修改后
reasoning=parsed.get("summary", "")[:300] or "（LLM 未返回摘要，已从搜索结果生成）",
```

**`_run_step()` — Step 2 维度筛选（`frost_agent.py:517`）**：

```python
# 修改前
reasoning = parsed.get("reasoning", "")[:300]

# 修改后
reasoning = parsed.get("reasoning", "")[:300] or "（LLM 未返回推理，已根据方法论完成维度筛选）"
```

**`_run_step()` — Step 3 结构决策（`frost_agent.py:522`）**：

```python
# 修改前
reasoning = parsed.get("reasoning", "")[:300]

# 修改后
reasoning = parsed.get("reasoning", "")[:300] or "（LLM 未返回推理，已根据维度筛选结果设计章节结构）"
```

### 3.2 增加原始响应日志（解决不可观测）

> 基于同行评议建议 P0-3，属于阶段一范围。

在 `_run_step1` 和 `_run_step` 两个函数的 `call_llm` 返回后、`_parse_json_response` 解析前，各加 1 行：

```python
logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})
```

**位置**：
- `frost_agent.py:487` — `_run_step1()` 中
- `frost_agent.py:515` — `_run_step()`（Step 2/3/4 共用）中

**关键设计决策**：日志在 `_parse_json_response` 之前记录，确保即使 JSON 解析失败也能看到 LLM 原始输出。Step 4 的原始文本在 `_strip_preamble` 剥离开场白之前记录，保留完整的 LLM 响应。Step 5 走独立 `evaluator.py` 模块内部调用 LLM，不在本次修改范围。

### 3.3 Prompt 侧增加非空约束（降低触发概率）

> 基于同行评议建议 P1-4，属于阶段一范围。

在 `context_builder.py` 的 `STEP_TASKS["1_info_collection"]` 末尾追加一行：

```
注意：summary 字段不可为空，必须包含对搜索结果的归纳摘要（至少 50 字）。
```

与代码硬兜底并行：prompt 软约束降低触发概率，代码硬兜底保证不崩溃。两步互不替代。

---

## 四、为什么这么改

**没有选择修改 `models.py` 放松 `reasoning` 约束**。`reasoning: min_length=1` 是 v4 故意收紧的设计——强制每步留下可审计的推理痕迹。如果改成 `Optional[str] = ""`，表面解决了报错，但放弃了审计能力。

**没有仅依赖 prompt 软约束**。加强 prompt 能降低 LLM 留空的概率，但不能保证 100%。LLM 是非确定性的，prompt 指令是软约束而非硬约束。因此 prompt 加约束和代码硬兜底并行使用，互为补充。

**选择 `or` 硬兜底 + 原始日志 + prompt 约束三管齐下**：代码兜底保证不崩溃 → 日志保证可观测 → prompt 约束降低触发频率。每一步改动都很小（共 7 行），但覆盖了"止血、诊断、预防"三个层面。

---

## 五、已知局限（阶段一范围内已解决 / 未解决）

| 局限 | 状态 | 说明 |
|------|------|------|
| 空字段导致 Pydantic 崩溃 | 已解决 | `or` fallback 硬兜底 |
| 无法区分 LLM 空字段 vs JSON 解析失败 | 已解决 | 原始响应日志在解析前记录，下次触发时可定位根因 |
| Prompt 未要求 `summary` 非空 | 已解决 | `context_builder.py` 增加非空约束 |
| 降级发生后后续步骤和用户不感知 | **未解决，延后** | 见下方「六、延后改进」 |


---

## 六、延后改进：`quality_flags` 跨步骤异常传递机制

> 决策：不在阶段一实施，作为阶段二 Session Event Log 升级的配套改进。

### 6.1 问题

`or` fallback 防止了崩溃，但如果 LLM 频繁返回空字段，系统会静默地用占位符替代真实推理。这个降级发生后：

- Step 2 不知道 Step 1 的 reasoning 是代码兜底的
- Step 5 Evaluator 只看最终报告文本，不知道地基曾经松动
- 使用者看到一份 Step 5 自检 pass 的报告，但 Step 1 的信息基础可能不扎实

### 6.2 方案（已设计，待实施）

**StepOutput 增加 `quality_flags` 字段**：

```python
# models.py
class StepOutput(BaseModel):
    # ... 现有字段 ...
    quality_flags: list[str] = Field(
        default_factory=list,
        description="该步骤发生的质量降级标记。示例：['llm_empty_field:summary', 'search_partial_failure:2/3']",
    )
```

**Step 6 汇总 `quality_flags`，在报告尾部增加「生成过程异常记录」区块**，让使用者能直接看到哪些步骤被降级过，不需要翻日志。

### 6.3 延后理由

1. `StepOutput` 数据模型扩展 + 报告输出格式变更，超出了 v4 阶段一的"跑一次出高质量报告"定位
2. 在阶段二 Session Event Log 升级为 JSONL 持久化时一并引入，可以一次性完成"日志结构化 → 异常汇聚 → 报告末展示"的完整链路
3. 不影响当前 Demo 的验收标准（阶段一验收不要求跨步骤异常感知）


---

## 七、更远期改进：Evaluator 感知 `quality_flags`

> 决策：阶段二或阶段三考虑，不进入阶段一。

当前 Evaluator 的设计约束是"只看最终报告文本，不接收 Step 1-4 的 reasoning"，目的是防止 Self-Evaluation Bias。但这个约束也导致 Evaluator 无法发现步骤级降级。

当 `quality_flags` 机制在阶段二引入后，阶段二/三可以让 Evaluator 在审查同时检查 `quality_flags`：如果存在降级标记，即使报告文本看起来合格，也应降低总体置信度或强制要求人工复核。

但如果过早让 Evaluator 感知步骤级信息，可能会破坏"独立审查"的设计原则。需要在阶段二的架构评审中重新评估这个 trade-off。

---

## 八、同行评议来源

本文档的三层修复方案（`or` fallback → 原始日志 → prompt 约束）以及延后改进（`quality_flags`、Evaluator 感知）的设计思路，来源于对 `kimi产出的文档/对fix-LLM空字段的评估与建议.md` 的分析和取舍。采纳了 P0-3（原始日志）、P1-4（prompt 非空约束）；P0-1&2（`quality_flags`）和 P3-6（Evaluator 感知 flags）记录为延后改进。
