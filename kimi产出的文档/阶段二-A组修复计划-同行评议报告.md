# 阶段二 A 组修复计划 同行评议报告

> **评估者身份**：同行评议专家（协作式评估者，非权威甲方）  
> **评估日期**：2026-06-25  
> **评估对象**：《阶段二-A组修复计划.md》（v1.1）  
> **评估类型**：代码/实现审计（验证修复计划与实际代码的对齐度、可实施性、风险）  
> **验证范围**：`demo2/` 目录实际代码 + `开发日志/阶段二-A组-基础设施加固开发日志.md`（v1.2）

---

## 一、总体判断

修复计划 v1.1 **总体合理，问题分类准确，修复方案具体且可验证，但存在 3 个需要修正的脆弱性**：

1. **验收标准"FM 审查超时数 = 0"过于严格**（5 样本统计不足，偶发 API 慢可能不可控）
2. **"修复 1 共 6 处修改"的计数与实际不符**（实际涉及 8 处文件修改，低估可能影响工作量估算）
3. **test_fm_review.py 测试中的 `max_retries=1` 参数与实际 `call_with_timeout` 接口不匹配**（修复后代码中的 `max_retries` 被移除，改为函数内部固定）

此外，修复计划有 **2 个优质设计**：新增搜索阶段外层 timeout（前瞻性）和 4 条 fixes_required 循环规则补充（二次评议成果）。工作量估算 8-13h 合理，但测试基础设施（2-3h）可能偏低。

---

## 二、分维度评估

### 2.1 问题分类准确性

| 问题 | 开发日志记录 | 修复计划分类 | 验证结果 | 说明 |
|------|-------------|-------------|---------|------|
| P2 #4 FM 审查 30s 超时偏短 | 开发日志 §5.6.2 发现 1：5 行业 4 个触发超时，根因确认为 30s 阈值偏短 | **A 组修复** | ✅ 正确 | 根因确认（`asyncio.TimeoutError` 的 `str()` 返回空字符串），4/5 行业受影响，是 A 组新引入的补搜循环的核心配置缺陷 |
| P2 #5 FM 审查失败原因未区分 | 开发日志 §5.6.2 发现 1：异常消息为空，统一记为 `json_parse_fallback` | **A 组修复** | ✅ 正确 | 当前代码第 372-375 行 `except (asyncio.TimeoutError, Exception) as e` 统一处理，确实未区分 |
| P2 #3 FM 审查 LLM 调用未记日志 | 开发日志未直接记录，但代码验证确认缺失 | **A 组修复** | ✅ 正确 | 实际代码验证：第 327-375 行 `_fm_review_search_results` 函数内部无 `logger.log` 调用；第 935 行是 Step 1 的 LLM summary 调用，不是 FM 审查调用 |
| P2 #2 Step 5 LLM 调用未记日志 | 开发日志未直接记录，但代码验证确认缺失 | **A 组修复** | ✅ 正确 | 实际代码验证：第 1117-1121 行 evaluate 调用后无 `logger.log("llm_raw_response", ...)`，其他步骤（Step 1-4）均有 |
| P2 #1 MethodologyLoader fallback 静默 | 开发日志未直接记录，但代码验证确认 | **A 组修复** | ✅ 正确 | 实际代码验证：第 126-130 行 fallback 路径无 print 或 warning |
| 新增：搜索阶段无外层 timeout | 开发日志 §5.6.2 发现 1：FM 审查耗时 68s，修复后最坏 258s | **A 组修复** | ✅ 正确 | 前瞻性设计——修复 #4 后时延增加，需要外层保护 |
| 问题 6 Step 3 偶发超时 | 开发日志 §5.6.2 发现 2：根因硅基流动 API 慢，3 次 60s 调用超时 | **留到 B 组** | ⚠️ 有条件接受 | 根因是 API 慢，非 A 组代码缺陷。但钙钛矿的 Step 3 超时是否与 Step 1 FM 审查超时有关（搜索信息不足导致 Step 3 prompt 更复杂？）开发日志未分析此关联。建议 B 组评估时补充检查 |
| 已知限制 1 FM 审查模型认知偏差 | 开发日志 §八 已知限制 | **留到之后阶段** | ✅ 正确 | 设计层面固有限制，A 组无法消除 |
| 已知限制 2 补搜 query 质量依赖 FM | 开发日志 §八 已知限制 | **留到之后阶段** | ✅ 正确 | 设计层面固有限制 |
| 问题 8 429 限流未实测 | 开发日志 §八 已知限制 | **无需修复** | ✅ 正确 | 代码逻辑已通过 agent-code-validator 验证，未自然触发不代表 bug |

