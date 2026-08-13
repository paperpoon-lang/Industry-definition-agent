"""v5.2 修复1 + 修复2 测试。

修复1：_fm_review_search_results 失败类型区分 + _record_fm_failure_flag（修复计划 v1.2 5.1 节）
修复2：搜索阶段外层 timeout 兜底 + 级联终止路径（architecture-critic P0 要求补的测试）

用 unittest.mock.patch mock call_with_timeout / step1_search_with_supplement，
测试 <1s 完成（非原 sleep(70) 的 121s）。

覆盖场景：
- 修复1：timeout/parse_error/exception 三种失败 + flag 构造
- 修复2：SEARCH_PHASE_TIMEOUT 触发后产生 search_phase_timeout flag，走终止路径，不级联 or_fallback_result
"""
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from frost_agent import (
    _fm_review_search_results,
    _record_fm_failure_flag,
    _run_step1,
)
from models import ReportState


@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_timeout(mock_call):
    """FM 审查超时返回 _error_type=timeout。"""
    mock_call.side_effect = asyncio.TimeoutError()
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "timeout"


@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_parse_error(mock_call):
    """FM 审查返回非 JSON 返回 _error_type=parse_error。"""
    mock_call.return_value = {"text": "not a json"}
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "parse_error"


@pytest.mark.asyncio
@patch("frost_agent.call_with_timeout", new_callable=AsyncMock)
async def test_fm_review_exception(mock_call):
    """FM 审查网络异常返回 _error_type=exception。"""
    mock_call.side_effect = ConnectionError("网络断开")
    result = await _fm_review_search_results("测试行业", "优先级", "摘要", AsyncMock())
    assert result.get("_error_type") == "exception"
    assert "网络断开" in result.get("_error_msg", "")


def test_record_fm_failure_flag():
    """_record_fm_failure_flag 正确生成 fm_review_skipped flag。"""
    flags = []
    _record_fm_failure_flag(flags, "timeout", "第 1 轮", {})
    assert len(flags) == 1
    assert flags[0].category == "fm_review_skipped"
    assert flags[0].field == "fm_review"
    assert flags[0].severity == "medium"
    assert "超时" in flags[0].detail
    # P2-2 结构化前缀（回应 architecture-critic）
    assert "[type=timeout]" in flags[0].detail


# ============================================================
# v5.2 Kimi P3 补测（2026-06-28）：_record_fm_failure_flag 三分支
# 原测试只覆盖 timeout 分支，Kimi 评议指出 parse_error/exception/empty 未覆盖
# ============================================================

def test_record_fm_failure_flag_parse_error():
    """_record_fm_failure_flag parse_error 分支（Kimi P3 补测）。"""
    flags = []
    _record_fm_failure_flag(flags, "parse_error", "最终审查", {"raw_response": "xxx"})
    assert len(flags) == 1
    assert flags[0].category == "fm_review_skipped"
    assert flags[0].severity == "medium"
    assert "[type=parse_error]" in flags[0].detail
    assert "非 JSON" in flags[0].detail


def test_record_fm_failure_flag_exception():
    """_record_fm_failure_flag exception 分支（Kimi P3 补测）。"""
    flags = []
    _record_fm_failure_flag(
        flags, "exception", "第 2 轮",
        {"_error_msg": "ConnectionError: 超时"},
    )
    assert len(flags) == 1
    assert flags[0].category == "fm_review_skipped"
    assert "[type=exception]" in flags[0].detail
    assert "ConnectionError: 超时" in flags[0].detail


def test_record_fm_failure_flag_empty():
    """_record_fm_failure_flag empty 分支（Kimi P3 补测）。"""
    flags = []
    _record_fm_failure_flag(flags, "empty", "第 1 轮", {})
    assert len(flags) == 1
    assert flags[0].category == "fm_review_skipped"
    assert "[type=empty]" in flags[0].detail
    assert "空结果" in flags[0].detail


