# 阶段二 A 组修复计划

> 版本：v1.2 | 日期：2026-06-25
> 范围：基于开发日志 v1.2 的问题排查结果，制定 A 组遗留问题的修复计划
> 基线：demo2/ 目录 v5.2 实现（未修复状态）
> v1.2 变更：采纳 Kimi 同行评议部分建议——测试 mock 优化（sleep→patch）、补充 pytest 依赖、日志加 round_label、P95 改最大耗时、新增分层 timeout 说明。反驳 Kimi 的"接受偶发超时"、"STEP_BUDGETS 增到 360s"、"Step 3 因果链假设"（详见第七节反驳说明）

---

## 一、问题分类总览

### 1.1 分类标准

| 类别 | 判定条件 | 处理方式 |
|------|---------|---------|
| **A 组修复** | A 组新引入组件/功能的缺陷，且满足以下任一：① 导致核心功能失效；② 破坏可观测性（日志/审计缺失）；③ 掩盖配置错误 | 本阶段修复 |
| **留到之后阶段** | 设计层面的固有限制，或环境问题（非 A 组代码缺陷） | 记录，后续阶段处理 |

### 1.2 分类结果

| 问题 | 分类 | 理由 |
|------|------|------|
| P2 #4：FM 审查 30s 超时偏短 | **A 组修复** | A 组新功能（搜索补搜循环）的核心配置缺陷，5 个行业中 4 个触发 FM 审查超时（1 个补搜循环完全失效 + 3 个最终审查超时） |
| P2 #5：FM 审查失败原因未区分 | **A 组修复** | 与 #4 配套。当前把 timeout 误记为 json_parse_fallback，且最终审查超时静默无 flag，属于可观测性缺陷 |
| P2 #3：FM 审查 LLM 调用未记日志 | **A 组修复** | FM 审查是 A 组新功能，其 LLM 调用必须可追溯 |
| P2 #2：Step 5 LLM 调用未记日志 | **A 组修复** | 可观测性是 A 组核心目标（SessionEventLog），Step 5 调用缺失导致 LLM 调用次数审计不完整 |
| P2 #1：MethodologyLoader fallback 静默 | **A 组修复** | A 组新组件 MethodologyLoader 的缺陷，静默掩盖配置错误违背"不确定就说不知道"原则（项目规则 2） |
| **新增：搜索阶段无外层 timeout** | **A 组修复** | 修复 #4 后 FM 审查 30s→60s，搜索阶段最坏 258s 无外层保护，需补兜底 |
| 问题 6：Step 3 偶发超时（API 慢） | **留到之后阶段** | 根因是硅基流动 API 响应慢，非 A 组代码缺陷。建议在 B 组评估超时策略时一并处理 |
| 已知限制 1：FM 审查模型认知偏差 | **留到之后阶段** | 设计层面的固有限制，FM 审查者本身是 LLM，无法消除 |
| 已知限制 2：补搜 query 质量依赖 FM | **留到之后阶段** | 设计层面的固有限制，需引入外部知识源才能缓解 |
| 问题 8：429 限流未实测 | **无需修复** | 代码逻辑正确（agent-code-validator 验证 7 个子测试全过），仅未自然触发，非 bug |

---

## 二、A 组修复方案

### 修复顺序

按依赖关系和影响范围排序：

1. **P2 #4 + P2 #5 + P2 #3**（合并修改 `_fm_review_search_results` 函数）→ 最优先，核心功能 + 可观测性
2. **搜索阶段外层 timeout**（依赖 #4 完成）→ 配合 #4 的超时调整
3. **P2 #2**（Step 5 记日志）→ 独立修改
4. **P2 #1**（MethodologyLoader warning）→ 独立修改

> 注：#4/#5/#3 + 搜索阶段 timeout 都涉及 `_fm_review_search_results` 和 `step1_search_with_supplement`，合并为一次修改避免重复返工。

---

### 修复 1：P2 #4 + P2 #5 + P2 #3 — FM 审查超时 + 失败区分 + 日志记录（合并修改）