**观察**：问题分类准确，4 个 A 组修复全部对应 A 组新引入组件的缺陷，3 个留到之后阶段的问题全部不是 A 组代码缺陷。新增搜索阶段外层 timeout 是优质的前瞻性设计。

### 2.2 修复方案可实施性

#### 修复 1：FM 审查超时 + 区分 + 日志（6 处修改）

**验证行号**：

| 修改点 | 修复计划引用行号 | 实际代码位置 | 匹配 | 验证说明 |
|--------|---------------|-------------|------|---------|
| `_fm_review_search_results` 函数 | 327-375 | 327-375 | ✅ | 函数定义完全匹配 |
| `timeout_seconds=30` | 361 | 361 | ✅ | 硬编码 30s 确认 |
| 循环内调用 | 459-470 | 459-470 | ✅ | 调用点和 flag 记录确认 |
| 最终审查 | 512-524 | 512-524 | ✅ | 调用点和静默问题确认 |
| `step1_search_with_supplement` 调用 | 889 | 889 | ✅ | _run_step1 中调用确认 |

**修复方案设计**：
- 超时 30s → 环境变量 `FM_REVIEW_TIMEOUT`（默认 60s）：**合理**。可配置，避免硬编码，且默认 60s 覆盖了实测 68s 的 worst case。
- 区分 timeout/parse_error/exception：**合理**。当前代码第 372-375 行的统一 `except (asyncio.TimeoutError, Exception)` 确实掩盖了不同失败模式。
- 新增 `_error_type` 字段返回：***有风险**——这个字段名可能与 LLM 返回的正常字段冲突（虽然概率极低）。建议用 `_fm_error_type` 或更独特的名称。*
- 新增 `fm_review_skipped` category：***合理**。不重用 `timeout_retry`（语义不同）是正确的，避免 validator 冲突。*
- 记录 FM 审查 LLM 调用：`logger.log("llm_raw_response", {"step_id": "1_info_collection_fm_review", ...})`：**合理**。但注意：Step 1 的 LLM 调用已经有 2 次（FM 审查 + LLM summary），加上补搜循环中可能多次 FM 审查，日志中 `step_id` 用 `1_info_collection_fm_review` 区分是合理的。但建议用 `1_info_collection_fm_review_round_{n}` 来区分第 1 轮和最终审查，否则日志中会有多个相同 `step_id` 的事件，查询时无法区分。

**修复 1 的实际修改处数**：修复计划说"6 处修改"，但实际涉及：
1. `models.py`：新增 `fm_review_skipped` category（1 处）
2. `frost_agent.py`：顶部环境变量 `_FM_REVIEW_TIMEOUT`（1 处）
3. `frost_agent.py`：`_fm_review_search_results` 函数重写（1 处，但内部多处）
4. `frost_agent.py`：新增 `_record_fm_failure_flag` 辅助函数（1 处）
5. `frost_agent.py`：循环内调用方修改（第 463-470 行，1 处）
6. `frost_agent.py`：最终审查修改（第 512-524 行，1 处）
7. `frost_agent.py`：`step1_search_with_supplement` 签名修改 + 内部 2 处调用点传入 logger（1 处函数签名 + 2 处调用）
8. `frost_agent.py`：`_run_step1` 调用 `step1_search_with_supplement` 时传入 logger（第 889 行，1 处）

总计 **8 个独立修改点**（修复计划说 6 处，可能是将 7 和 8 合并为"调用链修改"）。但考虑到 Step 1 的调用链涉及 `step1_search_with_supplement`（签名修改）→ `_fm_review_search_results`（签名修改 + 内部 logger 使用）→ `_run_step1`（传入 logger），这实际上是 3 层嵌套调用的修改，修改点比 6 处更多。工作量估算 4-6h 可能偏乐观，建议调整为 5-7h。