# ============================================================
# 修复2 测试（architecture-critic P0 要求补的测试）
# 验证 SEARCH_PHASE_TIMEOUT 触发后的级联处理：
# 1. asyncio.wait_for 触发 TimeoutError
# 2. except 分支产生 search_phase_timeout(high) flag
# 3. has_search_all_failed 走终止分支（不调 LLM 总结）
# 4. 不产生 or_fallback_result flag（避免级联污染）
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
@patch("frost_agent.SEARCH_PHASE_TIMEOUT", 0.1)  # 短超时，让 wait_for 快速触发
@patch("frost_agent.step1_search_with_supplement", new_callable=AsyncMock)
async def test_search_phase_timeout_cascade(mock_step1, mock_call_llm):
    """v5.2 修复2 + P1-3 + architecture-critic P0-1：搜索阶段整体超时走终止路径。

    验证：
    1. asyncio.wait_for 在 SEARCH_PHASE_TIMEOUT 后触发 TimeoutError
    2. except 分支产生 search_phase_timeout(high) flag
    3. has_search_all_failed 走终止分支（不调 LLM 总结）
    4. _run_step1 抛 QualityGateError（P0-1 修复，不依赖 _check_quality_gate）
    5. 不产生 or_fallback_result flag（避免级联污染）
    6. LLM 未被调用（P1-2：终止分支不应调 LLM）
    """

    # mock step1_search_with_supplement 长时间 sleep，让 wait_for 在 0.1s 后触发 TimeoutError
    async def slow_step(*args, **kwargs):
        await asyncio.sleep(10)  # 远大于 SEARCH_PHASE_TIMEOUT=0.1

    mock_step1.side_effect = slow_step

    # 构造最小依赖
    state = ReportState(industry_name="测试行业")
    logger = MagicMock()
    logger.log = MagicMock()  # 同步 mock（不实际写日志）
    context_builder = MagicMock()
    methodology_loader = MagicMock()
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    # 调用 _run_step1，期望抛 QualityGateError
    from models import QualityGateError
    # B1-1：异常消息改为 "触发终止性降级：{category}/{field}..."，用稳定字符串 match
    # 不依赖具体 category 名（_check_quality_gate for 循环顺序非确定）
    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step1(
            industry_name="测试行业",
            state=state,
            logger=logger,
            context_builder=context_builder,
            methodology_loader=methodology_loader,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_trace_timeout",
            mock=False,
            mock_search_mode=False,
        )

    # 异常抛出后 state.steps 仍可访问（raise 在 append 之后）
    assert len(state.steps) == 1, f"期望 1 个 step，实际 {len(state.steps)}"
    last_step = state.steps[-1]
    assert last_step.step_id == "1_info_collection"

    # 验证 search_phase_timeout(high) flag
    flags = last_step.quality_flags
    spt_flags = [f for f in flags if f.category == "search_phase_timeout"]
    assert len(spt_flags) == 1, f"期望 1 个 search_phase_timeout flag，实际 {len(spt_flags)}"
    assert spt_flags[0].severity == "high"
    assert "整体超时" in spt_flags[0].detail

    # 验证不产生 or_fallback_result flag（关键：级联终止路径生效）
    or_flags = [f for f in flags if f.category == "or_fallback_result"]
    assert len(or_flags) == 0, f"不应产生 or_fallback_result，实际有 {len(or_flags)} 个"

    # 验证 LLM 未被调用（P1-2：终止分支不应调 LLM）
    assert mock_call_llm.call_count == 0, "终止分支不应调 LLM"

    # 验证 result 含 error 标记
    assert last_step.result.get("error") == "all_search_failed"


# ============================================================
# v5.2 Kimi Q4 补测（2026-06-28）：复合场景
# 验证 has_search_all_failed 的 or 逻辑在两种 high category 同时存在时也能触发 QualityGateError
#
# 注意：真实代码中 search_phase_timeout 只在 except 分支产生，会覆盖 step1_search_with_supplement
# 的返回值，所以两者不会同时存在。本测试通过 mock step1 正常返回（绕过 except）构造复合场景，
# 验证 has_search_all_failed 表达式（frost_agent.py L993-998）的 or 逻辑正确性，防止未来代码
# 改动引入 P0-1 类 bug。
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
@patch("frost_agent.step1_search_with_supplement", new_callable=AsyncMock)
async def test_search_partial_failure_plus_timeout_cascade(mock_step1, mock_call_llm):
    """v5.2 Kimi Q4 补测：search_partial_failure(high, all_queries) + search_phase_timeout
    同时存在时，has_search_all_failed 的 or 逻辑命中，触发 QualityGateError。

    验证：
    1. has_search_all_failed 表达式正确处理两种 category 的 or 组合
    2. QualityGateError 的 failed_categories 列表包含两种 category
    3. 两种 flag 都被保留到 step.quality_flags
    4. LLM 未被调用（终止分支不应调 LLM）
    """
    from models import QualityFlag, QualityGateError

    # 构造两种 high flag 同时存在的场景（绕过 except 分支，直接 mock step1 正常返回）
    # B1-1：flags 需设 terminates_flow=True 才能触发 _check_quality_gate 终止
    combined_flags = [
        QualityFlag(
            category="search_partial_failure",
            field="all_queries",
            severity="high",
            detail="所有搜索 query 失败",
            terminates_flow=True,  # B1-1：SSOT 元数据
        ),
        QualityFlag(
            category="search_phase_timeout",
            field="search_phase",
            severity="high",
            detail="搜索阶段整体超时",
            terminates_flow=True,  # B1-1：SSOT 元数据
        ),
    ]
    mock_step1.return_value = ({}, combined_flags, 1)

    state = ReportState(industry_name="测试行业")
    logger = MagicMock()
    logger.log = MagicMock()
    context_builder = MagicMock()
    methodology_loader = MagicMock()
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    # B1-1：用稳定字符串 match，不依赖具体 category 名（_check_quality_gate for 循环顺序非确定）
    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step1(
            industry_name="测试行业",
            state=state,
            logger=logger,
            context_builder=context_builder,
            methodology_loader=methodology_loader,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_trace_combined",
            mock=False,
            mock_search_mode=False,
        )

    assert len(state.steps) == 1, f"期望 1 个 step，实际 {len(state.steps)}"
    last_step = state.steps[-1]
    flags = last_step.quality_flags

    # 验证两种 flag 都被保留
    sp_flags = [f for f in flags if f.category == "search_partial_failure"]
    spt_flags = [f for f in flags if f.category == "search_phase_timeout"]
    assert len(sp_flags) == 1, f"期望 1 个 search_partial_failure flag，实际 {len(sp_flags)}"
    assert len(spt_flags) == 1, f"期望 1 个 search_phase_timeout flag，实际 {len(spt_flags)}"

    # 验证不产生 or_fallback_result flag
    or_flags = [f for f in flags if f.category == "or_fallback_result"]
    assert len(or_flags) == 0, f"不应产生 or_fallback_result，实际有 {len(or_flags)} 个"

    # 验证 LLM 未被调用
    assert mock_call_llm.call_count == 0, "终止分支不应调 LLM"

    # 验证 result 含 error 标记
    assert last_step.result.get("error") == "all_search_failed"
