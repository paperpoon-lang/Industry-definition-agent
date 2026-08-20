# 阶段二-A组修复实现日志 v1.1 同行评议报告

> **评估者身份**：同行评议专家（协作式评估者，非权威甲方）
> **评估日期**：2026-06-27
> **评估对象**：《阶段二-A组修复计划 v1.2 实现日志》v1.1
> **评估类型**：代码/实现审计（验证修复实现质量、文档可信度、验收标准达成度）
> **验证范围**：实现日志文档本身 + 部分代码验证（`demo2/` 关键文件）

---

## 一、总体判断

**修复实现日志 v1.1 是一份高质量的工程文档，修复实现正确，关键路径测试覆盖，但存在 1 个 P0 级严重 bug（P0-1）已在 v1.1 中修复，1 个关键归因验证待确认（脑机接口 Step 3 选 5 章），以及 2 个技术债务需要明确记录。**

文档的**最大价值**在于：
1. 坦诚记录从 v1.0 "9/9 通过"到 v1.1 "8/9 通过 + 1 项 FAIL"的自我修正
2. architecture-critic 补审发现 P0-1 严重 bug（`search_phase_timeout` 不触发 `QualityGateError`）并修复
3. 脑机接口 6611 归因从"修复正面效应"修正为"Step 3 结构决策不稳定"，归因更准确

文档的**主要风险**在于：
1. `search_phase_timeout` 终止路径在真实 API 环境中**从未触发**（5/5 行业未超时），生产环境首次触发可能暴露未预见问题
2. 测试覆盖率估计 < 20%，大量 v5 组件代码无测试覆盖
3. `QualityFlag.terminates_flow` 元数据字段方案被推迟到 B 组，但当前"直接 raise"的临时方案已引入设计债务

---

## 二、分维度评估

### 2.1 修复实现质量

| 修复 | 实现状态 | 测试覆盖 | 真实 API 验证 | 评价 |
|------|---------|---------|--------------|------|
| 修复 1：FM 审查 60s + 失败区分 + 日志 | ✅ 完整实现 | 4 个测试（timeout/parse/exception/flag） | 5/5 行业无超时，FM 审查成功 | 实现正确。`_record_fm_failure_flag` 的 `[type=xxx]` 结构化前缀便于离线统计 |
| 修复 2：搜索阶段外层 timeout + 级联终止 | ✅ 完整实现（含 P0-1 修复） | 1 个测试（`test_search_phase_timeout_cascade`） | **5/5 行业未触发超时路径** | 实现正确，但**生产环境未验证**。P0-1 修复（`has_search_all_failed` 直接 raise）是关键修正 |
| 修复 3：Step 5 LLM 记日志 | ✅ 完整实现 | 无持久化测试 | 5/5 行业 JSONL 确认 7 个 llm_raw_response | 实现简单正确，但缺乏持久化测试 |
| 修复 4：MethodologyLoader fallback warning | ✅ 完整实现 | 无持久化测试 | 代码审查确认 | 实现正确，但 `METHODOLOGY_STRICT` 硬失败路径未测试 |

**观察**：修复 2 的 `search_phase_timeout` 路径在 5 行业真实 API 验证中**从未触发**，这意味着该路径的可靠性只能靠单元测试保证。单元测试中 `test_search_phase_timeout_cascade` 使用 `unittest.mock.patch` mock 了 `step1_search_with_supplement` 使其抛出 `TimeoutError`，验证了终止路径正确。但生产环境首次触发时，实际异常链（`asyncio.wait_for` 抛 `TimeoutError` → `_run_step1` 捕获 → 记录 flag → raise `QualityGateError`）是否完全一致，仍有不确定性。

### 2.2 P0-1 严重 bug 的发现与修复

**这是文档中最关键的事件**，需要单独评估：