#### 修复 2：搜索阶段外层 timeout（新增）

**方案设计**：给 `step1_search_with_supplement` 加 `asyncio.wait_for` 外层 300s 兜底。

**验证**：
- 修复 1 后最坏时延：搜索 ~8s + FM 审查 60s×2 + 补搜 ~8s + FM 最终审查 60s×2 = 约 256s（修复计划说 258s，计算正确）
- 300s 兜底覆盖了 256s 的最坏情况，有 44s 余量
- **但**：300s 外层 timeout 只包裹 `step1_search_with_supplement`，不包含后续的 LLM summary 调用（第 935 行）。所以 Step 1 整体最坏时延是 256s + LLM summary 180s×3 = 796s。Step 1 的 `STEP_BUDGETS` 配置为 180s timeout，但 `step1_search_with_supplement` 不受 `STEP_BUDGETS` 限制。

**修复方案合理**，但有一个**遗漏**：`STEP_BUDGETS` 的 `timeout_seconds=180` 只作用于 `call_with_timeout` 包裹的 LLM summary 调用，不覆盖搜索阶段。所以搜索阶段的外层 timeout 是必需的。但建议将 `STEP_BUDGETS` 的 Step 1 timeout 从 180s 调整为 300s 或更大，以覆盖整个 Step 1（搜索 + LLM summary）。否则 `STEP_BUDGETS` 的 timeout 和实际时延不匹配。

或者更简单地：在 `_run_step1` 中，给 `step1_search_with_supplement` 加 `asyncio.wait_for` 后，再给整个 `call_with_timeout(lambda: call_llm(...))` 加另一个 `asyncio.wait_for`，但这会造成嵌套 timeout。建议将 `STEP_BUDGETS["1_info_collection"].timeout_seconds` 从 180s 增加到 300s 或 360s，以覆盖搜索阶段（256s）+ LLM summary（~60s）。

**等等，开发日志说 Step 1 的 `STEP_BUDGETS` timeout 已经调到 180s 了**（v5.2 变更：120s→180s）。但 180s 不够覆盖搜索阶段 256s。所以修复计划中的 300s 外层 timeout 是独立于 `STEP_BUDGETS` 的。这会造成两个 timeout 机制：
1. `asyncio.wait_for(step1_search_with_supplement, timeout=300)`：搜索阶段外层
2. `call_with_timeout(..., timeout_seconds=180)`：LLM summary 调用

如果搜索阶段在 256s 完成，然后 LLM summary 在 180s 内完成，总时间 436s。如果 `STEP_BUDGETS` 的 timeout 180s 只包裹 LLM 调用，而搜索阶段已经用了 256s，那么总时间 436s 超过了 `STEP_BUDGETS` 的 180s。但 `STEP_BUDGETS` 的 timeout 是作用于 `call_with_timeout` 的，而 `call_with_timeout` 只包裹 LLM 调用，所以 180s 是 LLM 调用的超时，不是整个 Step 1 的超时。

**这个设计是合理的**，因为搜索阶段和 LLM 调用是两个独立的超时：
- 搜索阶段：300s（包括搜索 + FM 审查 + 补搜）
- LLM 总结：180s（独立的 LLM 调用）

但建议修复计划中明确说明：`STEP_BUDGETS["1_info_collection"].timeout_seconds` 只覆盖 LLM 总结调用，不覆盖搜索阶段。搜索阶段的超时由外层 `asyncio.wait_for` 控制。

#### 修复 3：Step 5 记日志

**验证**：代码第 1117-1121 行确实无 `logger.log`。

**方案**：在 `eval_result = await call_with_timeout(...)` 后加 `logger.log("llm_raw_response", ...)`。**简单、正确**。工作量 <1h 合理。

#### 修复 4：MethodologyLoader fallback warning

**验证**：代码第 126-130 行：
```python
if not path.exists():
    v4_path = Path(__file__).parent / "方法论-v2.md"
    if v4_path.exists():
        path = v4_path
        self._v4_single_file_path = v4_path
    else:
        raise FileNotFoundError(...)
```

确实没有 print 或 warning。修复方案增加 `print(f"[MethodologyLoader 警告] ...")` 和可选 `METHODOLOGY_STRICT=true` 时 raise。**合理**。工作量 <1h 合理。

