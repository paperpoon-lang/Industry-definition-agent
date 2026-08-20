# 阶段二 B 组修复计划

> 版本：v1.0 | 日期：2026-06-29
> 范围：A 组收尾后发现的设计层面增强 + A 组未覆盖的测试债务 + Kimi/architecture-critic 评议积累的后续建议
> 基线：开发日志 v1.3（A 组已收尾，验收 9/9 通过）
> A 组产出：`阶段二-A组修复实现日志.md` v1.3 / `脑机接口报告超长根因修正.md`

---

## 一、背景

A 组完成了 4 项修复 + 测试基础设施搭建，验收 9/9 通过。但 A 组的定位是"让现有设计能跑"（修 bug），B 组的定位是"让系统更强健"（架构增强 + 技术债务清理）。

B 组工作来源包括：
- A 组实现日志 9.4 节标记"待补"的 P2/P3 项
- Kimi 评议（2026-06-29）的三项新发现
- architecture-critic v1.2 审查的未采纳建议
- 实测发现的设计层面固有限制

---

## 二、问题分类

| 类别 | 说明 |
|------|------|
| **B1 架构增强** | 设计层面的改进，非修复 bug，是让系统更强健 |
| **B2 测试债务** | A 组未覆盖的测试缺口 |
| **B3 可观测性与标准化** | 日志、审计、格式一致性 |
| **B4 探索性评估** | 需要先评估可行性再决定是否动手 |

---

## 三、B1 架构增强

### B1-1：SSOT 重构 — QualityFlag.terminates_flow（P2，1-2d）

**背景**：A 组 P0-1 的根因是 `_check_quality_gate` 硬编码 `category == "or_fallback_result"`，新增 `search_phase_timeout` 时终止条件未同步。当前方案 A（直接 raise）绕过了 `_check_quality_gate`，但未来每新增一个需终止的 high category 都要手动维护 raise 点。

**方案**：在 `QualityFlag` 新增 `terminates_flow: bool = False` 元数据字段，`_check_quality_gate` 改为扫描所有 `severity == "high" and terminates_flow == True` 的 flag。

**影响文件**：`demo2/models.py`（QualityFlag 定义）+ `demo2/frost_agent.py`（`_check_quality_gate` 函数 + `_run_step1`）

**风险**：修改 `_check_quality_gate` 是 A 组已验证的"state 传递逻辑"，需按规则 10.2 在 Edit 前后各调一次 architecture-critic。

---

### B1-2：补搜上限可配置化（P2，2-4h）

**背景**：5/5 行业 2026-06-27 批次全部触发 `data_gaps_remaining`（补搜 2 个 query 后仍有 1-4 个缺口）。当前硬编码上限 2，导致 FM 审查识别的额外缺口无法填补。

**当前状态**：

| 行业 | 补搜后仍缺的口数 |
|------|-----------------|
| 脑机接口 | 2（技术路线对比 + 商业模式） |
| 钙钛矿 | 2（行业分类归属 + 包含/排除边界） |
| 固态电池 | 1（行业分类标准参照） |
| 室内垂直农业 | 2（官方分类/权威定义 + 监管审批要求） |
| 细胞培养肉 | 2（官方标准/监管定义 + 竞争格局/企业信息） |

**方案**：
- 将补搜上限从硬编码 `2` 改为环境变量 `MAX_SUPPLEMENTARY_QUERIES`（默认 2）
- 增加"补搜循环安全阀"：总 query 数（初始 3 + 补搜）不超过 10，防止无限循环
- 在 Step 1 的 `_record_fm_failure_flag` 中增加 detail 字段 `max_queries_reached` 标注"因达到上限未继续补搜"

**影响文件**：`demo2/frost_agent.py`（`step1_search_with_supplement` 函数）

**权衡**：
- 调大到 4：每行业多 1-2 次 FM 审查 LLM 调用 + Tavily 搜索，成本约 +30-50%（当前 ¥0.15-0.18/行业）
- 默认保持 2：A 组已验证的配置不变，仅开放可配置入口

---

### B1-3：Step 3 超时策略（P3，<1h）

