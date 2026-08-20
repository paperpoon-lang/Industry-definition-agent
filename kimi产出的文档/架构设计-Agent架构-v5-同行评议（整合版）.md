# 对《架构设计-Agent架构-v5》的同行评议（整合版）

> **评议对象**：`架构设计/架构设计-Agent架构-v5.md`（文档内标注 v5.2，阶段二 A 组，2026-06-18）
> **评议基准**：`demo/` 目录下的实际代码（当前为 v4 实现）
> **评议日期**：2026-06-24
> **评议类型**：设计评审 + 工程批判整合评议
> **评议方法**：架构一致性审查与工程视角批判两条独立路径交叉验证后整合

---

## 〇、评议立场声明

本次评议采取同行评议立场，而非权威裁判。我们的判断基于对设计文档与实际代码的交叉阅读，但承认以下局限：

1. 评议者未参与项目实际开发，对某些设计决策的上下文（如阶段一开发日志、Kimi 前序评议的完整讨论链）掌握不全；
2. 部分估算（如成本、延迟）基于代码中的 `max_tokens` 上限和经验推测，可信度有限，已在文中标注；
3. 评议目的是帮助作者在编码前发现问题，而非否定设计方向。

**我们的总体判断是：v5.2 的设计方向值得肯定，但文档与代码现状之间存在系统性偏差，部分新增设计存在接口层面的硬性矛盾，建议在进入编码阶段前修订。**

---

## 一、总体评价

v5.2 在 v4 基础上系统性地补齐了三块基础设施短板：可观测性（JSONL + trace_id）、可恢复性（多版本 Checkpoint）、降级可视化（quality_flags）。设计分层清晰，对"做什么"和"不做什么"有明确边界，符合"Start simple"原则。这些方向我们认为是对的。

但评议中我们发现两个层面的系统性问题，值得作者重视：

**第一层：文档与代码的现状偏差。** v5.2 文档描述了 7 项新增/升级组件，但经逐文件核查，`demo/` 目录下代码 100% 停留在 v4 阶段——`models.py` 无 `QualityFlag`、`harness/session_log.py` 仍是 `SimpleLogger`、`harness/checkpoint.py` 仍是覆盖写入、`harness/token_audit.py` 与 `harness/output_safety.py` 不存在、`方法论/` 拆分目录不存在。文档语气却像在描述"增量集成"，验收标准表格列出 27 项验收项，语气是"实现后验证"。这种偏差如果不在文档中显式标注，容易让后续协作者（包括 AI 编码助手）产生"哪些已存在、哪些需要新建"的误判。

**第二层：v5.2 新增的搜索补搜循环存在接口层面的硬性矛盾。** 这是两路独立评议都识别到的同一问题，详见下文 3.1 节。

此外，评议中还发现若干工程层面的担忧——有些是确凿的接口/逻辑矛盾，有些则是我们对生产可靠性的忧虑，我们在文中尽量区分这两类。

---

## 二、评议方法与评估框架

本次评议由两条独立路径并行展开后整合：

- **路径 A（架构一致性审查）**：聚焦文档内部一致性、文档与 v4 代码的兼容性、State 健全性、最佳实践对标。
- **路径 B（工程视角批判）**：聚焦工程五问（成本/延迟/错误处理/恢复/并发）、薄弱环节、过度乐观假设、生产部署风险。

评估维度与权重如下：

| 维度 | 权重 | 说明 |
|---|---|---|
| 内部一致性 | 20% | 文档自身矛盾会导致实现时无法判断以哪个为准 |
| 代码兼容性 | 20% | v5 声称"增量集成、不重写"，兼容性是核心承诺 |
| State 健全性 | 15% | A2 架构的核心是 State 驱动 |
| 错误处理与恢复 | 15% | LLM/搜索均不可靠，降级与恢复是工程刚需 |
| 可观测性 | 10% | JSONL + trace_id + Token Audit 是 v5 主要升级点 |
| 成本/延迟 | 10% | Demo 阶段需控制单次运行成本 |
| 最佳实践对标 | 10% | 对标 State-driven / Reflection / Checkpoint 等模式 |

评级标准：A（可直接指导实现）/ B（少量小问题，修复后可实现）/ C（多处矛盾或缺陷，需返工部分设计）/ D（核心设计有重大缺陷，需重新设计）。

---

## 三、主要发现

### 3.1 两路评议共同识别的接口矛盾（建议 P0）

**问题**：v5.2 文档第 2.7 节明确声称"不改 search.py 接口"，但其搜索补搜循环的代码骨架调用 `search_with_fallback` 的方式与实际接口完全不兼容。

文档中的调用方式（[架构设计-Agent架构-v5.md:1087](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1087) 附近）：

```python
for query in static_queries:
    results = await search_with_fallback(query)   # 传入单个 query 字符串
    all_results.extend(results)                    # 期望返回 list
```