### 2.3 测试基础设施

修复计划新增 `demo2/tests/test_fm_review.py`：

```python
@pytest.mark.asyncio
async def test_fm_review_timeout():
    async def slow_llm(...):
        await asyncio.sleep(70)  # 模拟超时
        return {"text": "{}"}
    result = await _fm_review_search_results(..., slow_llm)
    assert result.get("_error_type") == "timeout"
```

**问题**：`slow_llm` 函数签名是 `async def slow_llm(system_prompt, user_prompt, max_tokens)`，但 `_fm_review_search_results` 的 `llm_call_fn` 参数签名是 `async def fn(system_prompt, user_prompt, max_tokens) -> dict`。修复后的 `_fm_review_search_results` 内部调用：

```python
result = await call_with_timeout(
    lambda: llm_call_fn(...),
    timeout_seconds=_FM_REVIEW_TIMEOUT,  # 60s
    max_retries=1,
)
```

但等等，**修复计划中 `call_with_timeout` 的 `max_retries=1` 参数可能与实际代码不匹配**。让我检查当前 `call_with_timeout` 的签名：

```python
async def call_with_timeout(fn, max_retries: int = 2, timeout_seconds: float | None = None):
```

但 `call_with_timeout` 的实现中，`max_retries` 参数确实存在。修复方案说 `max_retries=1`，这是合法的（可以传入 1）。

但测试中的 `slow_llm` 每次 sleep 70s，`call_with_timeout` 的 timeout 是 60s，所以第 1 次调用 sleep 70s → 60s 超时，重试 1 次（max_retries=1）→ 再 sleep 70s → 60s 超时 → 最终抛出 `asyncio.TimeoutError`。总时间 60s + 1s(退避) + 60s = 121s。测试函数本身没有 timeout，所以测试会成功，但耗时 121s。如果 pytest 有全局 timeout（如 120s），这个测试会失败。

**建议**：测试中使用 `asyncio.sleep(65)` 而不是 70s，这样第 1 次调用 60s 超时，重试 1 次 60s 超时，总时间 60s + 1s + 60s = 121s。或者使用 `call_with_timeout(..., max_retries=0)` 减少重试次数，测试时间 60s。或者 mock `call_with_timeout` 直接抛出 `asyncio.TimeoutError`。

更好的方案：在测试中直接 mock `call_with_timeout` 使其立即抛出 `asyncio.TimeoutError`，这样测试瞬间完成，不依赖实际 sleep 时间。但这样测试的是 `_fm_review_search_results` 的异常处理逻辑，而不是 `call_with_timeout` 的超时逻辑。考虑到测试的是 `_fm_review_search_results` 的异常处理，mock `call_with_timeout` 是更合理的。

**另一个问题**：`test_fm_review.py` 中的 `pytest` 和 `pytest-asyncio` 依赖未在 `requirements.txt` 中声明。需要补充：
```
pytest>=7.0
pytest-asyncio>=0.21.0
```

修复计划未提及此依赖补充。

### 2.4 验收标准

修复计划将验收标准从"≤ 1/5"收紧到"超时数 = 0"：

> **原标准**：≤ 1/5 行业 FM 审查超时（因为 5 样本中允许 1 个）  
> **新标准**：5 个行业 FM 审查超时数 = 0；且 FM 审查实际耗时 P95 ≤ 45s

**问题**：
- 5 样本的"超时数 = 0"统计意义不足——如果真实超时率是 5%，5 样本中 0/5 的概率是 77%（0.95^5），所以"0/5"并不能证明超时率很低。更合理的验收标准是"0/5 通过，但接受偶发超时（<10%）作为已知限制"。
- 钙钛矿的 Step 3 超时（问题 6）不是本次修复范围，但钙钛矿的测试仍然可能失败。修复计划说"实际有效验证 4 行业 ≈ ¥0.68-0.88"，这意味着只跑 4 个成功行业。但验收标准说"5 个行业"，这与"实际有效验证 4 行业"矛盾。建议明确："跑 5 个行业，允许钙钛矿因 Step 3 超时（非本修复范围）失败，其余 4 个行业必须全部成功"。
- "FM 审查实际耗时 P95 ≤ 45s"：P95 需要至少 20 个样本才能计算。5 样本无法计算 P95。建议改为"5 个行业中 FM 审查最大耗时 ≤ 60s"或"平均耗时 ≤ 30s"。