**背景**：修复计划 7.3 假设"钙钛矿 Step 3 可能超时"，但 A 组实测 5/5 行业 Step 3 全部完成。Step 3 偶发超时是 LLM API 慢响应问题，非代码缺陷。

**方案**：给 Step 3 的 `call_with_timeout` 增加可选 timeout 参数（环境变量 `STEP3_TIMEOUT`，默认 120s），与 Step 1 的 `SEARCH_PHASE_TIMEOUT` 保持一致的防御层级。不设默认行为变化（当前 120s 未触发超时，不改动）。

---

## 四、B2 测试债务

### B2-1：MethodologyLoader METHODOLOGY_STRICT 持久化测试（P2，<1h）

**内容**：A 组修复 4 在 `methodology_loader.py` 增加了 `METHODOLOGY_STRICT=true` 硬失败路径，但仅有代码审查确认，无持久化单元测试。

**方案**：新建 `tests/test_methodology_loader.py`，mock 文件系统，测试 `METHODOLOGY_STRICT=true` 时文件缺失 → 抛异常；`METHODOLOGY_STRICT=false` 时 fallback → 正常加载。

---

### B2-2：降级路径集成测试（P2，1-2d）

**背景**：A 组 9 个测试全是单元测试（mock），缺少组件间协同验证。例如：`search_phase_timeout` 触发后是否正确记录到 JSONL？是否正确写入 checkpoint？`token_audit` 是否正确统计超时前的 token 消耗？

**方案**：新增 1 个集成测试类 `test_integration_degradation`：
- `test_timeout_jsonl_integration`：mock step1 超时 → 验证 JSONL 含 `search_phase_timeout(high)` + `step_complete(all_search_failed)` 事件
- `test_timeout_checkpoint_integration`：mock step1 超时 → 验证 checkpoint 文件被写入且状态为 `all_search_failed`
- `test_timeout_token_audit_integration`：mock step1 超时 → 验证 `token_audit` 统计了超时前的 LLM 调用

**影响文件**：`tests/test_integration_degradation.py`（新建）

---

### B2-3：pytest-cov + 覆盖率阈值（P3，1-2h）

**内容**：当前覆盖率估计 < 20%（9 个测试覆盖 ~340 行新增代码）。引入 `pytest-cov`，设阈值（如 40%），CI 不达标则失败。

**方案**：`pip install pytest-cov` → 在 `pytest.ini` 配置 `--cov-fail-under=40`。

---

## 五、B3 可观测性与标准化

### B3-1：logging 框架统一（P3，1-2d）

**背景**：当前 `print` 和 `logger.log()` 混用。`methodology_loader.py` 用 `print`（A 组修复 4 的 trade-off 决定短期一致优先），`frost_agent.py` 用 `SessionEventLog`。两个输出通道不可统一控制。

**方案**：引入 Python `logging` 模块，`methodology_loader.py` 的 `print` → `logging.warning()`，`frost_agent.py` 的 `print` → `logging.info()`。保留 `SessionEventLog` 用于结构化审计事件（`llm_raw_response`、`step_complete` 等），`logging` 用于人类可读的运行日志。

**注意**：这是 P3，需评估对现有 `SessionEventLog` 的影响，不破坏 JSONL 输出。

---

### B3-2：Step 3 chapters JSON 格式稳定性（P3，1-2h）

**背景**：Kimi 发现 2026-06-27 批次 5 个 Step 3 checkpoint 中，2 个行业有 `chapter_id` 字段，3 个行业无。LLM JSON 输出格式不稳定。

**方案**：
- 在 Step 3 prompt 中增加 `chapter_id` 的格式约束（要求输出 `{"chapter_id": N, "title": "...", ...}`）
- 或代码侧增加后处理：`chapters` 缺少 `chapter_id` 时自动补序号（按列表顺序 1, 2, 3...）

**影响**：当前无直接影响（Step 4 不消费 `chapter_id`），但未来若需程序化消费（如自动生成目录），需先统一格式。

---

### B3-3：规则 10.2 子条款（P3，<1h）

**背景**：architecture-critic v1.2 审查建议在规则 10.2 中增加子条款——修改 `_check_*`/`has_*_failed`/`raise QualityGateError` 也需触发 Edit 前审查。A 组 P0-1 就是因为 `_check_quality_gate` 调用链未被审查覆盖而漏掉的。

