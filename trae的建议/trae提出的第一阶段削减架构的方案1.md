我换个视角——不再拿 Brief 当合规检查表，而是站在"要给行业定义分析师做一个能用的 Demo"这个立场上重新审视。

---

## 判断逻辑

Demo 需要同时满足三个目标，按优先级：

| 优先级 | 目标 | 含义 |
|--------|------|------|
| P0 | **跑通方法论管线** | 输入行业名，六步走完，产出符合方法论标准的报告 |
| P0 | **通过验收标准** | Step 5 自检 pass、无禁止内容、推理可见 |
| P1 | **给人看时不尴尬** | 不会因为一次 API 超时就崩溃、输出有基本的结构化和可读性 |
| P2 | **未来能升级** | 接口设计不把路堵死，但不需要现在就实现 v3 功能 |

---

## 完整做（6 项）

这些直接服务于 P0/P1，不能省：

### 1. 核心 4 文件 + 六步管线
`frost_agent.py`、`models.py`、`methodology_loader.py`、`requirements.txt`。这是产品本身，没有商量的余地。

### 2. Context Builder
不是因为它叫"五层组装"所以要做，而是因为**方法论按步骤切片注入**是项目 Brief 的硬约束（约束 #5）。Step 1 需要看到 H1-H4 + P0-P3，Step 5 只需要看到 C1-C5。如果每个步骤都把整本方法论文档塞进去，一是浪费 token，二是模型会被不相关的规则干扰。Context Builder 的"切片 + 组装"是正确做法，而且实现不复杂——本质就是字符串拼接。

做减法：保留切片逻辑和组装逻辑，去掉"五层"的形式化命名。核心只需要三层：静态身份 + 当前步骤方法论切片 + 前序步骤摘要。

### 3. 搜索并行 + 结果压缩
"至少 3 轮搜索"是硬约束（约束 #4）。串行 3 轮搜和并行 3 个 query 搜，对 Demo 体验的差异很大——串行可能要等 15-30 秒，并行 5-8 秒。对于给分析师演示的场景，"等 8 秒 vs 等 30 秒"就是"能用 vs 尴尬"的区别。

结果压缩也是必需的——3 个 Tavily query 的原始返回量可能上万 token，不压缩直接塞给 LLM 既浪费又可能超 context window。

### 4. StepBudget 数据模型
只定义不做强执行（架构 v2 也说了"v2 仅定义预算上限，不自动拦截超支"）。但它作为约束声明很有价值——给每个步骤一个"预期消耗"的参照，出问题时能快速判断是哪个步骤异常。

### 5. Independent Evaluator（独立 LLM 审查）
这一步做不做，直接决定"Step 5 自检能全部 pass"这个验收标准是真实过还是走过场。同一个 LLM 生成报告再自己检查，几乎一定会给通过——这不是模型能力问题，是 Self-Evaluation Bias。独立 LLM 调用（不同的 system prompt，定位为"挑剔的审查员"）成本不高（一次额外 API 调用），但对报告质量的提升是实质性的。

**注意**：保留"独立审查"，但**不做自动修正闭环**。Evaluator 的职责止于"审查 + 输出问题列表"，修不修由后续逻辑（或人工）决定。

### 6. methodology_loader（按 step_id 切片）
方法论外部加载、按步切片注入——这既是 Brief 约束也是架构正确性要求。但它不是"基础设施"，它是核心管线的一部分。`methodology_loader.py` 应该是一个不到 100 行的文件：读取方法论 markdown，按 `## 三、判断原则` 这样的章节标题做简单的正则切分。

---

## 打桩做（5 项）

保留接口和数据结构，实现从简（甚至空实现），为将来升级留空间但不拖累 Demo 开发：

### 1. Circuit Breaker → 简化为 `retry_on_failure(max_retries=2)`

**打桩方案**：
```python
# 不引入状态机（CLOSED/OPEN/HALF_OPEN）
# 只做 try/except + 计数 + 延迟重试
async def call_with_retry(fn, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)
```