### 2.5 工作量估算

| 修复 | 修复计划估算 | 我的评估 | 偏差原因 |
|------|------------|---------|---------|
| 修复 1（FM 超时+区分+日志） | 4-6h | 5-7h | 实际涉及 8 个独立修改点（修复计划说 6 处），且测试验证（mock 3 种场景）需要额外时间 |
| 修复 2（搜索阶段外层 timeout） | 1-2h | 1-2h | ✅ 合理 |
| 修复 3（Step 5 记日志） | <1h | <1h | ✅ 合理 |
| 修复 4（MethodologyLoader warning） | <1h | <1h | ✅ 合理 |
| 测试基础设施（test_fm_review.py） | 2-3h | 3-4h | pytest-asyncio 配置、mock 设计、3 个测试场景，以及测试依赖补充（requirements.txt） |
| **合计** | **8-13h** | **10-15h** | 测试基础设施 + 修复 1 修改点多于预期 |

**总工作量建议**：10-15h（比修复计划的 8-13h 增加约 2h）。

---

## 三、关键问题列表（Q 级——需要团队反馈）

### Q1：验收标准"超时数 = 0"在 5 样本下统计意义不足，且 P95 无法计算

- **我的观察**：5 样本的"0/5"只能证明在测试条件下表现良好，不能证明生产环境零超时。如果真实超时率是 5%，0/5 的概率是 77%。P95 需要至少 20 个样本。钙钛矿的 Step 3 超时（非本修复范围）可能导致测试失败。
- **建议**：
  - 方案 A：将"超时数 = 0"改为"超时率 ≤ 10%（在 ≥ 20 个样本下）"，但这对 A 组工作量增加太大
  - 方案 B：保留 5 行业测试，但明确"0/5 通过 = 验收通过，但已知偶发超时（API 响应慢）作为限制条件记录"
  - 方案 C：将 P95 改为"最大耗时 ≤ 60s"（5 样本可计算最大值）
- **需要团队反馈**：是否接受方案 B（保留 5 样本但降低零超时要求为"可接受偶发超时"）？

### Q2：测试基础设施中的 `pytest` 和 `pytest-asyncio` 依赖未声明

- **我的观察**：`test_fm_review.py` 需要 `pytest` 和 `pytest-asyncio`，但 `requirements.txt` 只有 4 行（pydantic, openai, tavily-python, python-dotenv），没有 pytest 相关依赖。
- **建议**：补充 `pytest>=7.0` 和 `pytest-asyncio>=0.21.0` 到 `requirements.txt`。或者将测试放在 `tests/` 目录并单独创建 `tests/requirements.txt`。
- **需要团队反馈**：测试是否作为 A 组的交付物？如果是，依赖补充需要包含在修复中。如果不是，可以推迟到 B 组。

### Q3：修复 1 的 `step_id` 日志区分问题

- **我的观察**：修复方案中 FM 审查的日志 `step_id` 为 `"1_info_collection_fm_review"`，但补搜循环中有多次 FM 审查（第 1 轮、第 2 轮、最终审查），日志中会有多个相同 `step_id` 的事件，无法区分是第几轮。
- **建议**：在 `logger.log` 的 `data` 字段中增加 `round_label` 字段（如 `"第 1 轮"`、`"最终审查"`），或者将 `step_id` 改为 `"1_info_collection_fm_review_round_1"`。这样在 JSONL 查询时可以通过 `data.round_label` 过滤。
- **需要团队反馈**：是否接受在 `data` 中增加 `round_label` 字段？

### Q4：修复 2 的 `STEP_BUDGETS` 与搜索阶段外层 timeout 的关系