**问题**：
- P2 #4：FM 审查 `timeout_seconds=30` 偏短，5 个行业中 4 个触发超时
- P2 #5：`_fm_review_search_results` 返回 `{}` 时统一记为 `json_parse_fallback`，且**最终审查（line 512-524）超时静默无 flag**（3/5 行业发生）
- P2 #3：FM 审查 LLM 调用未记入 SessionLog

**文件**：
- [demo2/models.py:36-44](file:///Users/paper/trae_project/行业定义agent/demo2/models.py#L36)（KNOWN_CATEGORIES + CATEGORY_DEFAULT_SEVERITY）
- [demo2/frost_agent.py:327-375](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L327)（`_fm_review_search_results` 函数）
- [demo2/frost_agent.py:463-470](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L463)（循环内调用方 flag 记录）
- [demo2/frost_agent.py:512-524](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L512)（**最终审查 flag 记录——必须同步修改**）
- [demo2/frost_agent.py:378-384](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L378)（`step1_search_with_supplement` 函数签名）
- [demo2/frost_agent.py:889](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L889)（`_run_step1` 调用 `step1_search_with_supplement`）

**共 6 处修改**（非原文档的 3 处）。

#### 步骤 1：models.py 新增 `fm_review_skipped` category

```python
# models.py KNOWN_CATEGORIES 新增（不复用 timeout_retry，因其语义是"超时后重试成功"）
KNOWN_CATEGORIES: set[str] = {
    "llm_empty_field",
    "search_partial_failure",
    "json_parse_fallback",
    "or_fallback_result",
    "or_fallback_reasoning",
    "timeout_retry",
    "data_gaps_remaining",
    "fm_review_skipped",  # v5.2 修复：FM 审查失败（超时/解析异常/网络异常）
}

# CATEGORY_DEFAULT_SEVERITY 新增
CATEGORY_DEFAULT_SEVERITY: dict[str, str] = {
    # ... 现有映射 ...
    "fm_review_skipped": "medium",  # v5.2 修复
}
```

> 不复用 `timeout_retry`（severity=low，语义是"超时后重试成功"）或 `llm_call_failed`（不存在于 KNOWN_CATEGORIES）。新增专用 category 语义清晰且避免 validator 冲突。

#### 步骤 2：frost_agent.py 超时阈值 30s → 环境变量（默认 60s）

```python
# 模块级常量（frost_agent.py 顶部）
import os
_FM_REVIEW_TIMEOUT = float(os.getenv("FM_REVIEW_TIMEOUT", "60"))  # v5.2: 30s→60s

# _fm_review_search_results 内部（line 361）
timeout_seconds=_FM_REVIEW_TIMEOUT,
```

#### 步骤 3：frost_agent.py `_fm_review_search_results` 区分失败类型 + 记日志

```python
# 修复后函数签名（增加 logger 参数）
async def _fm_review_search_results(
    industry_name: str,
    methodology_info_priority: str,
    search_results_summary: str,
    llm_call_fn: Callable,
    logger: Optional["SessionEventLog"] = None,  # v5.2 修复 P2 #3
    round_label: str = "",  # v5.2 修复 P2 #5：用于日志标识（如"第 1 轮"/"最终审查"）
) -> dict[str, Any]:
    # ...
    try:
        result = await call_with_timeout(
            lambda: llm_call_fn(...),
            timeout_seconds=_FM_REVIEW_TIMEOUT,
            max_retries=1,
        )
        # 修复 P2 #3：记录 FM 审查的 LLM 调用
        if logger is not None:
            text = result.get("text", "") if isinstance(result, dict) else str(result)
            logger.log("llm_raw_response", {
                "step_id": "1_info_collection_fm_review",
                "round_label": round_label,  # v1.2 新增：区分"第 1 轮"/"最终审查"，便于日志查询
                "text_preview": text[:1000],
            })
        # ... JSON 解析 ...
        return {"data_gaps": ..., "suggested_queries": ...}
    except asyncio.TimeoutError:
        print(f"  [FM 审查超时] {round_label}（timeout={_FM_REVIEW_TIMEOUT}s），跳过")
        return {"_error_type": "timeout"}
    except json.JSONDecodeError as e:
        print(f"  [FM 审查 JSON 解析失败] {round_label}：{e}")
        return {"_error_type": "parse_error"}
    except Exception as e:
        print(f"  [FM 审查异常] {round_label} {type(e).__name__}: {e}")
        return {"_error_type": "exception", "_error_msg": str(e)}
```

#### 步骤 4：抽公共辅助函数处理失败 flag（循环内 + 最终审查复用）

```python
def _record_fm_failure_flag(
    quality_flags: list,
    error_type: str,
    round_label: str,
    fm_result: dict,
) -> None:
    """v5.2 修复 P2 #5：统一记录 FM 审查失败 flag（循环内 + 最终审查复用）。"""
    detail_map = {
        "timeout": f"FM 审查{round_label}超时（{_FM_REVIEW_TIMEOUT}s）",
        "parse_error": f"FM 审查{round_label}返回非 JSON",
        "exception": f"FM 审查{round_label}异常：{fm_result.get('_error_msg', '')}",
        "empty": f"FM 审查{round_label}返回空结果",
    }
    quality_flags.append(QualityFlag(
        category="fm_review_skipped",  # 统一用新增 category
        field="fm_review",
        severity="medium",
        detail=detail_map.get(error_type, "未知错误"),
    ))
```

#### 步骤 5：循环内调用方修改（line 463-470）

```python
# 修复前
if not fm_result:
    quality_flags.append(QualityFlag(category="json_parse_fallback", ...))
    break

# 修复后
if not fm_result or "_error_type" in fm_result:
    error_type = fm_result.get("_error_type", "empty") if fm_result else "empty"
    _record_fm_failure_flag(quality_flags, error_type, f"第 {round_num + 1} 轮", fm_result)
    break
```

#### 步骤 6：最终审查修改（line 512-524）— 关键遗漏补齐

```python
# 修复前（line 512-524）：fm_result 为空时静默跳过
if fm_result and fm_result.get("data_gaps"):
    quality_flags.append(QualityFlag(category="data_gaps_remaining", ...))
    print(f"  [FM 最终审查] 补搜后仍有缺口")
else:
    print(f"  [FM 最终审查] 补搜后无缺口")

# 修复后：区分失败和成功
if fm_result and "_error_type" in fm_result:
    # 最终审查失败（超时/异常）
    _record_fm_failure_flag(quality_flags, fm_result["_error_type"], "最终审查", fm_result)
    print(f"  [FM 最终审查] 失败（{fm_result['_error_type']}），缺口状态未知")
elif fm_result and fm_result.get("data_gaps"):
    quality_flags.append(QualityFlag(category="data_gaps_remaining", ...))
    print(f"  [FM 最终审查] 补搜后仍有缺口")
else:
    print(f"  [FM 最终审查] 补搜后无缺口")
```

#### 步骤 7：`step1_search_with_supplement` 签名 + 调用点

```python
# step1_search_with_supplement 签名增加 logger 参数
async def step1_search_with_supplement(
    industry_name: str,
    tavily_api_key: str,
    methodology_loader,
    llm_call_fn: Callable,
    mock_search_mode: bool = False,
    logger: Optional["SessionEventLog"] = None,  # v5.2 修复 P2 #3
) -> tuple[...]:
    # ...
    # 2 处 _fm_review_search_results 调用传入 logger 和 round_label
    fm_result = await _fm_review_search_results(
        ..., logger=logger, round_label=f"第 {round_num + 1} 轮",
    )
    # ...
    fm_result = await _fm_review_search_results(
        ..., logger=logger, round_label="最终审查",
    )

# _run_step1 调用 step1_search_with_supplement 时传入 logger（line 889）
search_results, search_quality_flags, error_count = await step1_search_with_supplement(
    ...,
    logger=logger,  # 新增
)
```

**工作量**：4-6h（6 处修改 + 测试，非原估算的 3-5h）

**优先级**：最高（核心功能 + 可观测性）

**验证方式**：
1. 构造 mock LLM 模拟 timeout/parse_error/exception 三种场景，验证 `fm_review_skipped` flag 正确生成
2. 跑一个真实行业，检查 JSONL 日志含 `step_id: "1_info_collection_fm_review"` 事件
3. 检查最终审查超时时不再静默，产生 `fm_review_skipped` flag

---

### 修复 2：搜索阶段外层 timeout 兜底（新增）

**问题**：修复 1 将 FM 审查超时从 30s→60s 后，`max_retries=1` 意味着单次 FM 审查最坏 60+1+60=121s。Step 1 补搜循环有 2 次 FM 审查（循环内 + 最终审查），最坏：首轮搜索 ~8s + FM1 121s + 补搜 ~8s + FM2 121s = **258s**。而 `step1_search_with_supplement` **没有外层 timeout 包裹**（STEP_BUDGETS 的 180s 只作用于 LLM summary，不包裹搜索阶段）。

**文件**：[demo2/frost_agent.py:378](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L378)（`step1_search_with_supplement` 函数）

**修复方案**：给 `step1_search_with_supplement` 加外层 `asyncio.wait_for` 兜底。

```python
# 在 _run_step1 中包裹 step1_search_with_supplement（line 889）
SEARCH_PHASE_TIMEOUT = 300  # v5.2 修复：搜索阶段外层兜底 5 分钟

try:
    search_results, search_quality_flags, error_count = await asyncio.wait_for(
        step1_search_with_supplement(..., logger=logger),
        timeout=SEARCH_PHASE_TIMEOUT,
    )
except asyncio.TimeoutError:
    search_results = {}
    search_quality_flags = [QualityFlag(
        category="timeout_retry",
        field="search_phase",
        severity="high",  # 显式覆盖为 high
        detail=f"搜索阶段整体超时（{SEARCH_PHASE_TIMEOUT}s），[severity-overridden]",
    )]
    error_count = 1
    print(f"  [搜索阶段超时] 整体 {SEARCH_PHASE_TIMEOUT}s 兜底触发")
```

> 注：`timeout_retry` 默认 severity=low，这里显式覆盖为 high 并加 `[severity-overridden]` 标记（通过 models.py validator 要求），因为搜索阶段整体超时是严重故障。

**工作量**：1-2h

**优先级**：P1（防止修复 1 后出现无保护的长时阻塞）

**验证方式**：mock LLM 每次 sleep 70s，验证 300s 后触发外层 timeout 并产生 high severity flag

---

### 修复 3：P2 #2 — Step 5 LLM 调用记入 SessionLog

**问题**：`_run_step5` 通过 `evaluator.evaluate()` 调用 LLM，但未记入 SessionLog，导致 LLM 调用次数审计不完整。

**文件**：[demo2/frost_agent.py:1117-1121](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L1117)

**修复方案**：

```python
# 修复后：在 evaluate 调用后记录
eval_result = await call_with_timeout(
    lambda: evaluate(report_to_check, industry_name, _llm_call_fn),
    timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
    max_retries=STEP_BUDGETS[step_id].max_retries,
)
# 修复 P2 #2：记录 Step 5 的 LLM 调用
logger.log("llm_raw_response", {
    "step_id": step_id,
    "text_preview": json.dumps(eval_result, ensure_ascii=False)[:1000],
})
```

**工作量**：< 1h

**优先级**：P2

**验证方式**：跑一个行业，检查 JSONL 日志含 Step 5 的 `llm_raw_response` 事件（应 5 个，非 4 个）

---

### 修复 4：P2 #1 — MethodologyLoader v4 fallback 打印 warning

**问题**：指向不存在的目录时静默回退到 v4 单文件，掩盖配置错误。

**文件**：[demo2/methodology_loader.py:126-131](file:///Users/paper/trae_project/行业定义agent/demo2/methodology_loader.py#L126)

**修复方案**：fallback 时打印 warning + 可选严格模式。

```python
# 修复后
if not path.exists():
    v4_path = Path(__file__).parent / "方法论-v2.md"
    if v4_path.exists():
        # v5.2 修复 P2 #1：打印 warning，不再静默
        print(f"  [MethodologyLoader 警告] 指定目录 {self.dir} 下未找到 {fallback_file}，"
              f"已回退到 v4 单文件模式 {v4_path}。请检查 methodology_dir 配置。")
        # 可选严格模式：环境变量 METHODOLOGY_STRICT=true 时硬失败
        if os.getenv("METHODOLOGY_STRICT") == "true":
            raise FileNotFoundError(
                f"严格模式：指定目录 {self.dir} 下未找到 {fallback_file}，"
                f"且 METHODOLOGY_STRICT=true，拒绝回退。"
            )
        path = v4_path
        self._v4_single_file_path = v4_path
    else:
        raise FileNotFoundError(...)
```

> 注：统一用 `print`（与该文件 line 111、line 156 现有风格一致），不用 `warnings.warn`（避免批量场景下被 warning filter 去重）。

**工作量**：< 1h

**优先级**：P2

**验证方式**：构造不存在的目录，验证 print 输出 + 不崩溃；设 `METHODOLOGY_STRICT=true` 验证 raise

---

## 三、留到之后阶段的问题

### 3.1 留到 B 组

| 问题 | 原因 | B 组处理方式 |
|------|------|-------------|
| 问题 6：Step 3 偶发超时（API 慢） | 根因是硅基流动 API 响应慢，非 A 组代码缺陷 | B 组评估 `call_with_timeout` 增强时，一并评估是否调整 Step 3 超时 60s→90s 或增加重试次数 |

### 3.2 留到 D 组（阶段三）或长期限制

| 问题 | 原因 | 处理方式 |
|------|------|---------|
| 已知限制 1：FM 审查模型认知偏差 | 设计层面固有限制，无法消除 | 长期限制，D 组如引入多模型交叉验证可部分缓解 |
| 已知限制 2：补搜 query 质量依赖 FM | 设计层面固有限制，需引入外部知识源才能缓解 | 长期限制，D 组评估 |

### 3.3 无需修复

| 问题 | 原因 |
|------|------|
| 问题 8：429 限流未实测 | 代码逻辑正确（agent-code-validator 验证通过），仅未自然触发，非 bug |

---

## 四、工程视角分析（按项目规则 4）

### 4.1 成本估算

修复后重跑 5 行业做集成验证：
- 开发日志 v1.2 数据：4 个成功行业单次成本 ¥0.163-0.178，平均约 ¥0.17/行业
- 5 行业 × ¥0.17 ≈ **¥0.85（约 $0.12）**
- 注意：FM 审查修复后补搜循环会真正执行（之前 4/5 超时失效），补搜 2 query 会增加 Tavily 调用和 Step 1 prompt token，单行业成本可能从 ¥0.17 上升到约 ¥0.20-0.22（待实测）
- 钙钛矿可能仍因 Step 3 超时失败（非本次修复范围），实际有效验证 4 行业 ≈ ¥0.68-0.88

### 4.2 延迟分析（关键）

修复 1（FM 超时 30s→60s）后的最坏时延：

| 阶段 | 最坏耗时 | 说明 |
|------|---------|------|
| 首轮搜索 | ~8s | 3 个 query 并行 |
| FM 审查第 1 轮 | 121s | 60s × 2 次 + 1s 退避 |
| 补搜 | ~8s | 2 个 query 并行 |
| FM 最终审查 | 121s | 60s × 2 次 + 1s 退避 |
| **搜索阶段合计** | **258s** | **修复 2 的外层 timeout 300s 可兜底** |
| LLM summary | 180s × 3 | STEP_BUDGETS 的 180s × max_retries=2 |
| **Step 1 最坏** | **~798s（13 分钟）** | 搜索 258s + LLM 540s |

> 风险：13 分钟的最坏时延较长，但属可接受范围（单次行业定义报告生成非实时任务）。修复 2 的 300s 外层 timeout 防止搜索阶段无限阻塞。

### 4.3 恢复机制（回滚方案）

1. 修复前打 git tag：`git tag demo2-v5.2-pre-fix`
2. 修复分 2 个 commit：
   - Commit 1：修复 1 + 修复 2（`_fm_review_search_results` + `step1_search_with_supplement` + models.py）
   - Commit 2：修复 3 + 修复 4（Step 5 日志 + MethodologyLoader）
3. 若集成验证失败：`git reset --hard demo2-v5.2-pre-fix` 完全回退

### 4.4 并发

本阶段串行执行，不涉及并发改造。（开发日志 5.6 节明确"串行运行避免 API 限流"）

### 4.5 错误处理

| 场景 | 处理方式 |
|------|---------|
| FM 审查超时 | 记录 `fm_review_skipped` flag，跳过补搜，流程继续 |
| FM 审查 JSON 解析失败 | 同上 |
| FM 审查网络异常 | 同上 |
| 搜索阶段整体超时（300s） | 记录 `timeout_retry(high)` flag，search_results 为空，后续触发 search_partial_failure |
| MethodologyLoader fallback | 打印 warning + 可选严格模式 raise |
| 修复引入回归 | git reset 回滚到 pre-fix tag |

---

## 五、验证计划

### 5.1 测试基础设施（新增）

> demo2/ 目录当前无测试文件。agent-code-validator 的验证是临时生成的，无法重复执行。需落地持久化测试。
>
> v1.2 修正（Kimi 评议采纳）：① 用 `unittest.mock.patch` mock `call_with_timeout` 直接抛异常，测试 <1s 完成（原 `sleep(70)` 方案耗时 121s）；② 补充 `pytest` 和 `pytest-asyncio` 依赖到 requirements.txt（原遗漏）。

**依赖补充**（[demo2/requirements.txt](file:///Users/paper/trae_project/行业定义agent/demo2/requirements.txt)）：

```text
# v1.2 新增：测试依赖
pytest>=7.0
pytest-asyncio>=0.21.0
```

**测试代码**（`demo2/tests/test_fm_review.py`）：

```python
# demo2/tests/test_fm_review.py
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from frost_agent import _fm_review_search_results, _record_fm_failure_flag

# v1.2: mock call_with_timeout 直接抛异常，测试 <1s 完成（非原 sleep(70) 的 121s）

@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_timeout(mock_call):
    """FM 审查超时返回 _error_type=timeout"""
    mock_call.side_effect = asyncio.TimeoutError()
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "timeout"

@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_parse_error(mock_call):
    """FM 审查返回非 JSON 返回 _error_type=parse_error"""
    mock_call.return_value = {"text": "not a json"}
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "parse_error"

@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_exception(mock_call):
    """FM 审查网络异常返回 _error_type=exception"""
    mock_call.side_effect = ConnectionError("网络断开")
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "exception"

def test_record_fm_failure_flag():
    """_record_fm_failure_flag 正确生成 fm_review_skipped flag"""
    flags = []
    _record_fm_failure_flag(flags, "timeout", "第 1 轮", {})
    assert len(flags) == 1
    assert flags[0].category == "fm_review_skipped"
    assert "超时" in flags[0].detail
```

**工作量**：3-4h（v1.2 修正：含 pytest-asyncio 配置 + mock 设计 + 依赖补充，原估算 2-3h 偏低）

**优先级**：P1（无测试则修复 1 的正确性无法保证）

### 5.2 单元验证

每个修复完成后，单独验证：

| 修复 | 验证方式 |
|------|---------|
| 修复 1（P2 #4/#5/#3） | 运行 test_fm_review.py 的 3 个 mock 测试 |
| 修复 2（外层 timeout） | mock LLM 每次 sleep 70s，验证 300s 后触发外层 timeout |
| 修复 3（P2 #2） | 跑一个行业，检查 JSONL 日志含 Step 5 的 `llm_raw_response` 事件 |
| 修复 4（P2 #1） | 构造不存在的目录，验证 print 输出 + 不崩溃 |

### 5.3 集成验证

全部修复完成后：

1. **重跑 5 个行业**（钙钛矿、细胞培养肉、室内垂直农业、脑机接口、固态电池）
2. **调用 agent-code-validator** 验证 P2 #1-#5 + 新增修复全部通过
3. **更新开发日志到 v1.3**

### 5.4 验收标准（v1.2 调整）

> v1.2 修正（Kimi 评议部分采纳）：P95 在 5 样本下无法计算，改为"最大耗时 ≤ 60s"。
>
> v1.2 反驳（Kimi 评议"接受偶发超时为已知限制"）：不接受。超时必须分析原因——环境故障（余额/网络）不算修复失败；API 响应慢（60s 不够）算修复不充分，需调高 timeout。区分两类超时比无原则"接受偶发"更负责任。

| 标准 | 达成条件 |
|------|---------|
| FM 审查超时修复 | 4 个行业（排除钙钛矿 Step 3 超时，非本修复范围）FM 审查超时数 = **0**；且 FM 审查**最大耗时 ≤ 60s**（5 样本无法计算 P95，用最大值替代）。若出现超时：环境故障（余额不足/网络中断）不算修复失败；API 响应慢（60s 不够）算修复不充分，需调高 `FM_REVIEW_TIMEOUT` |
| FM 失败原因区分 | timeout/parse_error/exception 三种场景 quality_flag category 均为 `fm_review_skipped`，detail 正确区分。**最终审查失败也产生 flag**（不再静默） |
| FM 审查记日志 | JSONL 日志含 `step_id: "1_info_collection_fm_review"` 事件，且 `data.round_label` 字段区分轮次（v1.2 新增） |
| Step 5 记日志 | JSONL 日志含 Step 5 的 `llm_raw_response` 事件（5 个，非 4 个） |
| 搜索阶段外层 timeout | mock 测试验证 300s 触发外层 timeout + high severity flag |
| MethodologyLoader warning | 指向不存在目录时输出 print 警告；`METHODOLOGY_STRICT=true` 时 raise |
| **无回归（过程指标）** | ① 4 个原本成功的行业，补搜循环必须真正执行（query_count 从 3 增到 5）；② 报告字符数不劣化（4320-5472 区间）；③ quality_flag 数量可增加（记录了之前静默的失败），但不应出现 `or_fallback_result(high)` |

> 删除原 v1.0 的"≤ 1/5"退路——5 样本里允许 1 个超时无统计意义，且 20% 超时率对基础设施组件不可接受。v1.2 进一步明确：超时原因必须分类，不能笼统"接受偶发"。

---

## 六、工作量估算

| 修复 | 工作量 | 优先级 |
|------|--------|--------|
| 修复 1（P2 #4/#5/#3 合并） | 4-6h | 最高 |
| 修复 2（搜索阶段外层 timeout） | 1-2h | P1 |
| 修复 3（P2 #2 Step 5 记日志） | < 1h | P2 |
| 修复 4（P2 #1 MethodologyLoader） | < 1h | P2 |
| 测试基础设施（test_fm_review.py + pytest 依赖） | 3-4h | P1 |
| **合计** | **9-14h** | |

> v1.2 变更：测试基础设施从 2-3h 上调至 3-4h（含 pytest 依赖补充 + mock 设计），总计从 8-13h 上调至 9-14h。

---

## 七、对 Kimi 同行评议的反驳说明（v1.2 新增）

> 本节记录对 Kimi 同行评议报告中**未采纳**建议的反驳理由，确保决策可追溯。

### 7.1 反驳：不"接受偶发超时为已知限制"（Kimi Q1 方案 B / P2 行动 #3）

**Kimi 论点**：5 样本统计意义不足，偶发 API 慢可能导致验收失败，建议"0/5 通过但记录偶发超时为已知限制"。

**反驳**：Kimi 把两类不同的超时混为一谈。修复 P2 #4 的核心目标是"FM 审查 30s 超时 → 60s 够用"。如果修复后仍因 API 响应慢超时，说明 60s 不够，需调高——这恰恰是验收要发现的，而不是"接受偶发"糊弄过去。正确做法：超时必须分析原因，环境故障（余额/网络）不算修复失败，API 响应慢算修复不充分。已在 5.4 验收标准中明确。

### 7.2 反驳：不调整 STEP_BUDGETS 到 360s（Kimi Q4 方案 B）

**Kimi 论点**：或将 `STEP_BUDGETS["1_info_collection"].timeout_seconds` 从 180s 增到 360s 覆盖整个 Step 1。

**反驳**：`STEP_BUDGETS` 的 `timeout_seconds` 通过 `call_with_timeout` 作用于**单次 LLM 调用**，不是步骤整体预算。增到 360s 会让 LLM summary 调用在 API 卡死时等 360s × 3 次 = 18 分钟才报错，**降低**可靠性。Kimi 把"步骤预算"和"单次 LLM 调用超时"混为一谈。保持分层（搜索 300s 外层 + LLM 180s 内层）是正确的。

### 7.3 反驳：不假设 Step 3 超时与 Step 1 FM 审查的因果链（Kimi P3 风险 #6）

**Kimi 论点**：钙钛矿 FM 审查超时 → 补搜未执行 → 信息不足 → Step 3 prompt 更复杂 → Step 3 超时。

**反驳**：因果链假设缺乏证据，且与已确认根因矛盾。开发日志 v1.2 明确"钙钛矿 Step 3 超时根因是硅基流动 API 响应慢——3 次调用都在 60s 内未返回"。如果"信息不足导致超时"，Step 3 应该是返回质量差，而不是超时——超时是时间问题，与信息充分性无直接关联。观察钙钛矿修复后 Step 3 行为有价值，但不应预设因果链存在，这会误导后续分析方向。

### 7.4 不采纳：`_error_type` 不改名（Kimi P3 风险 #8 / P2 行动 #8）

**Kimi 论点**：`_error_type` 可能与 LLM 返回字段冲突，建议改为 `_fm_error_type`。

**判断**：风险被高估。`_fm_review_search_results` 返回的 dict 只有两种状态：正常时含 `data_gaps`/`suggested_queries`，异常时含 `_error_type`。调用方先检查 `"_error_type" in fm_result`，LLM 返回的 JSON 不会生成以下划线开头的字段。改名收益低，不改不影响正确性。

### 7.5 补充说明：分层 timeout 设计（采纳 Kimi Q4 方案 A）

> Kimi 评议指出 `STEP_BUDGETS` 的 180s 只覆盖 LLM 调用，不覆盖搜索阶段，两个独立 timeout 机制需要文档说明。采纳此建议（方案 A：分层+文档），不采纳方案 B（增到 360s）。

修复后 Step 1 的 timeout 分层：

```
Step 1 完整执行
├── 搜索阶段（step1_search_with_supplement）
│   ├── 首轮 3 query 并行搜索
│   ├── FM 审查第 1 轮（call_with_timeout, timeout=FM_REVIEW_TIMEOUT=60s, max_retries=1）
│   ├── 补搜 2 query 并行搜索
│   └── FM 最终审查（call_with_timeout, timeout=FM_REVIEW_TIMEOUT=60s, max_retries=1）
│   └── 外层兜底：asyncio.wait_for(timeout=SEARCH_PHASE_TIMEOUT=300s)  ← 修复 2
│
└── LLM 总结阶段（call_llm）
    └── call_with_timeout(timeout=STEP_BUDGETS["1_info_collection"].timeout_seconds=180s, max_retries=2)
```

| timeout 层级 | 值 | 作用范围 | 配置位置 |
|-------------|-----|---------|---------|
| FM 审查单次 | 60s（可配置） | 单次 FM 审查的 LLM 调用 | `FM_REVIEW_TIMEOUT` 环境变量 |
| 搜索阶段外层 | 300s | 整个搜索阶段（搜索+FM+补搜+最终审查） | `SEARCH_PHASE_TIMEOUT` 常量（修复 2） |
| LLM 总结 | 180s | Step 1 的 LLM summary 调用 | `STEP_BUDGETS["1_info_collection"].timeout_seconds` |

**设计理由**：分层 timeout 比单一 timeout 更精确——搜索阶段和 LLM 调用是不同的故障模式，应分别控制。`STEP_BUDGETS` 的 180s **不调整**，因为它只作用于 LLM 调用。

---

*修复计划版本：v1.2 | 日期：2026-06-25 | 基于 demo2 v5.2 + 开发日志 v1.2 + ai-architecture-fact-checker + architecture-critic + Kimi 同行评议（部分采纳，部分反驳，详见第七节）*
*v1.2 变更：测试 mock 优化、补充 pytest 依赖、日志加 round_label、P95 改最大耗时、新增分层 timeout 说明（第七节）、反驳 Kimi 的"接受偶发超时"/"STEP_BUDGETS 增到 360s"/"Step 3 因果链假设"*
*v1.1 变更：根据 ai-architecture-fact-checker + architecture-critic 审查意见修正——修复 2 重写（新增 fm_review_skipped category）、扩展最终审查失败处理、新增搜索阶段外层 timeout、收紧验收标准、补充工程视角分析*