实际接口（[search.py:122](file:///Users/paper/trae_project/行业定义agent/demo/search.py#L122)）：

```python
async def search_with_fallback(industry: str, tavily_api_key: str) -> dict[str, Any]:
    # 传入行业名 + API key，内部生成 3 个 query
    # 返回 {"results": {query: [items]}, "data_gaps": [...], "error_count": int}
```

矛盾点有三处：
1. **参数数量**：设计传单个 query 字符串；实际需要 `(industry, tavily_api_key)` 两个参数
2. **语义**：设计传入的是"补搜 query"；实际第一个参数是"行业名"，内部用 `SEARCH_QUERIES` 模板生成 3 个静态 query
3. **返回值结构**：设计期望 `list`（用 `extend` 展开）；实际返回 `dict`（含 `results`/`data_gaps`/`error_count`）

**为什么我们认为这是 P0**：这是 v5.2 的核心新增功能，接口不兼容意味着"不改 search.py 接口"的承诺无法兑现。若实现者按文档骨架直接编码，代码会立即因参数不匹配崩溃。两路评议独立得出同一结论，我们认为这并非评议者的误读。

**可能的修正方向**（供作者参考，非定论）：
- 方案 A：在 `search.py` 中新增 `search_single_query(query, tavily_api_key) -> list[dict]`，补搜循环调用新函数。这确实"改了 search.py"但只是新增不修改现有接口，建议同步修正文档中"不改 search.py 接口"的声明。
- 方案 B：修改补搜循环骨架，复用现有 `search_with_fallback` 的行业名语义，但这样补搜的就不是 FM 建议的具体 query 了，与设计意图不符。

无论选哪个方案，文档中"不改 search.py 接口"的声明都需要修订。

### 3.2 文档与代码实现状态的系统性偏差（建议 P0）

经逐文件核查，v5 文档描述的组件与 `demo/` 目录下实际代码的对应关系如下：

| 文档声称 | 实际代码 | 状态 |
|---|---|---|
| `models.py` 新增 `QualityFlag` + `quality_flags` 字段 | [models.py](file:///Users/paper/trae_project/行业定义agent/demo/models.py) 文件头标注 "v4 Demo MVP"，无 `QualityFlag` 类 | 未实现 |
| `STEP_BUDGETS["1_info_collection"].timeout_seconds = 180` | [models.py:163](file:///Users/paper/trae_project/行业定义agent/demo/models.py#L163) 实际值为 `120` | 未实现 |
| `STEP4_MAX_TOKENS` 默认 `10000`（文档） | [frost_agent.py:64](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L64) 实际默认 `16000` | 文档与代码不一致 |
| `harness/session_log.py` 升级为 `SessionEventLog`（JSONL + trace_id） | 仍是 `SimpleLogger`（仅 print，18 行） | 未实现 |
| `harness/checkpoint.py` 升级为 `CheckpointManager`（多版本） | 仍是 v4 打桩（覆盖写入，41 行） | 未实现 |
| 新增 `harness/token_audit.py` + `harness/output_safety.py` | 目录下只有 3 个文件，两个新文件不存在 | 未实现 |
| `方法论/` 目录拆分（_meta.yaml + 4 模块） | `方法论/` 目录不存在，只有单文件 `demo/方法论-v2.md` | 未实现 |
| `methodology_loader.py` 升级支持拆分模块 | 仍是 v4 版本（163 行，无 `_meta.yaml` 逻辑） | 未实现 |

**我们的担忧**：v5.2 验收标准表格列出 27 项验收项，语气是"实现后验证"，但当前 0 项可通过。文档没有在任何地方标注"当前实现状态：未实现"。这并非设计本身的问题，而是文档呈现方式的问题——但它的实际危害不容忽视：

1. 后续协作者（包括 AI 编码助手）可能误以为某些组件已存在，只生成"调用代码"而不生成"组件实现"；
2. 已有的 Kimi 前序评议也在评审一个"设计文档"，但评议链中没有人指出"这个设计完全没有落地"——评议对象逐渐偏移，从"评审设计"变成"评审一个被当作半成品的纯设计"。

**建议**：在文档开头添加"当前实现状态"章节，明确标注每个组件的状态（未实现/部分实现/已完成）。这是一项 < 1h 的文档工作，但能显著降低后续协作的沟通成本。

### 3.3 `load_version` 的 glob 模式可能无法匹配无 request_id 的文件（建议 P0，潜伏）

**问题**：[CheckpointManager.load_version](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L649) 的 glob 模式与 [save](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L581) 的文件命名规则不匹配。

`save` 生成的文件名（无 request_id 时）：`{safe_name}_{timestamp}_{step_id}.json`

`load_version` 的 glob 模式：`{safe_name}_{timestamp}_{step_id}_*`（注意末尾的 `_*`）

矛盾点：glob 模式要求 step_id 后必须有下划线 + 任意字符。但无 request_id 时文件名是 `{step_id}.json`，step_id 后直接是 `.json`，不匹配 `_{step_id}_*` 模式。

**影响判断**：v5 阶段不使用 `request_id`（文档明确说"阶段三并发场景使用"），因此所有 v5 checkpoint 都无法被 `load_version` 找到。虽然 `load_version` 是阶段三 Evaluator-Optimizer 才用，v5 不触发，但我们认为这是一个潜伏的 P0 bug——到阶段三会直接爆发，且届时调试成本更高。

**可能的修正**：将 glob 模式从 `{step_id}_*` 改为 `{step_id}*`，使其同时匹配有/无 request_id 的文件。工作量 < 1h。

### 3.4 Orchestrator 骨架与"六步逻辑保持不变"承诺的张力（建议 P1）

**问题**：文档第六节声称"frost_agent.py 的六步逻辑（Step 1-5）保持不变，只修改导入和调用点"，但第五节的 Orchestrator 骨架是一次显著重构。

文档骨架（[架构设计-Agent架构-v5.md:1308-1328](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1308) 附近）：

```python
steps = [
    ("1_info_collection",      step1_info_collection),
    ("2_dimension_screening",  step2_dimension_screening),
    ...
]
for step_id, step_fn in steps:
    result = await call_with_timeout(
        lambda: step_fn(state),   # 统一签名为 step_fn(state)
        timeout_seconds=...,
    )
    state.steps.append(result)
```

实际 v4 步骤函数签名各异：
- `_run_step1(industry_name, state, logger, context_builder, mock, mock_search_mode)` — 6 个参数
- `_run_step(step_index, state, logger, context_builder, mock)` — 5 个参数
- `_run_step5(industry_name, state, logger, mock)` — 4 个参数

**我们的担忧**：v5 骨架用 `step_fn(state)` 统一签名 + 循环调度，与 v4 各步函数签名不一致，且函数名（`step1_info_collection` vs `_run_step1`）、返回值处理（骨架返回 result 再 append vs v4 直接修改 state）都不同。若实现者按骨架写，会发现需要重构所有步骤函数，与"保持不变"承诺冲突，工作量估计会严重偏低。

**建议作者澄清**：v5 骨架是伪代码示意还是可直接实现的 spec？若是伪代码，建议在文档中标注，并明确"实际实现保留 v4 的显式 if/else 逐步调用结构"。若确实要引入循环调度，建议更新工作量估计。

### 3.5 "最多 2 轮补搜"与预算上限逻辑的冲突（建议 P1）

**问题**：文档声称"最多 2 轮补搜，总共 ≤5 个 query"，但预算逻辑使第 2 轮几乎不可能执行。

逻辑分析：
- 首轮静态搜索：3 个 query → `queries_used = 3`
- `MAX_TOTAL_QUERIES = 5`
- 每轮补搜：`queries_to_search = suggested_queries[:min(2, remaining_budget)]`

第 1 轮：`remaining_budget = 5 - 3 = 2`，搜索最多 2 个 query → `queries_used = 5`
第 2 轮：`queries_used(5) >= MAX_TOTAL_QUERIES(5)` → break

**结论**：只要第 1 轮 FM 返回 2 个 suggested_queries，第 2 轮就永远不会执行。只有当 FM 每轮恰好返回 1 个 query 时，2 轮才可能发生。文档的"最多 2 轮"描述具有误导性，实际更接近"最多 2 个补搜 query"。

**建议**：二选一——
- 方案 A（改描述，保持简单）：将"最多 2 轮补搜"改为"最多 2 个补搜 query"，与预算逻辑一致
- 方案 B（改逻辑）：若确实要支持 2 轮，将 `MAX_TOTAL_QUERIES` 提升到 7（3 静态 + 2×2 补搜）

我们倾向方案 A，符合"Start simple"原则。

### 3.6 `STEP4_MAX_TOKENS` 代码未更新到实测推荐值（建议 P1）

**文档**（[架构设计-Agent架构-v5.md:1288](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1288)）：默认 `10000`，注释说"阶段一收尾 P0-1 成果"
**代码**（[frost_agent.py:64](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L64)）：默认 `16000`，注释说"当前值 16000 保持与 v4 一致，待二分查找后调整"
**实测报告**（[阶段一-P0-1_P0-3_实测报告.md:36-44](file:///Users/paper/trae_project/行业定义agent/开发日志/阶段一-P0-1_P0-3_实测报告.md#L36-L44)，★★★★★ [可信]）：推荐值 `10000`，理由是实测 completion_tokens 最大 3789（8000 时），10000 提供约 2.6 倍冗余，质量未下降。

**结论**：文档的 10000 是正确的（有实测支撑），是代码未更新到推荐值。代码注释"待二分查找后调整"已过时——二分查找已完成并归档。建议将 [frost_agent.py:64](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L64) 的默认值从 16000 改为 10000，并更新注释。工作量 < 1h。

> 勘误说明：本节在初版评议中标注为"待确认"，方向判断有误——我们曾怀疑文档 10000 是否正确，实测报告证实文档是对的，代码才是待更新方。

---

## 四、工程视角五问

以下五问是项目规则要求的强制覆盖。我们的回答基于代码与文档的交叉阅读，部分估算可信度有限，已标注。

### 4.1 成本

**文档覆盖情况**：部分覆盖。v5.2 新增的 FM 审查有成本估算，但全管线成本依赖阶段一实测数据，文档未直接引用。

文档给出的数据：
- 定价来源标注清晰：SiliconFlow DeepSeek-V4-Pro，¥3/M input、¥6/M output（[v5.md:386-389](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L386-L389)），可信度 ★★★★★
- v5.2 FM 审查成本估算：每次 `max_tokens=2000`，约 $0.002/次，最坏 3 次 = $0.006 额外

**阶段一 P0-3 实测数据**（[阶段一-P0-1_P0-3_实测报告.md:117-124](file:///Users/paper/trae_project/行业定义agent/开发日志/阶段一-P0-1_P0-3_实测报告.md#L117-L124)，★★★★★ [可信]，真实 API 运行）：

| 行业 | 总 Token | 输入成本（¥） | 输出成本（¥） | 总成本（¥） | 总成本（$） |
|-----|---------|------------|------------|-----------|-----------|
| 低空经济物流 | 33,415 | 0.0696 | 0.0612 | 0.1308 | 0.0182 |
| 汽车 | 34,462 | 0.0680 | 0.0708 | 0.1388 | 0.0193 |
| 新能源汽车 | 35,809 | 0.0694 | 0.0761 | 0.1455 | 0.0202 |
| **平均** | **34,562** | **0.0690** | **0.0694** | **0.1384** | **0.0192** |

实测结论：单次成本平均 $0.019，远低于 $0.10 闸门（仅占 19%）。Step 4 实际 completion_tokens 3,357-4,657，远低于 max_tokens 上限 10,000-16,000。

> 勘误说明：本节初版曾用 max_tokens 上限 × 单价估算得出 ¥0.396，并据此担忧"Step 4 单步可能超过 $0.10 闸门"。**该估算方法错误**——max_tokens 是输出上限而非实际消耗，用上限估成本如同用限速估通勤时间。经查阅 P0-3 实测报告，实际平均成本 $0.019，初版高估约 20 倍。文档"总成本远低于 $0.10 闸门"的判断有实测支撑，并非过度乐观。相关错误论断已在过度乐观假设清单（第六节）和批判性三问（第七节）中同步修正。

**仍存在的担忧**（基于实测数据重新评估）：

1. **v5.2 新增 FM 审查的增量成本未纳入实测**：P0-3 实测是 v4 数据（无 FM 审查）。v5.2 新增 FM 审查最多 3 次，文档估算额外 $0.006。但该估算只算 output（`max_tokens=2000`），未算 input（方法论信息优先级 + 搜索结果摘要）。按 v4 实测 Step 1 prompt_tokens 约 13K-15K 推测，FM 审查 input 可能 5-10K tokens/次，3 次 input 成本约 ¥0.045-0.09。叠加 v4 基线 $0.019，v5.2 总成本可能升至 $0.025-0.032，仍远低于闸门，但比文档的 $0.006 增量估算高。建议 v5.2 实现后补测。

2. **搜索 API 成本完全未提**：Tavily 搜索有独立计费，v5.2 最多 5 个 query，每个 `search_depth="advanced"`（[search.py:74](file:///Users/paper/trae_project/行业定义agent/demo/search.py#L74)）。P0-3 实测只覆盖 LLM 成本，未含搜索成本。建议补充。

3. **$0.10 闸门来源不明**：文档多次引用但未说明来源和依据。虽实测 $0.019 远低于闸门，但闸门本身的合理性仍需说明（项目预算？竞品对标？）。

### 4.2 延迟

**文档覆盖情况**：仅 v5.2 搜索补搜循环有延迟分析，全管线无端到端估算（但阶段一实测报告有数据，文档未引用）。

文档给出的数据：
- v5.2 搜索补搜：首轮 2-4s + FM 审查 ~15s/轮 × 最多 3 轮 = 最坏额外 ~45s
- Step 1 timeout 从 120s → 180s

**阶段一 P0-3 实测耗时**（[阶段一-P0-1_P0-3_实测报告.md:154-169](file:///Users/paper/trae_project/行业定义agent/开发日志/阶段一-P0-1_P0-3_实测报告.md#L154-L169)，★★★★★ [可信]，基于日志时间戳估算）：

| 行业 | max_tokens | Step 1 | Step 2 | Step 3 | Step 4 | Step 5 | 总耗时 |
|-----|-----------|--------|--------|--------|--------|--------|--------|
| 低空经济物流 | 16000 | ~90s | ~25s | ~25s | ~87s | ~30s | ~4.5 分钟 |
| 汽车 | 16000 | ~100s | ~32s | ~37s | ~73s | ~20s | ~4.4 分钟 |
| 新能源汽车 | 16000 | ~88s | ~41s | ~23s | ~105s | ~32s | ~4.8 分钟 |

实测结论：平均 ~4.5 分钟/次（远低于 v4 的 ~8 分钟）。Step 4 实测 73-105s，未触发 180s timeout。

**仍存在的担忧**：

1. **v5.2 新增 FM 审查的增量延迟未纳入实测**：P0-3 实测是 v4 数据（无 FM 审查）。v5.2 新增 FM 审查最多 3 轮，文档估算 ~15s/轮 × 3 = ~45s 额外。叠加 v4 基线 Step 1 ~90s，v5.2 Step 1 可能升至 ~135s，仍在 180s timeout 内，但余量从 90s 压缩到 45s。建议 v5.2 实现后补测。

2. **v5.2 FM 审查的 15s/轮估算缺乏依据**：文档说"~15s/轮"但未说明来源（实测？推测？）。按 v4 实测 Step 5 自检 completion_tokens 721-1249 耗时 20-32s 推测，FM 审查 max_tokens=2000 的耗时可能在 15-30s，3 轮就是 45-90s。若达 90s，叠加搜索时间可能逼近 180s timeout。

3. **搜索补搜循环的串行性未分析**：v5.2 的补搜是 `for query in queries_to_search: await search_with_fallback(query)`，串行执行。2 个补搜 query 串行可能 4-8s，建议改为 `asyncio.gather` 并行。

> 勘误说明：本节初版第 1 点称"无端到端延迟估算""典型 3-5 分钟"，第 2 点称"Step 4 生成 150K tokens 可能需要 60-120s"。前者忽略了 P0-3 实测报告已有 4.5 分钟实测数据；后者沿用了 max_tokens 上限的错误推理——实测 Step 4 completion 仅 3.4K-4.7K tokens，耗时 73-105s，与"生成 150K tokens"无关。

### 4.3 错误处理

**文档覆盖情况**：部分覆盖，有重大遗漏。

**已覆盖**：
- JSON 解析失败：三层容错（直接解析 → 代码块提取 → 花括号提取）
- v5.2 FM 审查返回非 JSON：记录 `json_parse_fallback`，跳过补搜
- 超时重试：`call_with_timeout` 提供指数退避重试

**我们的担忧**：

1. **API 限流（429）无专门处理**：`call_with_timeout` 对所有异常一视同仁地指数退避重试（[circuit_breaker.py:40-42](file:///Users/paper/trae_project/行业定义agent/demo/harness/circuit_breaker.py#L40-L42)），不区分 429 和 5xx。429 应该读取 `Retry-After` header 等待，而非盲目指数退避。SiliconFlow 的限流可能需要 30-60s 等待，2 次重试（默认 `max_retries=2`）可能不够，短时间重试会加剧限流，可能导致 IP 被封。

2. **LLM 返回"格式正确但语义错误"无处理**：例如 Step 4 返回一个只有标题没有正文的报告，或 Step 1 返回 `{"summary": ""}`。`_parse_json_response` 只检查 JSON 格式，不检查内容质量。空 `summary` 会被 `[:300] or "（LLM 未返回摘要）"` 兜底，但报告正文为空不会被拦截。

3. **quality_flags 记录降级但不阻止输出**：即使有 `high` 严重度的 `or_fallback_result`（result 字段被占位符替代），报告仍会输出。quality_flags 汇总在报告尾部，但用户可能不看尾部。`result` 是核心数据字段，如果被占位符替代，意味着该步骤的核心产出丢失——例如 Step 1 的 `result` 被占位符替代，后续 Step 2-4 都基于垃圾数据生成报告。在报告尾部标注"high 严重度"无法弥补报告本身已是垃圾的事实。

4. **搜索全部失败时的处理过于乐观**：`search_with_fallback` 全失败后降级为单 query 重试，如果降级也失败，`data_gaps` 会记录"所有搜索渠道不可用"，但流程继续。后续步骤会基于空搜索结果生成报告，质量极差。

5. **v5.2 FM 审查 LLM 本身失败的处理未覆盖**：FM 审查调用 `llm_call`，如果这个 LLM 调用超时或抛异常怎么办？代码只 `try/except json.JSONDecodeError`，不捕获 `asyncio.TimeoutError` 或网络异常。FM 审查超时会直接崩溃整个 Step 1。

### 4.4 恢复机制

**文档覆盖情况**：v5 设计了多版本 Checkpoint，但完全未实现。

**v5 设计（未实现）**：每次 `save()` 创建新版本文件，文件内 `saved_at` 字段用于清理；`load()` 从 latest 指针恢复；`load_version()` 按时间戳 + step_id 恢复历史版本。

**实际代码（v4）**：`save_checkpoint` 覆盖写入单文件；`try_resume` 从单文件恢复。

**我们的担忧**：

1. **v5 Checkpoint 完全未实现**：文档声称"v5 升级"但实际没有。如果现在崩溃，只能恢复到最后一个完整步骤，无法回滚历史版本。

2. **步骤内部分崩溃无法恢复**：Checkpoint 只在步骤完成后保存，步骤中间状态不保存。例如 Step 1 搜索成功但 LLM 调用崩溃，搜索结果丢失。

3. **v5 设计的 `_latest_path` 指针文件有并发风险**：`latest_path.write_text(path.name)` 是非原子操作。两个并发运行同一行业时，latest 指针会被覆盖，导致恢复到错误的版本。文档已标注"阶段三并发场景"使用 `request_id`，但应明确警告：v5 不支持同行业并发运行。

4. **v4 遗留 checkpoint 兼容性未测试**：v5 设计声称 `load()` 兼容 v4 格式，但因为 v5 CheckpointManager 未实现，这个兼容性无法验证。

### 4.5 并发

**文档覆盖情况**：明确推迟到阶段三，但未分析当前限制。

文档立场：v5 明确将并发相关组件推迟到 D 组："Checkpoint 按请求隔离"属于 D 组不做。

**我们的担忧**：

1. **同行业并发会数据损坏**：Checkpoint 文件名是 `{industry_name}.json`（v4）或 `{industry_name}_{timestamp}_{step_id}.json`（v5），`_latest_path` 是 `{industry_name}_latest.txt`。两个同行业并发运行会互相覆盖 latest 指针。建议在文档中明确警告：v5 不支持同行业并发；不同行业并发理论上可行但未测试。

2. **不同行业并发的 API 限流风险未分析**：多个行业同时运行会共享 LLM API 配额。SiliconFlow 有 RPM/TPM 限制，并发运行可能触发限流。

3. **全局状态（如 methodology 缓存）的线程安全未分析**：`methodology_loader.py` 有全局缓存 `_cached_full_text`，多线程访问可能有问题。虽然 asyncio 是单线程，但如果未来引入多进程或多线程，全局缓存会有竞态。

---

## 五、薄弱环节清单（按严重程度排序）

### P0 级（建议在编码前解决）

#### 5.1 v5.2 搜索补搜循环的 search.py 接口矛盾

见 3.1 节。两路评议独立识别。建议工作量 2-4h，涉及 `search.py` + `frost_agent.py` + 文档声明修正。

#### 5.2 v5 全部组件未实现，文档呈现"已实现"的语气

见 3.2 节。建议在文档开头添加"当前实现状态"章节。工作量 < 1h，涉及 `架构设计-Agent架构-v5.md`。

#### 5.3 `call_with_timeout` 不区分异常类型，429 限流处理不当

见 4.3 节。[circuit_breaker.py:40-42](file:///Users/paper/trae_project/行业定义agent/demo/harness/circuit_breaker.py#L40-L42) 对所有异常（含 429 限流）统一用 `2 ** attempt` 秒数退避重试。

**可能的修正方向**（供参考）：

```python
async def call_with_timeout(fn, max_retries=2, timeout_seconds=None):
    for attempt in range(max_retries + 1):
        try:
            if timeout_seconds is not None:
                return await asyncio.wait_for(fn(), timeout=timeout_seconds)
            return await fn()
        except asyncio.TimeoutError:
            if attempt == max_retries: raise
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            if attempt == max_retries: raise
            # 429 限流：读取 Retry-After，等待更长时间
            if hasattr(e, 'status_code') and e.status_code == 429:
                retry_after = getattr(e, 'headers', {}).get('Retry-After', '30')
                await asyncio.sleep(int(retry_after))
            else:
                await asyncio.sleep(2 ** attempt)
```

建议工作量 2-4h，涉及 `harness/circuit_breaker.py`。

#### 5.4 `load_version` 的 glob 模式 bug

见 3.3 节。建议工作量 < 1h，涉及 `harness/checkpoint.py`（v5 新增部分）。

### P1 级（严重，影响生产可靠性）

#### 5.5 Step 4 内容生成无质量校验，空报告会直接输出

[frost_agent.py:549-554](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L549-L554) 中，Step 4 只做 `_strip_preamble` 剥离开场白，不检查报告是否为空或过短。如果 LLM 返回空字符串或只有标题，后续 Step 5 会审查空报告，Step 6 会输出空报告。

**可能的修正**：在 [frost_agent.py:550](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L550) 后添加最小内容校验：

```python
report_text = _strip_preamble(llm_result["text"])
if len(report_text) < 500:
    raise ValueError(f"Step 4 报告过短（{len(report_text)} 字符），可能 LLM 生成失败")
```

建议工作量 < 1h，涉及 `frost_agent.py`。

#### 5.6 v5.2 FM 审查的"同源偏差"论证不成立

文档声称"FM 审查的是搜索结果（外部数据），不是 LLM 输出，不存在同源偏差"（[v5.md:1019](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1019), [1201](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1201)）。

**我们的不同意见**：
1. FM 审查本身是 LLM 调用，用 DeepSeek-V4-Pro
2. Step 1 的 LLM 总结也用 DeepSeek-V4-Pro
3. 虽然审查对象不同（搜索结果 vs LLM 输出），但审查者本身是 LLM，有自己的认知偏差
4. "同源偏差"在 Independent Evaluator 的语境下指的是"同一个 LLM 既当运动员又当裁判"，FM 审查用同一个模型确实存在这个问题——FM 可能对某些信息维度的"缺失"不敏感，因为同模型在 Step 1 总结时也不关注这些维度

**建议**：修正文档表述，将"不存在同源偏差"改为"审查对象是外部数据，降低了同源偏差风险，但审查者本身仍是 LLM，存在模型认知偏差"。阶段三 Model Router 引入后，FM 审查应使用不同模型。工作量 < 1h，涉及文档。

#### 5.7 `or_fallback_result` 标记为 high 但不阻止输出

见 4.3 节第 3 点。v5.1 将 `or_fallback_result`（result 字段被占位符替代）标记为 `high` 严重度，但流程仍继续。

**建议**：当 `or_fallback_result` 出现在 Step 1-4（生产步骤）时，应终止流程并提示重跑；当出现在 Step 5（自检步骤）时，可以继续但标记警告。工作量 2-4h，涉及 `frost_agent.py`。

#### 5.8 搜索全失败仍继续生成报告

见 4.3 节第 4 点。

**可能的修正**：在 [frost_agent.py:496](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L496) 后添加：

```python
if search_result.get("error_count", 0) == len(SEARCH_QUERIES) and not mock:
    raise RuntimeError("所有搜索渠道不可用，无法生成报告。请检查 TAVILY_API_KEY 和网络连接。")
```

工作量 < 1h，涉及 `frost_agent.py`。

#### 5.9 Orchestrator 骨架与"保持不变"承诺的张力

见 3.4 节。建议作者澄清骨架性质（伪代码 vs spec），并相应修正文档描述或工作量估计。

#### 5.10 "最多 2 轮补搜"描述与逻辑冲突

见 3.5 节。建议修正描述或修正逻辑。

#### 5.11 `STEP4_MAX_TOKENS` 文档与代码不一致

见 3.6 节。待作者确认阶段一 P0-1 二分查找结论后统一。

### P2 级（设计改进建议）

#### 5.12 v5.2 补搜循环的串行搜索应改为并行

[v5.md:1136-1139](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1136-L1139) 中补搜 query 串行执行。2 个补搜 query 串行需要 4-8s，并行只需 2-4s。建议改为 `await asyncio.gather(*[search_single_query(q, key) for q in queries_to_search])`。工作量 < 1h。

#### 5.13 OutputSafety 的版本号追加有理论上的无限循环风险

[v5.md:775-778](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L775-L778) 中 `while path.exists()` 无上限。虽然实际不太可能，但如果在同一秒内运行同一行业超过几百次（如脚本循环测试），`version` 会无限增长。建议添加 `max_versions = 100` 上限。工作量 < 1h。

#### 5.14 TokenAudit 的汇率硬编码

[v5.md:456](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L456) 硬编码 `7.2` 汇率。汇率会变动，建议改为从环境变量读取，或标注"汇率固定为 7.2，仅用于粗略估算"。工作量 < 1h。

#### 5.15 Checkpoint 保存 trace_id 以支持可观测性关联

Checkpoint 不记录 trace_id，无法关联"哪次运行产生了哪个 checkpoint"。建议在 `CheckpointManager.save` 的 wrapper 中增加 `trace_id` 字段。工作量 < 1h。

#### 5.16 FM 审查纳入步骤级超时管理

FM 审查调用 LLM 但未纳入 `call_with_timeout` 的超时管理，若 FM 审查卡住会耗尽 Step 1 的 180s 预算。建议用 `call_with_timeout` 包装 FM 审查调用，单次超时 30s，最多重试 1 次。工作量 < 1h。

---

## 六、过度乐观假设清单

以下是我们认为文档中偏乐观的假设，列出来供作者自查：

| # | 过度乐观的假设 | 我们的担忧 | 文档位置 |
|---|--------------|-----------|---------|
| 1 | "多数情况不触发补搜（静态模板已覆盖），平均额外成本 < $0.001/次" | 无任何实测数据支持。3 个静态模板是通用的"行业定义/政策监管/边界区分"，对于细分行业（如"人形机器人腱绳材料"）很可能覆盖不足，FM 审查大概率会触发补搜 | [v5.md:1196](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1196) |
| ~~2~~ | ~~"总成本仍远低于 $0.10 闸门"~~ | ~~已撤回~~。经查阅 P0-3 实测报告，三行业平均成本 $0.019/次，远低于 $0.10 闸门（仅占 19%），文档判断有实测支撑，**非过度乐观**。初版评议用 max_tokens 上限估算得出 ¥0.396 属方法错误，已勘误。仍存的小担忧：v5.2 新增 FM 审查的增量成本（含 input token）未纳入实测，建议 v5.2 实现后补测 | [v5.md:1197](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1197) |
| 3 | "FM 审查的是搜索结果（外部数据），不是 LLM 输出，不存在同源偏差" | FM 本身是 LLM，有模型认知偏差。同模型在 Step 1 总结时不关注的维度，FM 审查时也可能不关注 | [v5.md:1019, 1201](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1019) |
| 4 | "签名兼容 v4 的 save_checkpoint() / try_resume()" | v5 的 `CheckpointManager.save(state, step_id, request_id=None)` 和 `load(industry_name)` 签名确实兼容，但 `load_version` 是新增方法，且 v5 要求 `step_id` 必填，与 v4 的 `try_resume(industry_name)` 语义不同 | [v5.md:713](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L713) |
| 5 | "v5.2 不改 search.py 接口" | 直接矛盾，见 3.1 节 | [v5.md:983](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L983) |
| 6 | "FM 审查 ~15s/轮" | 无实测依据。按 v4 实测 Step 5 自检（completion 721-1249 tokens 耗时 20-32s）推测，FM 审查 max_tokens=2000 可能在 15-30s | [v5.md:1189](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1189) |
| 7 | "阶段二退出条件无耗时考核"——暗示延迟不重要 | 即使没有考核，如果一次运行超过 10 分钟，用户体验极差。不过 P0-3 实测平均 4.5 分钟/次，当前延迟可接受；担忧主要针对 v5.2 新增 FM 审查可能压缩 Step 1 timeout 余量 | [v5.md:1191](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1191) |
| 8 | v5 验收标准中"跑一次真实 API 运行"能通过 | 当前代码是 v4，v5 组件未实现，无法跑 v5 的验收 | [v5.md:1457](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L1457) |

---

## 七、批判性三问

### 7.1 这个架构能否通过最基础测试（能不能跑）？

**我们的判断**：当前代码（v4）能跑，但 v5 不能跑——因为 v5 不存在。

- v4 代码可以 `python frost_agent.py "低空经济物流"` 跑通（有 Mock 模式和真实 API 模式）
- v5 文档描述的 7 项组件全部未实现，v5 的验收标准 0 项可通过
- v5.2 的搜索补搜循环因接口矛盾（3.1 节）即使实现了也无法运行

需要强调：这不是说 v5 设计有问题，而是说 v5 还停留在设计阶段。设计本身能否跑通，要等实现后才能验证。

### 7.2 如果现在部署到生产环境，第一个故障会是什么？

**取决于部署的是 v4 还是 v5。**

如果部署 **v4（当前代码）**：
1. **第一个故障**：Tavily API 限流或超时。`search_with_fallback` 的降级策略只重试一次，如果降级也失败，会基于空搜索结果生成低质量报告
2. **第二个故障**：SiliconFlow API 限流（429）。`call_with_timeout` 不区分 429，盲目重试会加剧限流
3. **第三个故障**：Step 4 生成超时。实测 Step 4 耗时 73-105s（completion 3.4K-4.7K tokens），180s timeout 下有约 75s 余量，正常情况不会超时；但若 LLM 响应慢或网络抖动，仍可能触发。这并非高频故障，列第三仅供参考。

如果部署 **v5（如果实现）**：
1. **第一个故障**：v5.2 搜索补搜循环因 `search_with_fallback` 接口不匹配直接崩溃（3.1 节）
2. **第二个故障**：FM 审查 LLM 调用超时未被捕获（4.3 节第 5 点）

### 7.3 与其他方案相比，放弃这个架构会失去什么、选择它会失去什么？

**选择当前架构（v4/v5）的 trade-off**：

| 选择 | 得到 | 失去 |
|------|------|------|
| **选择当前架构** | 1. 六步管线结构清晰，方法论约束强<br>2. Independent Evaluator 设计降低自评偏差<br>3. Context Builder 四层组装可追溯<br>4. quality_flags 设计（v5）能追踪降级 | 1. 无并发能力，单次运行 3-10 分钟<br>2. 无流式输出，用户等待体验差<br>3. 无 Model Router，全用贵模型<br>4. 无 Prompt Cache，重复 prompt 浪费 token<br>5. 无 Evaluator-Optimizer 闭环，自检失败只警告不修正<br>6. 单点 LLM 调用，无 fallback 模型 |
| **放弃当前架构，用 LangChain/LangGraph** | 1. 成熟的并发/流式/缓存支持<br>2. 丰富的社区生态和文档<br>3. 内置多种错误处理模式 | 1. 方法论约束需要重新实现<br>2. 框架抽象可能隐藏关键细节<br>3. Independent Evaluator 的"独立 LLM 调用"设计在框架中不直观 |

**我们的倾向性判断**（非定论）：当前架构的"六步管线 + 方法论约束 + Independent Evaluator"设计思路是合理的，不应该放弃。但工程基础设施（并发、流式、缓存、错误处理）严重不足，需要补齐。文档将大部分基础设施推迟到 D 组是合理的（阶段二聚焦 A 组），但建议在设计中补充"不做的代价"分析——例如，不做 Prompt Cache 的代价是每次运行多花 30-50% 的 input token 费用，这个数字应该出现在成本分析中。

---

## 八、与业界实践的对标分析

文档在"参考来源"章节列出了借鉴来源，但未分析"借鉴了什么"和"没借鉴什么"。以下从设计思想层面分析差距，供作者参考：

| 业界实践 | 当前架构状态 | 可借鉴的设计思想 |
|---------|------------|----------------|
| **流式输出（Streaming）** | 未实现，全量等待 | Step 4 内容生成可以用流式输出，用户边等边看进度。设计思想：长耗时操作应提供增量反馈 |
| **Prompt Cache** | 明确推迟到 D 组 | Step 1-5 的 system prompt（静态身份 + 方法论切片）高度重复，缓存可节省 30-50% input token。设计思想：识别不变部分与可变部分，缓存不变部分 |
| **Structured Output / Function Calling** | 用手动 JSON 解析 + 三层容错 | DeepSeek-V4-Pro 支持 JSON mode 或 function calling，可以强制返回合法 JSON，避免三层容错的复杂性。设计思想：用 API 原生能力替代手动解析 |
| **Model Router** | 明确推迟到 D 组 | FM 审查、Step 5 自检等"判断"类任务可以用更便宜的模型，Step 4 内容生成才用贵模型。设计思想：按任务复杂度分配模型 |
| **分布式追踪（OpenTelemetry）** | 只有 trace_id + JSONL | 业界用 OpenTelemetry 标准，支持 span/trace/metrics 统一采集。设计思想：用标准协议替代自定义日志格式 |
| **Evaluator-Optimizer 闭环** | 明确推迟到阶段三 | 当前自检失败只注入警告，用户拿到带警告的报告。业界做法是自动重跑失败步骤。设计思想：自检结果应驱动修正，而非仅记录 |
| **Cost Guard（成本守卫）** | 明确推迟到 D 组 | 有 $0.10 闸门但无运行时 enforcement。设计思想：成本控制需要运行时拦截，不是事后审计 |
| **Circuit Breaker（熔断器）** | `call_with_timeout` 仅超时重试 | 无 CLOSED/OPEN/HALF_OPEN 状态机。设计思想：连续失败应触发熔断，停止重试，避免雪崩 |

**重要说明**：文档将上述大部分组件推迟到 D 组是合理的（阶段二聚焦 A 组基础设施）。我们的担忧不在于"为什么不现在做"，而在于"即使推迟，也应该在设计中分析不做的定量代价"。

---

## 九、改进建议汇总

### P0 级（建议在编码前解决）

| # | 建议 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| P0-1 | 修正 v5.2 搜索补搜循环的 search.py 接口矛盾 | `search.py` + `架构设计-Agent架构-v5.md` | 2-4h |
| P0-2 | 在 v5 文档中标注所有组件的"当前实现状态" | `架构设计-Agent架构-v5.md` | < 1h |
| P0-3 | 修正 `call_with_timeout` 的 429 限流处理 | `harness/circuit_breaker.py` | 2-4h |
| P0-4 | 修正 `load_version` 的 glob 模式 | `harness/checkpoint.py`（v5 新增部分） | < 1h |

### P1 级（严重，影响可靠性）

| # | 建议 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| P1-1 | 添加 Step 4 报告内容最小校验 | `frost_agent.py` | < 1h |
| P1-2 | 搜索全失败时终止流程 | `frost_agent.py` | < 1h |
| P1-3 | `or_fallback_result` 在生产步骤终止流程 | `frost_agent.py` | 2-4h |
| P1-4 | FM 审查 LLM 调用添加异常捕获 | `frost_agent.py` | < 1h |
| P1-5 | 修正"不存在同源偏差"的表述 | `架构设计-Agent架构-v5.md` | < 1h |
| P1-6 | 补充端到端成本和延迟估算（引用 P0-3 实测数据 + v5.2 增量补测） | `架构设计-Agent架构-v5.md` | 2-4h |
| P1-7 | 澄清 Orchestrator 骨架性质（伪代码 vs spec） | `架构设计-Agent架构-v5.md` | < 1h |
| P1-8 | 修正"最多 2 轮补搜"描述或逻辑 | `架构设计-Agent架构-v5.md` | < 1h |
| P1-9 | 将 `frost_agent.py` 的 `STEP4_MAX_TOKENS` 默认值从 16000 改为 10000（实测推荐值），更新过时注释 | `frost_agent.py` | < 1h |

### P2 级（改进建议）

| # | 建议 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| P2-1 | 补搜循环改为并行搜索 | `frost_agent.py` | < 1h |
| P2-2 | OutputSafety 版本号追加加上限 | `harness/output_safety.py`（未实现） | < 1h |
| P2-3 | TokenAudit 汇率改为环境变量 | `harness/token_audit.py`（未实现） | < 1h |
| P2-4 | Checkpoint 保存 trace_id | `harness/checkpoint.py` | < 1h |
| P2-5 | FM 审查纳入超时管理 | `frost_agent.py` | < 1h |
| P2-6 | 补充"不做的代价"分析 | `架构设计-Agent架构-v5.md` | 2-4h |

---

## 十、待确认事项

以下问题我们无法在本次评议中定论，需作者澄清或查阅更多资料：

1. ~~**`STEP4_MAX_TOKENS` 最终结论是 10000 还是 16000？**~~ **已解决**：查阅 P0-3 实测报告，推荐值 10000（有二分查找数据支撑），文档正确，代码待更新。见 3.6 节。
2. **FM 审查"~15s/轮"是实测还是估算？** 来源是什么？
3. **v5 骨架是伪代码还是可直接实现的 spec？** 若是伪代码，建议在文档中标注。
4. **$0.10 闸门的来源和依据是什么？** 项目预算？竞品对标？还是随意定的？
5. **v4 遗留 checkpoint 与 v5 新包装格式的加载兼容性如何处理？** v5 设计声称兼容但未实现，无法验证。
6. **`方法论/` 拆分目录的具体模块划分是什么？** 文档说"2-3 模块 + _meta.yaml"但未给出具体拆分方案。

---

## 十一、对前序评议的补充

已有的 Kimi 评议（[v5-评估报告](file:///Users/paper/trae_project/行业定义agent/kimi产出的文档/架构设计-Agent架构-v5-评估报告（设计评审）.md) 和 [对-v5-评估回应的评议回复](file:///Users/paper/trae_project/行业定义agent/kimi产出的文档/对-v5-评估回应的评议回复.md)）质量很高，识别了 Checkpoint 清理逻辑、load_version 模糊匹配、or_fallback 严重度泛滥等真实问题。本次评议在这些问题上与 Kimi 评议一致，并补充了以下视角：

1. **工程视角五问的强制覆盖**：Kimi 评议聚焦设计层面，本次评议补充了成本/延迟/错误处理/恢复/并发的工程视角分析。
2. **文档与代码实现状态的系统性偏差**：Kimi 评议在评审"设计文档"本身，本次评议指出"这个设计完全没有落地"——这是前序评议链中的盲点。
3. **v5.2 搜索补搜循环的接口矛盾**：这是 v5.2 新增内容，前序评议未覆盖。
4. **429 限流处理、空报告输出、搜索全失败继续生成等生产可靠性问题**：这些是工程实战视角的补充。

我们认同 Kimi 评议的核心判断——"v5 架构设计文档作为阶段二 A 组的开发 Spec，整体设计方向正确"。但作为同行评议，我们需要补充一点：**一份完全未实现的设计文档，无论设计多正确，其工程价值为零。当前项目的当务之急不是继续打磨设计文档，而是开始实现。** 这个判断可能偏激，欢迎作者反驳。

---

## 十二、评议者声明

本次评议由两条独立路径（架构一致性审查 + 工程视角批判）并行展开后整合。两路评议在以下问题上独立得出一致结论，我们认为这些结论较为可靠：

- v5.2 搜索补搜循环的 search.py 接口矛盾（3.1 节）
- v5 全部组件未实现的现状（3.2 节）
- 429 限流处理不当（5.3 节）
- Step 4 无内容质量校验（5.5 节）

以下问题属于我们的工程担忧，可能存在过度批判，欢迎作者澄清：

- "同源偏差"论证是否成立（5.6 节）——这取决于"同源偏差"在项目语境下的定义
- Orchestrator 骨架是否构成"重构"（3.4 节）——这取决于骨架是伪代码还是 spec

**已确认的评议错误（勘误）**：

- **成本估算方法错误（4.1 节）**：初版用 max_tokens 上限 × 单价估算得出 ¥0.396，并据此担忧"Step 4 单步可能超过 $0.10 闸门"。经作者指出并查阅 P0-3 实测报告，实际平均成本 $0.019/次（三行业真实 API 运行），初版高估约 20 倍。max_tokens 是输出上限而非实际消耗，用上限估成本如同用限速估通勤时间——这是方法性错误，非数据偏差。文档"总成本远低于 $0.10 闸门"的判断有实测支撑，并非过度乐观。相关错误论断已在 4.1、4.2、第六节第 2 条、7.2 节同步修正。
- **STEP4_MAX_TOKENS 方向判断有误（3.6 节）**：初版标注"待确认"，隐含怀疑文档 10000 是否正确。实测报告证实文档是对的，代码才是待更新方。

评议中引用的行号和代码均来自实际读取的文件，但我们承认可能存在遗漏的代码路径或文档章节。本次勘误也暴露了评议方法的一个缺陷：**在未查阅项目开发日志的情况下，不应基于代码中的 max_tokens 上限做成本推测**。如作者认为仍有评议条目有误，欢迎指正，我们会在后续讨论中修正。

---

*评议完成。本文档遵循项目规则：评估框架 → 逐项分析 → 总结，三段式结构完整；所有数字标注可信度或"待验证"；术语全文统一。*