| 维度 | 评估 |
|------|------|
| 严重度 | **P0**：`search_phase_timeout` 触发后，`_check_quality_gate` 只检查 `or_fallback_result`，对 `search_phase_timeout` 和 `search_partial_failure` 都静默返回。`run()` 主流程继续 Step 2-4，基于 `result={"error": "all_search_failed"}` 的垃圾输入调 LLM，产生无意义输出 |
| 发现时机 | 修复实现完成后（v1.0），architecture-critic **补审**发现（非 Edit 前审查） |
| 根因分析 | "category 注册表"与"终止条件"两处单一真相源（SSOT）未同步。`models.py` 新增 `search_phase_timeout` category 时，`frost_agent.py` `_check_quality_gate` 的硬编码 `category == "or_fallback_result"` 未同步扩展 |
| 修复方案 | 方案 A（直接 raise，不依赖 `_check_quality_gate`）替代方案 B（扩展 `_check_quality_gate` 检查 `search_phase_timeout`），理由是避免"每加一个 high category 就要改 `_check_quality_gate`"的反模式 |
| 长期方案 | `QualityFlag.terminates_flow: bool` 元数据字段，纳入 B 组评估 |

**我的判断**：
- P0-1 的发现和修复是**及时的**——如果在阶段二 A 组收尾后才发现，进入 B 组或生产环境时会产生严重后果
- architecture-critic 的补审机制有效，但问题是：**为什么 Edit 前审查没有发现？** 答案是：Edit 前审查只审了 `models.py` 的 category 设计，没有审 `frost_agent.py` 的 `_check_quality_gate` 调用链。这是审查覆盖范围的局限
- 方案 A（直接 raise）是务实的，但引入了**技术债务**：未来每新增一个需要终止流程的 high category，都需要在 `has_search_all_failed` 分支中手动 raise。这比方案 B（扩展 `_check_quality_gate`）更脆弱，因为分散的 raise 点比集中的 `_check_quality_gate` 更难维护
- 文档明确记录了长期方案（`QualityFlag.terminates_flow`），这是好的，但需要确认 B 组评估时会优先处理这个技术债务

### 2.3 文档可信度与诚实性

| 维度 | 评估 | 说明 |
|------|------|------|
| v1.0 → v1.1 修正 | ✅ 坦诚 | 从"9/9 通过"改为"8/9 通过 + 1 项 FAIL"，诚实记录修正 |
| 脑机接口归因修正 | ✅ 准确 | 从"修复正面效应"修正为"Step 3 结构决策不稳定"，对比 v1.2 基线数据（4 行业有升有降）支持新归因 |
| 数据来源标注 | ✅ 详细 | 每个数据表格都标注了来源和可信度（★★★★★ 到 ★★☆☆☆） |
| 未采纳建议记录 | ✅ 完整 | 3 个未采纳建议（`_error_type` 改名、STEP_BUDGETS 360s、Step 3 因果链）都有反驳理由和前提验证 |
| 测试覆盖缺口 | ✅ 诚实 | 明确列出 5 个测试覆盖缺口，不掩盖 |
| 限制条件说明 | ✅ 清晰 | 标注"生产环境未触发超时路径"、"脑机接口 Step 3 选 5 章 待人工确认"等 |

**观察**：文档可信度整体很高，但有一个**需要追问的点**：v1.0 为什么错误地判定"9/9 通过"？脑机接口 6611 超出 4320-5472 区间在 v1.0 时就应该被发现。可能的原因：
1. v1.0 时验收标准执行不严（可能只检查了"4/5 在区间内"就认为"通过"）
2. v1.0 时对"脑机接口 6611"的归因错误（认为是"修复正面效应"），从而降低了其严重性认知
3. v1.0 的 fact-checker 没有核查报告长度数据

无论原因是什么，v1.1 的修正说明**审查机制（architecture-critic + fact-checker + 用户确认）有效**，但这也暗示**最初的自我评估流程有漏洞**——在没有外部审查时容易过度乐观。

### 2.4 验收标准达成度