**方案**：修改 `.trae/rules/project_rules.md` 规则 10.2，新增一行触发条件。

---

## 六、B4 探索性评估

### B4-1：验收标准设计评估（P3，1-2d）

**背景**：A 组 v1.3 将验收区间放宽至 4,320-7,000，但 Kimi 新考虑质疑"跨行业统一区间"的合理性——不同行业的话题复杂度天然不同，统一字符数区间可能对简单行业太宽、对复杂行业太窄。

**评估任务**：
1. 用现有 5 行业数据（4,833 / 4,887 / 5,144 / 5,202 / 6,611）分析区间合理性
2. 提出替代方案：
   - 方案 A：保留跨行业统一区间，但不作为硬性 FAIL 条件（改为"超出触发人工抽查"）
   - 方案 B：改为同行业批次间波动标准（如 ±20%）
   - 方案 C：引入多维度标准（字符数 + 段落数 + 信息密度评分）
3. 输出评估报告，由用户决策是否实施

**产出**：一篇 B 组评估文档（<100 行），不立即修改代码。

---

## 七、待办总览与优先级

| 编号 | 内容 | 类别 | 优先级 | 工作量 | A 组来源 |
|------|------|------|--------|--------|---------|
| B1-1 | QualityFlag.terminates_flow SSOT 重构 | B1 架构 | **P1** | 1-2d | architecture-critic P0-1 长期方案 |
| B1-2 | 补搜上限可配置化 | B1 架构 | **P2** | 2-4h | ✅ 已完成（步骤1+2，33 passed） |
| B1-3 | Step 3 超时策略 | B1 架构 | P3 | <1h | 修复计划 7.3 遗留 |
| B2-1 | MethodologyLoader 持久化测试 | B2 测试 | P2 | <1h | ✅ 已完成（8 个测试，231 行） |
| B2-2 | 降级路径集成测试 | B2 测试 | **P1** | 1-2d | Kimi Q3 |
| B2-3 | pytest-cov + 覆盖率阈值 | B2 测试 | P3 | 1-2h | A 组 9.4 |
| B3-1 | logging 框架统一 | B3 标准化 | P3 | 1-2d | A 组 9.4 |
| B3-2 | Step 3 chapters 格式稳定性 | B3 标准化 | P3 | 1-2h | Kimi 发现 1 |
| B3-3 | 规则 10.2 子条款 | B3 标准化 | P3 | <1h | architecture-critic v1.2 P2-3 |
| B4-1 | 验收标准设计评估 | B4 探索 | P3 | 1-2d | Kimi 新考虑 |

---

## 八、建议实施顺序

1. **B1-1**（P1 架构）→ 修复 A 组 P0-1 的设计债务，影响面大，先做
2. **B2-2**（P1 测试）→ 与 B1-1 并行，验证降级路径不回归
3. **B1-2**（P2 架构）→ 解决用户关注的"补搜后仍有缺口"问题
4. **B2-1**（P2 测试）→ 补 A 组缺失的持久化测试
5. **B3-1/B3-2/B3-3**（P3 标准化）→ 技术债务清理
6. **B4-1**（P3 探索）→ 不立即改代码，先输出评估报告供决策

---

## 九、未纳入 B 组的项目（及理由）

| 项目 | 来源 | 不纳入理由 |
|------|------|-----------|
| Step 3 章节数约束 | A 组 9.4（已废弃） | v1.3 验证无效：5 篇报告均为 4 章 |
| FM 审查模型升级（DeepSeek→其他） | 已知限制 1 | 成本/延迟权衡需独立评估，不属于 B 组"修复"范畴 |
| 补搜 query 质量引入外部知识源 | 已知限制 2 | 设计层面的根本限制，需 D 组或独立研究 |
| 并发执行支持 | A 组 9.3 | 当前 Tavily 限流 1000 req/min，5 行业串行远未触及，无需并发 |

---

*计划版本：v1.0*
*关联文档：`阶段二-A组修复实现日志.md` v1.3 / `脑机接口报告超长根因修正.md` / `kimi产出的文档/脑机接口报告超长根因-调查报告.md`*
