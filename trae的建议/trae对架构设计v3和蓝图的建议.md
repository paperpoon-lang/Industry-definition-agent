## 一、管线正确性问题（3 项）及解决方案

### 问题 1：Context Builder 丢失任务指令层

**现状**（[架构设计-Agent架构-v3.md#L61-L69](file:///Users/paper/trae_project/行业定义agent/kimi产出的文档/架构设计-Agent架构-v3.md#L61-L69)）：`build()` 只组装三层——静态身份、方法论切片、前序摘要。行业名称和当前步骤的具体任务描述没有被注入。以 Step 4 为例，LLM 不知道"当前行业是什么"、"该步骤该写什么"，只能靠方法论切片中的通用规则猜测。

**解决方案**：在 `build()` 中增加第四层，包含行业名 + 当前步骤的任务指令。

```python
# context_builder.py — 修改 build() 方法

STEP_TASKS = {
    "1_info_collection": (
        "请搜索并整理以下行业的基础信息：{industry}。\n"
        "要求：覆盖官方定义、关键政策/标准、结构性影响因素、相邻行业。\n"
        "标注信息来源和可信度（P0-P3）。"
    ),
    "2_dimension_screening": (
        "基于 Step 1 的信息，对行业「{industry}」应用 H1-H4 维度筛选原则。\n"
        "选出核心维度，并明确记录：选了什么、放弃了什么、为什么。"
    ),
    "3_structure_decision": (
        "为行业「{industry}」设计报告结构。\n"
        "每章对应 Step 2 的至少一个维度。\n"
        "禁止出现竞争格局/市场规模/投资建议类章节。"
    ),
    "4_content_generation": (
        "为行业「{industry}」撰写完整的行业定义报告正文。\n"
        "严格禁止：企业排名、市场份额、竞争格局分析、市场规模预测、投资建议。\n"
        "每个关键判断必须附带推理链和置信度标注。\n"
        "所有数据必须标注来源和可信度。"
    ),
    "5_self_check": (
        "对行业「{industry}」的报告执行 C1-C5 自检清单。\n"
        "你是一个严格的审查员，倾向于发现问题而非确认一切正常。"
    ),
}

class ContextBuilder:
    def build(self, step_id: str, state: ReportState) -> str:
        parts = [
            self._static_identity(),
            self._methodology_slice(step_id),
            self._task_directive(step_id, state.industry_name),  # 新增第四层
            self._previous_summary(state),
        ]
        return "\n\n---\n\n".join(parts)

    def _task_directive(self, step_id: str, industry: str) -> str:
        """当前步骤的具体任务指令（最高权重，放在摘要之前）"""
        template = STEP_TASKS.get(step_id, "请执行当前步骤。")
        return f"## 当前任务\n\n{template.format(industry=industry)}"
```

改动量：~30 行，P0。

---

### 问题 2：Step 5 失败后管线直接输出不合格报告

**现状**（[架构设计-Agent架构-v3.md#L386-L416](file:///Users/paper/trae_project/行业定义agent/kimi产出的文档/架构设计-Agent架构-v3.md#L386-L416)）：Orchestrator 执行完 `step5_self_check` 后，无论结果 `pass` 还是 `fail_with_fixes`，都直接进入 `step6_output` 输出报告。这意味着自检 FAIL 的报告也会被输出，且没有任何警告标记。

**解决方案**：在 Step 5 和 Step 6 之间插入判断分支 + 报告头部注入警告。

```python
# frost_agent.py — 修改 run() 中的输出段

    # Step 5 完成后，检查自检结果
    step5 = next(s for s in state.steps if s.step_id == "5_self_check")
    eval_result = step5.result
    self_check_passed = eval_result.get("overall") == "pass"

    if not self_check_passed:
        failed = eval_result.get("failed_dimensions", [])
        issues = eval_result.get("issues", [])
        
        warning = (
            "\n\n---\n\n"
            "## ⚠️ 自检未通过\n\n"
            f"以下维度未通过审查：{', '.join(failed)}\n\n"
        )
        for issue in issues:
            warning += f"- {issue}\n"
        warning += "\n**请人工审查后再使用此报告。**\n"
        
        state._self_check_warning = warning
        
        logger.log("self_check_failed", {
            "failed_dimensions": failed,
            "issues": issues,
        })
        print(f"\n[警告] 自检未通过 — 失败维度: {failed}")
        print("[警告] 报告已生成但包含审查警告，请人工复核\n")

    # Step 6: 输出（注入警告标记）
    final_report = step6_output(state)
```

同时在 `step6_output()` 中：
```python
def step6_output(state: ReportState) -> str:
    report_body = _assemble_report_body(state)
    header = ""
    if hasattr(state, "_self_check_warning"):
        header = state._self_check_warning
    # 尾部追加方法论附注...
    footer = _methodology_appendix(state)
    return header + report_body + footer
```

改动量：~25 行，P0。

---

### 问题 3：SLICE_MAP 关键词"内容生成"不匹配关键约束章节

**现状**（[架构设计-Agent架构-v3.md#L200](file:///Users/paper/trae_project/行业定义agent/kimi产出的文档/架构设计-Agent架构-v3.md#L200)）：Step 4 的 `SLICE_MAP` 包含 `["Hard Rules", "推理展示", "内容生成"]`。验证实际的匹配结果：

| 关键词 | 匹配到的章节 | 是否包含 Step 4 所需约束 |
|--------|-------------|------------------------|
| `"Hard Rules"` | 二、不可违背的约束（R1-R5） | ✅ 但 R1-R5 **不含**"严禁竞争排名/市场份额/投资建议" |
| `"推理展示"` | 四、推理展示要求 | ✅ |
| `"内容生成"` | 七、执行流程（仅因代码块中出现了这个词） | ❌ 七节只是流程描述，不含实际规则 |

**关键缺失**：三.3 报告范围约束——"不要输出竞争排名/市场份额/投资建议"这一约束在 `方法论-v2.md` 中位于三.3 节，但 Step 4 的切片中没有 `"范围约束"` 关键词。

**后果**：Step 4 生成报告时，LLM 看不到"哪些内容不能写"这一核心约束，只靠 `_static_identity()` 中的一句话"报告不包含竞争排名、市场规模预测、投资建议"——这一句太弱，可能被方法论切片淹没。

**解决方案**：

```python
# methodology_loader.py — 修改 SLICE_MAP

SLICE_MAP = {
    "1_info_collection":       ["信息优先级", "参考框架", "Hard Rules"],
    "2_dimension_screening":   ["维度筛选原则", "Heuristics", "自检清单"],
    "3_structure_decision":    ["报告结构", "范围约束"],
    "4_content_generation":    ["Hard Rules", "推理展示", "范围约束"],  # "内容生成"→"范围约束"
    "5_self_check":            ["自检清单"],
}
```

同时增加切片验证——如果匹配结果为空，回退到全量方法论并打警告：

```python
def load_slice(step_id: str) -> str:
    full = load_methodology()
    keywords = SLICE_MAP.get(step_id, [])
    sections = re.split(r'(?=^## )', full, flags=re.MULTILINE)
    matched = [s for s in sections if any(kw in s for kw in keywords)]

    if not matched or sum(len(s) for s in matched) < 100:
        print(f"[警告] Step {step_id} 的方法论切片为空或过短，回退到全量方法论")
        return full

    return "\n\n".join(matched)
```

改动量：~15 行，P1。

---

## 二、工程估算问题（2 项）及解决方案

### 问题 4：文档缺少单次运行的成本和延迟估算

**解决方案**：在 v3 文档中增加以下小节（放在验收标准之前）：

```markdown
### 成本估算（单次运行，推测值，待实测）

| 步骤 | 估计 input tokens | 估计 output tokens | 估计耗时 |
|------|-------------------|--------------------|----------|
| Step 1: 搜索+总结 | ~8,000 | ~2,000 | 8-20 秒 |
| Step 2: 维度筛选 | ~6,000 | ~1,500 | 5-10 秒 |
| Step 3: 结构决策 | ~5,000 | ~1,000 | 5-10 秒 |
| Step 4: 内容生成 | ~12,000 | ~8,000-15,000 | 15-35 秒 |
| Step 5: 自检 | ~10,000 | ~1,500 | 5-15 秒 |
| **端到端总计** | **~41,000** | **~18,000-21,000** | **~40-90 秒** |

- 单次运行 API 成本：约 $0.03（以 deepseek-v4-pro 计价）[推测]
- 以"低空经济物流"实测值更新本表
- 端到端约 1 分钟——演示时需向观众提前说明
```

改动量：在文档中加一段，P0。

---

### 问题 5：演进路线图工作量估计系统性偏低

**现状**：阶段二声称 ~2 周，我逐项复核如下：

| 组件 | 声称 | 实际 | 被低估的原因 |
|------|------|------|-------------|
| Persistent Memory | 2-3 天 | 3-5 天 | 不只是建表——需要设计知识表示 schema、相似度匹配逻辑、缓存失效策略 |
| Web UI (Streamlit) | 2-3 天 | 4-5 天 | "显示进度"意味着 WebSocket/SSE 实时推送六步状态——不是 Streamlit 默认 best case |
| Circuit Breaker 完整化 | 1 天 | 1.5-2 天 | 状态机 + 分组 + 与所有 LLM 调用点集成测试 |
| Sprint Contract 自动协商 | 1 天 | 2-3 天 | LLM 生成验收标准涉及 prompt engineering + 验收标准可验证性验证 |
| **阶段二总计** | **~2 周** | **~3-4 周** | **偏差 50-100%** |

阶段三同类偏差（Model Router 2天→3-4天）。

**解决方案**：在演进路线图中修正工作量估计，或在每个阶段末尾加一句诚实声明：

```markdown
**预计工作量**：~3-4 周（1 人）
> 注：以上估计基于单人全职开发，不含与行业定义分析师沟通需求的时间。
> 若方法论在此期间发生变更（新增规则 H5 等），需要额外预留 3-5 天。
```

---

## 三、架构演进路线图的完整评估

### 3.1 肯定

- **四阶段递进逻辑成立**：Demo MVP → 内部试用 → 批量处理 → 生产级，触发条件与新增需求的对应关系自然
- **接口兼容性策略方向正确**：`call_with_retry()` → `CircuitBreaker.call()` 的签名兼容设计是务实的
- **每个组件的演进路径可追溯**：从 v3 状态到阶段四，每个 Harness 组件的每次升级都有明确描述

### 3.2 三个缺陷

**缺陷 1：接口兼容性只在签名层面成立，行为语义差异被忽略**

路线图第三章展示的升级路径只保证了函数签名不变，但以下行为差异在真实升级时会变成问题：

| 组件 | v3 行为 | 升级后行为 | 调用方影响 |
|------|---------|-----------|-----------|
| `call_with_retry()` → `CircuitBreaker.call()` | 无状态函数 | 有状态方法（需持实例） | 调用方从 `await call_with_retry(fn)` 变为 `await breaker.call(fn)`——Orchestrator 需要管理 breaker 实例 |
| `SimpleLogger.log()` | 同步 print | JSONL 文件写入 | 文件写入失败会抛异常，v3 的 print 不会——需在所有调用点加 try/except |
| `save_checkpoint()` | 单文件覆盖 | 多版本 + 过期清理 | 磁盘占用行为变化——需在文档中说明 |

**建议**：在"接口兼容性保证"章节末尾加一段"已知的行为语义差异"，标注哪些差异需要调用方适配。

**缺陷 2：缺少"不演进"的退出条件**

当前每个阶段只有一个触发条件（如"分析师反馈良好"），没有"什么情况下不进入下一阶段"。如果 Demo 发现 Independent Evaluator 的实际效果不达预期（如 C1-C5 通过与人工评审一致性 < 70%），是否还升级到阶段二？路线图应该回答这个问题。

**建议**：每个阶段增加"闸门条件"：

```markdown
### 阶段一 → 阶段二 的闸门条件

进入阶段二前必须同时满足：
- [ ] 3 个不同行业的自检 C1-C5 通过率 ≥ 90%
- [ ] 单次运行端到端耗时 ≤ 120 秒
- [ ] 分析师试用的定性反馈 ≥ 3 条正向评价

任意一条不满足 → 停留在阶段一修复，不进入阶段二。
```

**缺陷 3：LangGraph 集成在阶段四缺乏需求论证**

路线图在阶段四规划了 LangGraph 集成（5-7 天），但行业定义 Agent 的六步流程是**严格线性的**——从 Step 1 到 Step 6 永远按固定顺序执行。LangGraph 的价值在于条件分支、子图、断点重放。用 LangGraph 替换一个 for 循环，付出了依赖引入 + 学习成本 + 调试复杂度三重代价，换来的功能增益是**零**。

**建议**：将 LangGraph 集成从"阶段四升级项"移到"附录：可选技术探索"，并标注触发条件：

```markdown
### LangGraph 集成（可选，仅当出现以下需求时考虑）
- 步骤间出现条件分支（如"Step 3 决策后可能跳过 Step 4"）
- 需要子图嵌套（如 Step 1 内部有独立的搜索→压缩→总结 DAG）
- 需要 Human-in-the-Loop 断点重放

当前六步流程为严格线性，LangGraph 不带来功能增益。
在阶段四引入 LangGraph 纯属为未来非线性流程预留接口，
实际收益为零，不建议在当前路线图中作为 P0 升级项。
```

---

## 四、汇总

| # | 问题 | 严重程度 | 修改文件 | 行数 |
|---|------|----------|----------|------|
| 1 | Context Builder 缺任务指令层 | P0 | `context_builder.py` | +30 |
| 2 | Step 5 失败后直接输出不合格报告 | P0 | `frost_agent.py` | +25 |
| 3 | SLICE_MAP 关键词不匹配关键约束 | P1 | `methodology_loader.py` | +15 |
| 4 | 文档缺少成本/延迟估算 | P0 | `架构设计-Agent架构-v3.md` | +20 |
| 5 | 演进路线图工作量估计偏低 | P2 | `架构演进路线图.md` | 修正数字 |
| + | 演进路线图缺退出条件 | P2 | `架构演进路线图.md` | +15/阶段 |
| + | LangGraph 集成缺乏需求论证 | P2 | `架构演进路线图.md` | 移至附录 |

前 4 项应在开发 `frost_agent.py` 之前修复，总计约 90 行新增代码 + 文档修改。后 3 项是路线图文档自身的修正，不阻塞 Demo 开发。