| 验收项 | 预期 | 实测 | 文档判定 | 我的评议 |
|--------|------|------|---------|---------|
| 4 行业 FM 审查超时数 = 0 | 0 | 5/5 无超时 | ✅ | 实际上 5/5 无超时（超出预期），但"4 行业"预期变为"5 行业"实测，是否意味着测试范围扩大？ |
| FM 审查最大耗时 ≤ 60s | ≤ 60s | 无超时触发 | ✅ | 未触发超时，无法验证 60s 阈值是否足够。只能确认"5 行业在 60s 内完成" |
| timeout/parse/exception 三场景 flag | `fm_review_skipped` | 单元测试覆盖 | ✅ | 测试覆盖，但生产环境未触发 |
| 最终审查失败产生 flag | 不再静默 | 5 行业未触发失败路径 | ⚠️ | 代码已改造（L578），但**真实 API 未触发失败路径**，无法验证"不再静默"是否真正生效 |
| JSONL 含 fm_review + round_label | 5/5 | 5/5 | ✅ | 一手实测确认 |
| JSONL 含 Step 5 llm_raw_response | 7 个/行业 | 7 个/行业 | ✅ | 一手实测确认 |
| 补搜循环执行 | query_count 3→5 | 5/5 均执行 | ✅ | 一手实测确认，效果显著（之前 4/5 超时失效） |
| 报告字符数不劣化 | 4320-5472 | 4/5 在区间，脑机接口 6611 | ❌ | **文档正确判定 FAIL**。我的确认：这是真实的问题，不是数据错误 |
| 无 `or_fallback_result(high)` | 0 | 5/5 均无 | ✅ | 一手实测确认 |

**关键观察**：
- 3 个验收项（timeout/parse/exception 三场景、最终审查失败 flag、无 timeout 触发）**只能靠单元测试验证**，真实 API 未触发对应路径。这不是文档的问题，是测试条件的限制（API 响应良好），但意味着这些路径的生产环境可靠性未经充分验证
- "4 行业"预期变为"5 行业"实测：文档说"排除钙钛矿 Step 3 超时"，但实测钙钛矿 Step 3 也未超时。这是否意味着测试范围比预期大？还是文档 v1.0 的"4 行业"是基于"钙钛矿可能 Step 3 超时"的保守估计？

### 2.5 测试质量

| 测试 | 覆盖场景 | 实现方式 | 耗时 | 评价 |
|------|---------|---------|------|------|
| `test_fm_review_timeout` | timeout 场景 | mock `call_with_timeout` 直接抛异常 | <1s | 高效，不依赖 sleep |
| `test_fm_review_parse_error` | parse_error 场景 | mock `call_with_timeout` 返回非 JSON | <1s | 高效 |
| `test_fm_review_exception` | exception 场景 | mock `call_with_timeout` 抛 Exception | <1s | 高效 |
| `test_record_fm_failure_flag` | flag 生成 | 直接调用 `_record_fm_failure_flag` | <1s | 只测 timeout 分支，未覆盖 parse/exception/empty |
| `test_search_phase_timeout_cascade` | 终止路径 + QualityGateError | mock `step1_search_with_supplement` 抛 TimeoutError | <1s | **最关键的测试**，验证 P0-1 修复 |

**测试覆盖缺口（文档已列出）**：

| 缺口 | 优先级 | 我的评议 |
|------|--------|---------|
| `test_record_fm_failure_flag` 未覆盖 parse/exception/empty | P2 | 同意。`_record_fm_failure_flag` 有多个分支，只测 timeout 不够 |
| MethodologyLoader `METHODOLOGY_STRICT` 硬失败 | P2 | 同意。硬失败路径是新增的关键分支 |
| `has_search_all_failed` 边界（`search_partial_failure` + `search_phase_timeout` 同时存在）| P3 | 合理。这个边界在真实 API 中可能触发（搜索部分失败 + 整体超时同时发生） |
| 修复 3 mock 模式下不记日志的回归测试 | P3 | 合理。mock 模式 Step 5 不记日志，需要确认不会破坏其他场景 |
| 引入 `pytest-cov` + 覆盖率阈值 | P3 | 同意。当前覆盖率 < 20%，需要量化 |