- **我的观察**：`STEP_BUDGETS["1_info_collection"].timeout_seconds=180` 只覆盖 LLM 总结调用，不覆盖搜索阶段（搜索阶段由 300s 外层 `asyncio.wait_for` 控制）。这造成两个独立的 timeout 机制，文档中未明确说明这种分层设计。
- **建议**：在修复计划或开发日志中补充说明：Step 1 的 `STEP_BUDGETS` timeout 只作用于 LLM 调用，搜索阶段（搜索 + FM 审查 + 补搜）的 timeout 由外层 `asyncio.wait_for` 控制。或者将 `STEP_BUDGETS` 的 Step 1 timeout 从 180s 增加到 360s，以覆盖整个 Step 1（搜索 256s + LLM 总结 60s）。
- **需要团队反馈**：是否接受将 `STEP_BUDGETS` 的 Step 1 timeout 增加为 360s？还是保持分层 timeout（搜索 300s + LLM 180s）并在文档中说明？

---

## 四、风险矩阵

| 风险等级 | 风险 | 说明 | 建议应对 |
|----------|------|------|----------|
| **P2** | **测试基础设施依赖缺失导致测试无法运行** | `pytest` 和 `pytest-asyncio` 未在 `requirements.txt` 中声明，新环境运行测试会失败 | **补充依赖**：在 `requirements.txt` 或 `tests/requirements.txt` 中增加 `pytest>=7.0` 和 `pytest-asyncio>=0.21.0` |
| **P2** | **验收标准"0/5 超时"不可重复** | 5 样本统计不足，偶发 API 慢可能导致验收失败（即使修复正确）。钙钛矿的 Step 3 超时（非修复范围）也可能导致测试失败 | **放宽验收标准**：允许"0/5 通过或 1/5 失败（且失败原因是非修复范围的已知问题）"。将 P95 改为"最大耗时" |
| **P2** | **测试函数耗时过长（121s）** | `test_fm_review_timeout` 用 `asyncio.sleep(70)` 模拟超时，配合 `max_retries=1` 和 60s timeout，实际耗时 121s。pytest 默认无全局超时，但 CI 环境可能有 | **优化测试**：将 `sleep(70)` 改为 `sleep(65)`，或者 mock `call_with_timeout` 直接抛出 `TimeoutError`，将测试时间降到 <1s |
| **P3** | **`_error_type` 字段名冲突** | `_error_type` 是函数返回的字典字段，虽然概率极低，但 LLM 可能返回包含此字段的 JSON（如 FM 审查 prompt 要求返回 `data_gaps` 和 `suggested_queries`，但 LLM 不总是遵守格式） | **更名**：改为 `_fm_error_type` 或 `__error_type__`，降低冲突概率。或者增加验证：如果返回 dict 包含 `data_gaps` 或 `suggested_queries`，忽略 `_error_type` |
| **P3** | **修复 1 实际修改点 8 处（非 6 处）** | 低估修改点数量可能导致工作量估算偏乐观。`step1_search_with_supplement` 签名修改 + 2 处调用点 + `_run_step1` 传入 logger 是 4 个额外修改点 | **调整工作量**：修复 1 从 4-6h 改为 5-7h，总工作量从 8-13h 改为 10-15h |
| **P3** | **Step 3 超时与 Step 1 FM 审查超时的关联未分析** | 钙钛矿 Step 1 FM 审查超时 → 补搜未执行 → 搜索信息不足 → 可能 Step 3 的 prompt 更复杂（因为上下文更少需要更多推理？）→ 导致 Step 3 超时 | **B 组评估**：在 B 组评估 Step 3 超时根因时，检查是否与 Step 1 搜索质量有关。如果有关，修复 FM 审查超时后 Step 3 超时可能也会减少 |

---

## 五、建议与行动清单

### P0（修复前必须完成）

无 P0。修复计划整体合理，不需要阻塞性修改。

### P1（修复过程中完成）

| # | 行动 | 改动范围 | 估计工作量 | 说明 |
|---|------|----------|------------|------|
| 1 | **补充测试依赖**：`pytest>=7.0` 和 `pytest-asyncio>=0.21.0` | `requirements.txt` 或 `tests/requirements.txt` | 5 分钟 | 测试基础设施的前提条件 |
| 2 | **优化测试函数耗时**：`asyncio.sleep(70)` → mock `call_with_timeout` 直接抛 `TimeoutError` | `tests/test_fm_review.py` | 15 分钟 | 避免测试耗时 121s，改为 <1s |
| 3 | **明确验收标准中的样本限制**：0/5 通过 = 验收通过，但记录"偶发超时（API 响应慢）作为已知限制" | `修复计划.md` 第 5.4 节 | 10 分钟 | 避免偶发 API 慢导致验收失败 |
| 4 | **修正工作量估算**：修复 1 从 4-6h → 5-7h，总工作量从 8-13h → 10-15h | `修复计划.md` 第 6 节 | 5 分钟 | 实际修改点 8 处（非 6 处）+ 测试依赖补充 |