理由：Demo 场景下一次运行 5-6 个 LLM 调用，单次失败概率低，连续失败概率极低。完整 Circuit Breaker（状态机 + 半开探测 + 恢复超时）是为"连续几百次调用中防止雪崩"设计的，Demo 用不上。但保留 `call_with_retry` 这个函数签名和基础重试逻辑，未来要升级到完整 Circuit Breaker 只需替换内部实现。

### 2. Session Event Log → 简化为 `print()` 结构化日志

**打桩方案**：保留 `SessionEventLog` 类名和 `log()` 方法签名，底层先 `print()` 到 stdout（带 `[STEP]` `[ERROR]` 前缀）加一个可选的文本文件写入。不做 JSONL 结构化、不做崩溃恢复读取、不做事件类型枚举。

理由：Demo 阶段日志的主要消费者是**开发者调试**和**演示时让人看到进度**，不是审计系统。`print()` 已经满足这个需求。

### 3. Checkpoint Manager → 简化为 `save_result()` / `load_result()`

**打桩方案**：保留接口，底层只做"每步完成后把当前 State 序列化到一个 JSON 文件"。不做恢复逻辑（启动时不检测已有 checkpoint），不做增量写入，不做多版本管理。

理由：单次 CLI 运行崩溃的概率极低。但保留 `save_checkpoint(state)` 这个接口是好的——当分析师说"刚才跑到 Step 4 断了，能不能重跑不用重新搜索？"时，有接口比没有好十倍。

### 4. Sprint Contract → 把验收标准写入步骤 prompt，不做协商

**打桩方案**：架构 v2 中每个步骤的 Sprint Contract 验收标准（如 Step 2 的"选中的维度覆盖 ≥ 2 个独立侧"）是有价值的内容——它告诉 LLM "做到什么程度算完成"。但这些验收标准不需要一个独立的 `SprintContract` 对象和"协商"流程。直接把它们写进对应步骤的 task prompt 即可。

`SprintContract` 数据模型可以保留在 `models.py` 里（将来有用），但 Orchestrator 中不实例化、不协商。

### 5. Token Audit → 简化为报告尾部一行统计

**打桩方案**：在 `StepOutput` 中加一个可选字段 `token_usage: dict | None`，每步 LLM 调用完后顺手填进去。报告输出时在末尾附一行"本次生成共消耗约 X tokens"。不做持久化审计日志、不做成本换算、不做超支告警。

理由：对 Demo 演示场景，"用了多少 token"是分析师可能会问的。花 5 行代码满足这个好奇心是值得的。但全功能 Token Audit 是给运营用的。

---

## 不做（3 项）

Demo 阶段完全跳过，接口也不留：

### 1. Evaluator-Optimizer 自动修正闭环

Step 5 的输出止于"C1-C5 逐项 PASS/FAIL + 问题描述"。不做自动回到 Step 4 重跑。这是行为契约变更，不只是复杂度问题。

### 2. Model Router（多模型降级链）

全链路用一个模型（推荐 `claude-sonnet-4-5` 或等价的 `deepseek-v4-pro`）。Demo 的第一优先级是功能正确性，不是成本优化。换模型引入的行为差异在 Demo 阶段是噪音。

### 3. methodology/ 目录拆分

保持 `方法论-v2.md` 单文件。拆成 8 个小文件 + `_meta.yaml` 的好处（独立版本控制、增量更新）在方法论稳定的 Demo 阶段不成立。`methodology_loader.py` 在单文件上做章节正则切分即可，未来要拆分时只改 loader 不改管线。

---

## 汇总

```
完整做（6）：核心管线 + Context Builder + 搜索并行/压缩 + StepBudget + 
            Independent Evaluator + methodology_loader
打桩做（5）：Circuit Breaker → retry | Event Log → print |
            Checkpoint → save_json | Sprint Contract → prompt内嵌 |
            Token Audit → 报告尾部统计
不做（3）： 自动修正闭环 | Model Router | methodology/拆分
```

这样 Demo 版本的 `frost_agent.py` 大约 300-400 行（含六步逻辑 + 简化版 Harness），加上 `models.py`（~50 行）、`methodology_loader.py`（~80 行），总共约 500 行 Python——比架构 v2 规划的 14 个文件大幅精简，但核心方法论管线的完整性和报告质量不妥协。