**我的额外观察**：
- 5 个测试全部是**mock 测试**，没有集成测试。这在单元测试层面是正确的，但意味着 v5 组件（SessionEventLog、CheckpointManager、OutputSafety、TokenAudit）之间没有集成测试验证协同工作
- 例如：`search_phase_timeout` 触发后，是否正确记录到 JSONL 日志？是否正确写入 checkpoint？`token_audit` 是否正确统计了超时前的 token 消耗？这些集成场景没有测试覆盖
- 文档在"工程视角"中提到"并发"未测试，但串行执行未触发并发问题，这是合理的局限

### 2.6 成本与延迟分析

| 维度 | 修复计划估算 | 实测 | 评价 |
|------|------------|------|------|
| 成本范围 | ¥0.17-0.22（修复计划 4.1） | ¥0.1538-0.1829（5 行业） | **实际低于估算下限**。修复 1 让补搜循环真正执行，但成本未显著上升。原因是补搜只增加 Tavily 调用（不计入 LLM token），Step 1 prompt 略增但影响小 |
| Step 1 最坏耗时 | ~258s（修复计划） | 173s（脑机接口，最长） | 实测低于估算，300s 兜底余量充足（127s） |
| 总耗时（5 行业串行） | 22:21-22:55 = 34 分钟 | 实际 | 平均每行业 ~6.8 分钟，包含搜索、LLM 调用、评估 |

**观察**：成本分析是 v1.1 新增的内容，补充了 v1.0 的缺失。数据支持"修复不会显著增加成本"的结论。延迟数据也支持"300s 兜底足够"的结论。

### 2.7 技术债务记录

文档中明确或隐含的技术债务：

| 债务 | 位置 | 记录状态 | 我的评议 |
|------|------|---------|---------|
| `_check_quality_gate` 硬编码 `category == "or_fallback_result"` | `frost_agent.py` | 已记录（P0-1 分析） | 当前方案 A（直接 raise）绕过了 `_check_quality_gate`，但未来新增 high category 时仍需手动确认是否触发 `QualityGateError`。`QualityFlag.terminates_flow: bool` 方案是根治，但推迟到 B 组 |
| `print` 混入 stdout（vs logging 框架） | `frost_agent.py` / `methodology_loader.py` | 已记录（修复 4 trade-off 表） | 文档选择了 print（短期一致优先），并记录"未来引入 logging 框架时统一迁移"为 P3 follow-up。合理 |
| 测试覆盖率 < 20% | `tests/` | 已记录（测试覆盖缺口） | 需要关注。v5 新增的大量代码（~340 行）只有 5 个测试覆盖，且全部集中在 FM 审查场景 |
| 并发场景未验证 | `frost_agent.py` | 已记录（工程视角） | 合理推迟到 B 组。Tavily 限流 1000 req/min 足够 5 行业串行，但并发场景需要额外测试 |
| Step 3 章节数不稳定（LLM 随机选择） | `frost_agent.py` | 已记录（脑机接口归因） | 建议 C（增加章节数约束）是根治方案，但推迟到 B/D 组 |

**观察**：技术债务记录完整，但 `QualityFlag.terminates_flow` 方案被明确推迟到 B 组。这意味着在 B 组之前，如果新增其他需要终止流程的 high category，仍然需要手动维护 raise 点。这是一个**持续的设计债务**。

---

## 三、关键问题列表（Q 级——需要团队反馈）

### Q1：P0-1 bug 的 Edit 前审查为何未发现？如何避免未来类似遗漏？

