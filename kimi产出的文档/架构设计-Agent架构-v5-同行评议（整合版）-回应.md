# 对 v5 同行评议（整合版）的回应

> 版本：v1.0 | 日期：2026-06-18 | 回应对象：`kimi产出的文档/架构设计-Agent架构-v5-同行评议（整合版）.md`

---

## 总体态度

这份整合评议质量很高。两路独立评议交叉验证的方法论值得肯定——3.1 节的接口矛盾确实是硬伤，两路独立识别说明这不是误读。

以下逐项回应，分为"接受"、"部分接受/调整"、"反驳/澄清"三类。

---

## 一、接受的修正（P0 + P1 + P2）

### P0 级（编码前必须解决）

#### 1. 3.1 search.py 接口矛盾 — 接受

**确认**：已验证 [search.py:122](file:///Users/paper/trae_project/行业定义agent/demo/search.py#L122)，实际接口是 `search_with_fallback(industry: str, tavily_api_key: str) -> dict[str, Any]`，内部生成 3 个 query，返回 dict。v5.2 spec 的代码骨架调用 `search_with_fallback(query)` 传入单个字符串、期望返回 list，三重不兼容（参数、语义、返回值）。

**修正方案**：采用评议建议的方案 A——在 `search.py` 中新增 `search_single_query(query: str, tavily_api_key: str) -> list[dict]` 函数，补搜循环调用新函数。

文档声明从"不改 search.py 接口"修正为"**新增** `search_single_query` 函数，**不修改**现有 `search_with_fallback` 接口"。

```python
# search.py 新增（v5.2）

async def search_single_query(query: str, tavily_api_key: str, max_results: int = 5) -> list[dict]:
    """单 query 搜索，供 Step 1 补搜循环调用。

    与 search_with_fallback 不同：传入具体 query 而非行业名，
    返回 list[dict] 而非包装 dict。

    v5.2 新增。
    """
    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=tavily_api_key)
        resp = await client.search(query, search_depth="advanced", max_results=max_results)
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in resp.get("results", [])
        ]
    except Exception as e:
        return [{"title": "搜索失败", "url": "", "content": str(e)}]
```

#### 2. 3.3 load_version glob 模式 bug — 接受

**确认**：已验证 [v5.md:650](file:///Users/paper/trae_project/行业定义agent/架构设计/架构设计-Agent架构-v5.md#L650)，glob 模式 `{safe_name}_{timestamp}_{step_id}_*` 末尾的 `_*` 要求 step_id 后有下划线，但无 request_id 时文件名是 `{step_id}.json`，不匹配。

**修正**：glob 模式从 `{step_id}_*` 改为 `{step_id}*`。

#### 3. 3.5 "最多 2 轮补搜"逻辑冲突 — 接受

**确认**：逻辑分析正确。首轮 3 query + 第 1 轮补搜 2 query = 5，达到 `MAX_TOTAL_QUERIES`，第 2 轮永远不执行。

**修正**：采用方案 A（改描述，保持简单）。将"最多 2 轮补搜，总共 ≤5 个 query"改为"**最多 2 个补搜 query，总共 ≤5 个 query**"。

#### 4. 3.6 STEP4_MAX_TOKENS 不一致 — 确认

**确认**：已查阅 [P0-1 实测报告](file:///Users/paper/trae_project/行业定义agent/开发日志/阶段一-P0-1_P0-3_实测报告.md)，二分查找推荐值是 **10000**。代码 [frost_agent.py:64](file:///Users/paper/trae_project/行业定义agent/demo/frost_agent.py#L64) 默认值仍为 16000，注释说"待二分查找后调整"——二分查找已完成但代码默认值未更新。

**修正**：实现时将代码默认值从 16000 改为 10000。文档已经是 10000，无需修改。

### P1 级

#### 5. 3.2 文档与代码状态偏差 — 接受

**接受**：在文档开头添加"当前实现状态"说明，明确标注所有 v5 组件均为未实现。

#### 6. 3.4 Orchestrator 骨架性质 — 接受

**接受**：骨架是伪代码示意，不是可直接实现的 spec。实际实现保留 v4 的显式逐步调用结构。在文档中标注。

#### 7. 5.5 Step 4 无质量校验 — 接受

**接受**：实现时在 Step 4 后添加最小内容校验（`len(report_text) < 500` 时 raise）。

#### 8. 5.6 同源偏差表述 — 部分接受

**接受**：修正表述。从"不存在同源偏差"改为"审查对象是外部数据，降低了同源偏差风险，但审查者本身仍是 LLM，存在模型认知偏差。阶段三 Model Router 引入后，FM 审查应使用不同模型"。

**补充说明**：用户此前已指出"FM 审的不是 FM 的输出，而是搜索结果"。评议者的反驳更精确——同源偏差的定义不是"审查自己的输出"，而是"同一个 LLM 既当运动员又当裁判"。这个点成立，但实际风险低于"同模型审查同模型输出"，因为搜索结果的质量判断比 LLM 输出的质量判断更客观（有/无信息是事实判断，不是质量判断）。

#### 9. 5.7 or_fallback_result 在生产步骤终止 — 接受

**接受**：当 `or_fallback_result`（result 字段被占位符替代）出现在 Step 1-4（生产步骤）时，终止流程并提示重跑。Step 5 可以继续但标记警告。

#### 10. 5.8 搜索全失败终止 — 接受

**接受**：实现时在搜索全失败后终止流程，不基于空搜索结果生成报告。

#### 11. 5.3 429 限流处理 — 接受

**接受**：在 A 组实现时改进 `call_with_timeout`，区分 429 限流和其他异常，429 读取 `Retry-After` header。

#### 12. 5.4 FM 审查 LLM 异常捕获 — 接受

**接受**：FM 审查的 `llm_call` 添加 `try/except` 捕获 `asyncio.TimeoutError` 和网络异常，异常时记录 `json_parse_fallback` 并跳过补搜。

### P2 级

| # | 评议建议 | 回应 |
|---|---------|------|
| 5.12 | 补搜改并行 | 接受。用 `asyncio.gather` 并行搜索 |
| 5.13 | OutputSafety 版本号上限 | 接受。`max_versions = 100` |
| 5.14 | TokenAudit 汇率环境变量 | 接受。从 `os.getenv("USD_TO_CNY", "7.2")` 读取 |
| 5.15 | Checkpoint 保存 trace_id | 接受。wrapper 增加 `trace_id` 字段 |
| 5.16 | FM 审查纳入超时管理 | 接受。用 `call_with_timeout` 包装，单次超时 30s |

---

## 二、澄清/反驳

### 2.1 成本估算方法（回应 4.1 节）

评议者的粗略估算基于 `max_tokens` 上限 × 单价，得出 Step 4 单步 ¥0.156、总计 ¥0.396。**这个方法严重高估了实际成本**。

**实测数据**（[P0-3 成本审计](file:///Users/paper/trae_project/行业定义agent/开发日志/阶段一-P0-1_P0-3_实测报告.md)，可信度 ★★★★★）：

| 指标 | 评议者估算 | 阶段一实测 |
|------|----------|----------|
| Step 4 completion_tokens | ~16K（按 max_tokens 上限） | 3,357-3,789（远低于上限） |
| 单次运行总费用 | ~¥0.396（~$0.055） | 平均 $0.019/次（3 个行业实测） |
| $0.10 闸门 | "可能守不住" | 实测仅为闸门的 19% |

`max_tokens` 是上限不是实际消耗。DeepSeek-V4-Pro 在 Step 4 实际只生成 ~3,500 tokens（报告长度 5,000-6,000 字符），远低于 10,000-16,000 的上限。用上限估算成本就像用高速公路限速估算通勤时间。

**$0.10 闸门来源**：v3.1 路线图阶段二进入闸门条件，基于项目预算规划。实测 $0.019/次远低于此值。

### 2.2 延迟估算（回应 4.2 节）

评议者说"无端到端延迟估算"。实际上 v3.1 路线图有延迟拆解章节，阶段一实测平均 ~4.5 分钟/次（已记录在进入闸门中）。

FM 审查 ~15s/轮是估算（基于 DeepSeek-V4-Pro 生成 2000 tokens 的经验值），标注为估算而非实测。实现后用实测数据修正。

### 2.3 "当务之急是开始实现"（回应第十一节）

**完全同意**。这份评议完成后，我们立即开始阶段二 A 组的实现。设计文档已经过三轮评议（Kimi 两轮 + 本次整合评议），继续打磨的边际收益递减。

### 2.4 文档语气（回应 3.2 节）

评议者指出文档语气像在描述"增量集成"，容易让协作者误以为组件已存在。这个批评成立——v5 文档是**设计 spec**，不是实现文档。将在文档开头明确标注。

---

## 三、修正项汇总

| # | 修正项 | 优先级 | 涉及文件 | 工作量 |
|---|--------|--------|---------|--------|
| 1 | search.py 新增 `search_single_query` + 文档声明修正 | P0 | search.py + v5.md | 2-4h |
| 2 | load_version glob 模式 `{step_id}_*` → `{step_id}*` | P0 | v5.md | < 1h |
| 3 | "最多 2 轮补搜" → "最多 2 个补搜 query" | P0 | v5.md | < 1h |
| 4 | STEP4_MAX_TOKENS 代码默认值 16000 → 10000 | P0 | frost_agent.py | < 1h |
| 5 | 文档开头添加"当前实现状态" | P1 | v5.md | < 1h |
| 6 | Orchestrator 骨架标注为伪代码 | P1 | v5.md | < 1h |
| 7 | Step 4 添加最小内容校验 | P1 | frost_agent.py | < 1h |
| 8 | 同源偏差表述修正 | P1 | v5.md | < 1h |
| 9 | or_fallback_result 在生产步骤终止 | P1 | frost_agent.py | 2-4h |
| 10 | 搜索全失败终止流程 | P1 | frost_agent.py | < 1h |
| 11 | 429 限流区分处理 | P1 | circuit_breaker.py | 2-4h |
| 12 | FM 审查异常捕获 | P1 | frost_agent.py | < 1h |
| 13 | 补搜改并行 | P2 | frost_agent.py | < 1h |
| 14 | OutputSafety 版本号上限 | P2 | output_safety.py | < 1h |
| 15 | TokenAudit 汇率环境变量 | P2 | token_audit.py | < 1h |
| 16 | Checkpoint 保存 trace_id | P2 | checkpoint.py | < 1h |
| 17 | FM 审查纳入超时管理 | P2 | frost_agent.py | < 1h |

**说明**：#1-4 是文档/spec 层面的修正，在开始编码前完成。#5-17 在编码过程中一并实现。

---

## 四、对评议方法的评价

这份评议的两个做法值得在后续同行评议中保持：

1. **两路独立评议交叉验证**：3.1 节的接口矛盾被两路独立识别，可信度高。单一路径容易遗漏。
2. **区分"确凿矛盾"和"工程担忧"**：评议者在第十二节明确区分了两类发现，避免将推测当作定论。

评议中唯一的方法论问题是**成本估算用 max_tokens 上限而非实测数据**——如果先查阅 P0-3 实测报告，4.1 节的"可能守不住 $0.10 闸门"结论就不会出现。建议后续评议在估算成本时先查阅 `开发日志/` 下的实测数据。

---

*本文档遵循项目规则：逐项回应、区分接受/反驳、修正项含具体文件和工作量。*