### P2（修复后或集成验证时完成）

| # | 行动 | 改动范围 | 说明 |
|---|------|----------|------|
| 5 | **FM 审查日志增加 `round_label` 字段**：在 `logger.log` 的 `data` 中增加 `round_label`（"第 1 轮"/"最终审查"） | `frost_agent.py` `_fm_review_search_results` 和调用点 | 便于日志查询区分不同轮次的 FM 审查 |
| 6 | **文档说明分层 timeout**：`STEP_BUDGETS` 的 Step 1 timeout=180s 只覆盖 LLM 调用，搜索阶段由 300s 外层 `asyncio.wait_for` 控制 | `修复计划.md` 或 `开发日志.md` | 避免未来开发者误解 timeout 配置 |
| 7 | **评估 Step 3 超时与 Step 1 搜索质量的关联**：钙钛矿 Step 1 FM 审查超时 → 补搜未执行 → Step 3 超时，是否存在因果链 | `开发日志.md` 或 B 组评估 | 如果存在关联，修复 FM 审查后 Step 3 超时可能也会减少 |
| 8 | **`_error_type` 更名**：改为 `_fm_error_type` 降低冲突概率 | `frost_agent.py` `_fm_review_search_results` 和调用方 | 低优先级，当前冲突概率极低 |

---

## 六、已确认的事实与已修正的判断

| 原判断 | 修正 | 依据 |
|--------|------|------|
| 无（首次评估此修复计划） | — | — |

**本次验证的关键事实**：
1. `frost_agent.py` 1301 行，`_fm_review_search_results` 定义在第 327 行（验证：grep 结果）
2. `timeout_seconds=30` 硬编码在第 361 行（验证：代码第 361 行）
3. `logger.log` 在 Step 5（第 1117-1121 行）缺失（验证：grep 结果无 Step 5 的 `llm_raw_response`）
4. `methodology_loader.py` 第 126-130 行 fallback 路径无 print/warning（验证：代码第 126-130 行）
5. checkpoint 文件格式含 `saved_at` 字段（验证：`head -c 500` 输出）
6. `KNOWN_CATEGORIES` 含 `data_gaps_remaining`，不含 `fm_review_skipped`（验证：models.py 第 36-44 行）
7. 测试依赖 `pytest` 未在 `requirements.txt` 中声明（验证：`requirements.txt` 4 行）

---

## 七、留给团队的核心提问

1. **测试是否作为 A 组交付物？** 如果是，需要补充 `pytest` 和 `pytest-asyncio` 依赖，并优化测试耗时。如果不是，测试基础设施可以推迟到 B 组，但修复 1 的正确性需要通过其他方式验证（如手动 mock 测试）。

2. **验收标准是否接受方案 B（0/5 通过但记录偶发超时为已知限制）？** 还是坚持 0/5 的严格标准？如果坚持 0/5，需要确认测试环境的 API 稳定性（如硅基流动在测试时段的响应速度）。

3. **`STEP_BUDGETS` 的 Step 1 timeout 是否调整？** 当前 180s 只覆盖 LLM 调用，搜索阶段由 300s 外层控制。是否接受将 `STEP_BUDGETS` 的 Step 1 timeout 增加为 360s（覆盖整个 Step 1），还是保持分层设计并在文档中说明？

4. **FM 审查日志的 `step_id` 是否增加轮次区分？** 当前 `"1_info_collection_fm_review"` 无法区分第 1 轮和最终审查。是否接受在 `data` 中增加 `round_label` 字段？

---

*评估报告版本：v1.0*  
*评估者：同行评议专家（Kimi）*  
*评估完成时间：2026-06-25*  
*评估类型：代码/实现审计（验证修复计划与实际代码的对齐度）*