**我的观察**：P0-1（`search_phase_timeout` 不触发 `QualityGateError`）是在 Edit 后补审中发现的，而非 Edit 前审查。Edit 前审查只审了 `models.py` 的 category 设计，没有审 `frost_agent.py` 的 `_check_quality_gate` 调用链。这意味着**审查覆盖范围与代码修改范围不匹配**——新增 category 时，审查者只关注了 category 定义，没有追踪到所有消费该 category 的代码路径。

**建议**：
- 方案 A：在"新增 category"的流程中增加"检查清单"——强制检查所有消费 `category` 的代码路径（`_check_quality_gate`、`has_search_all_failed`、Step 6 汇总、离线统计等）
- 方案 B：将 `QualityFlag.terminates_flow` 纳入 B 组 **P0 优先级**（而非 P2），因为这是一个持续的设计债务，每新增 category 都可能引入类似 P0-1 的 bug

**需要团队反馈**：是否接受方案 B？如果 `QualityFlag.terminates_flow` 不纳入 B 组 P0，是否有其他机制（如新增 category 检查清单）防止类似遗漏？

### Q2：脑机接口"Step 3 选 5 章"的归因是否已人工确认？

**我的观察**：文档中脑机接口"Step 3 选 5 章"（其他行业 3-4 章）的归因可信度只有 ★★☆☆☆（"JSONL text_preview 截断，无法精确验证"）。这个归因是脑机接口 6611 超出区间的**关键假设**——如果假设不成立，6611 超出的根因就未知，可能暗示其他系统性问题（如 LLM 输出长度不稳定、prompt 设计问题等）。

**建议**：
- 方案 A：人工抽查脑机接口的 `checkpoints/*.json` 中 Step 3 的 `result` 字段，确认章节数
- 方案 B：如果无法确认，将"脑机接口 6611 超出区间"的归因从"Step 3 选 5 章"降级为"待人工确认"，验收 FAIL 的结论不变，但根因分析标记为"待验证"

**需要团队反馈**：是否已人工确认脑机接口 Step 3 的章节数？

### Q3：v5 组件的集成测试缺失是否应纳入 B 组评估？

**我的观察**：5 个单元测试全部是 mock 测试，且全部集中在 FM 审查场景。v5 新增的其他组件（SessionEventLog 的 JSONL 写入、CheckpointManager 的多版本保存、OutputSafety 的文件名生成、TokenAudit 的报表统计）之间没有集成测试验证协同工作。例如：
- `search_phase_timeout` 触发后，SessionEventLog 是否正确记录？CheckpointManager 是否保存了中断状态？TokenAudit 是否正确统计了超时前的 token 消耗？
- 这些集成场景在单元测试中无法验证，因为每个组件被独立 mock

**建议**：
- 方案 A：在 B 组评估中增加"v5 组件集成测试"项，设计 2-3 个集成测试场景（如"搜索超时 → 检查 JSONL 日志 + checkpoint + token_audit 的协同状态"）
- 方案 B：保持当前测试策略（单元测试 + 真实 API 验证），但明确记录"集成测试缺失"为已知限制

**需要团队反馈**：B 组是否计划增加集成测试？还是保持当前策略？

### Q4：`test_search_phase_timeout_cascade` 是否覆盖了 P0-1 修复的所有分支？

**我的观察**：`test_search_phase_timeout_cascade` 测试了：
- `step1_search_with_supplement` 抛 `TimeoutError` → 产生 `search_phase_timeout(high)` flag → raise `QualityGateError`
- 验证 `mock_call_llm.call_count == 0`（LLM 未调用）
- 验证无 `or_fallback_result` flag

但 P0-1 的修复还涉及 `has_search_all_failed` 的扩展——它现在检查 `search_phase_timeout` 和 `search_partial_failure`。`test_search_phase_timeout_cascade` 是否也测试了 `search_partial_failure` + `search_phase_timeout` 同时存在的情况？

**建议**：确认 `test_search_phase_timeout_cascade` 的断言是否包含以下分支：
- 仅 `search_phase_timeout`（无 `search_partial_failure`）→ 触发 `QualityGateError`
- `search_partial_failure(high, all_queries)` + `search_phase_timeout` → 触发 `QualityGateError`
- 如果测试未覆盖第二个分支，补充测试（文档测试覆盖缺口中已有此项，P3）

**需要团队反馈**：`test_search_phase_timeout_cascade` 是否覆盖了 `search_partial_failure` + `search_phase_timeout` 的复合场景？

---

## 四、风险矩阵

| 风险等级 | 风险 | 说明 | 建议应对 |
|----------|------|------|----------|
| **P1** | **`search_phase_timeout` 终止路径生产环境未验证** | 5/5 行业真实 API 未触发超时路径，该路径的可靠性仅靠单元测试保证。生产环境首次触发（如 Tavily API 极端慢、网络抖动）可能暴露未预见问题 | 有条件接受：单元测试覆盖了核心逻辑，但建议在 B 组中设计一个"模拟超时"的集成测试（通过 monkeypatch 或环境变量注入慢响应） |
| **P1** | **脑机接口 6611 归因的置信度低** | 关键假设"Step 3 选 5 章"的可信度只有 ★★☆☆☆，如果假设不成立，6611 超出的根因未知 | **人工确认**：抽查脑机接口 checkpoint 的 Step 3 result，确认章节数。如果无法确认，将归因标记为"待验证" |
| **P2** | **测试覆盖率 < 20%** | 5 个单元测试覆盖了 FM 审查场景，但大量 v5 代码（SessionEventLog、CheckpointManager、OutputSafety、TokenAudit）无测试。未来修改这些组件时缺乏回归保护 | 在 B 组中引入 `pytest-cov` 并设置覆盖率阈值（如 50%），优先覆盖核心组件（CheckpointManager 的保存/加载、OutputSafety 的文件名生成） |
| **P2** | **`QualityFlag.terminates_flow` 技术债务持续累积** | 当前方案 A（直接 raise）是临时方案。每新增一个需要终止流程的 high category，都需要手动在 `has_search_all_failed` 分支中确认是否 raise。如果遗忘，会重现 P0-1 类 bug | 将 `QualityFlag.terminates_flow` 纳入 B 组 **P0** 优先级（而非 P2），或建立"新增 category 检查清单" |
| **P2** | **v1.0 "9/9 通过"错误暴露自我评估漏洞** | 最初的自我评估在没有外部审查时过度乐观。虽然 v1.1 修正了，但类似漏洞可能在未来重复 | 建立"双人审查"或"强制 fact-checker"机制——在声称"通过"之前，必须运行 fact-checker 核查所有数据 |
| **P3** | **`_record_fm_failure_flag` 的 parse/exception/empty 分支未测试** | 文档测试覆盖缺口中已列出，但优先级较低 | 补充 2-3 个测试，覆盖 parse_error 和 exception 分支的 flag 生成 |
| **P3** | **MethodologyLoader 的 `METHODOLOGY_STRICT` 硬失败路径未测试** | 文档测试覆盖缺口中已列出 | 补充 1 个测试，验证 `METHODOLOGY_STRICT=true` 时抛出 `FileNotFoundError` |
| **P3** | **并发场景未测试** | 文档工程视角中已记录，当前 5 行业串行执行，Tavily 限流足够 | 推迟到 B 组 |

---

## 五、建议与行动清单

### P1（建议在下一次交付前完成）

| # | 行动 | 改动范围 | 估计工作量 | 说明 |
|---|------|----------|------------|------|
| 1 | **人工确认脑机接口 Step 3 章节数** | 检查 `demo2/checkpoints/脑机接口_*.json` 中 Step 3 的 `result` 字段 | 10 分钟 | 验证 ★★☆☆☆ 归因假设。如果确认为 5 章，归因成立；如果为 3-4 章，需要重新分析 6611 超出的根因 |
| 2 | **补充 `test_search_phase_timeout_cascade` 复合场景** | `tests/test_fm_review.py` | 20 分钟 | 测试 `search_partial_failure` + `search_phase_timeout` 同时存在时是否触发 `QualityGateError` |
| 3 | **建立"新增 category 检查清单"** | 文档或代码注释 | 15 分钟 | 在 `models.py` 的 `KNOWN_CATEGORIES` 注释中增加："新增 category 时，检查 `_check_quality_gate` / `has_search_all_failed` / Step 6 汇总 / 离线统计 等消费点" |

### P2（B 组评估时纳入）

| # | 行动 | 改动范围 | 说明 |
|---|------|----------|------|
| 4 | **引入 `pytest-cov` + 设置覆盖率阈值** | `requirements.txt` + `pytest.ini` | 量化测试覆盖率，当前 < 20% 需要提升 |
| 5 | **`QualityFlag.terminates_flow` 纳入 B 组 P0** | `models.py` + `frost_agent.py` | 根治 P0-1 类 bug，避免手动维护 raise 点 |
| 6 | **设计 2-3 个 v5 组件集成测试** | `tests/` | 验证 SessionEventLog + CheckpointManager + TokenAudit 在超时/降级场景下的协同工作 |
| 7 | **Step 3 章节数约束** | `frost_agent.py` Step 3 prompt | 根治脑机接口类问题，防止 LLM 随机选择过多章节 |
| 8 | **补充 `test_record_fm_failure_flag` 的 parse/exception 分支** | `tests/test_fm_review.py` | 完善测试覆盖 |
| 9 | **MethodologyLoader `METHODOLOGY_STRICT` 测试** | `tests/test_methodology_loader.py` | 验证硬失败路径 |

### P3（长期考虑）

| # | 行动 | 说明 |
|---|------|------|
| 10 | **引入 logging 框架统一 print/warnings.warn** | 文档已记录为 P3 follow-up，当前 print 策略合理但长期需要统一 |
| 11 | **并发场景测试** | Tavily 和 LLM API 的并发限流测试，B 组或 C 组评估 |

---

## 六、已确认的事实与已修正的判断

| 原判断 | 修正 | 依据 |
|--------|------|------|
| 无（首次评估此实现日志） | — | — |

**本次验证的关键事实**：
1. `demo2/frost_agent.py` 1301 行（验证：wc 输出）
2. `test_search_phase_timeout_cascade` 测试存在（验证：文档第 6.2 节测试覆盖矩阵）
3. P0-1 bug 的修复：从 `_check_quality_gate` 硬编码改为 `has_search_all_failed` 直接 raise（验证：文档第 3.3 节）
4. 5 行业真实 API 验证，成本 ¥0.1538-0.1829（验证：文档第 8.2 节表格）
5. 脑机接口 6611 归因可信度 ★★☆☆☆（验证：文档第 8.2 节注释）
6. 测试覆盖缺口 5 项（验证：文档第 6.4 节）
7. 未采纳建议 3 项（验证：文档第 5.2 节）

---

## 七、留给团队的核心提问

1. **P0-1 类 bug 的预防机制**：`QualityFlag.terminates_flow` 是否纳入 B 组 P0？还是建立"新增 category 检查清单"作为临时方案？

2. **脑机接口归因的人工确认**：是否已人工确认 Step 3 选 5 章？如果未确认，验收 FAIL 的结论不变，但根因分析需要标记为"待验证"。

3. **测试覆盖率目标**：B 组是否计划将测试覆盖率提升到某个阈值（如 50%）？还是保持当前"关键路径测试覆盖"的策略？

4. **v5 组件集成测试**：是否计划设计集成测试（如"超时场景下 SessionEventLog + CheckpointManager + TokenAudit 的协同验证"）？还是推迟到阶段三？

---

*评估报告版本：v1.0*
*评估者：同行评议专家（Kimi）*
*评估完成时间：2026-06-27*
*评估类型：代码/实现审计（验证修复实现质量与文档可信度）*