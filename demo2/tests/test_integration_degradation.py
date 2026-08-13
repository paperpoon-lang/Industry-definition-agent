"""B2-2：降级路径集成测试。

验证 search_phase_timeout 触发后的组件间协同：
- JSONL 日志正确记录 search_done + step_complete(all_search_failed) 事件
- Checkpoint 文件被写入且状态为 all_search_failed
- TokenAudit 正确处理 fail path 的 token_usage=None

补充测试（采纳 architecture-critic P2 风险2）：
- Step 2/3/4 的 or_fallback_result 终止路径有专门 mock 测试覆盖

依赖 B1-1：测试构造的 QualityFlag 需设 terminates_flow=True 才能触发 _check_quality_gate 终止。
"""
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from frost_agent import _run_step1, _run_step
from models import ReportState, QualityFlag, QualityGateError


# ============================================================
# 集成测试 1：JSONL 联动验证
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
@patch("frost_agent.step1_search_with_supplement", new_callable=AsyncMock)
async def test_timeout_jsonl_integration(mock_step1, mock_call_llm, tmp_path):
    """Step 1 超时后 JSONL 正确记录 search_done + step_complete(all_search_failed) 事件。

    验证点：
    1. SessionEventLog 写入 tmp_path/test_trace.jsonl
    2. JSONL 含 search_done 事件且 quality_flags_count >= 1
    3. JSONL 含 step_complete 事件且 status == "all_search_failed"

    注意：search_phase_timeout 字符串本身不在 JSONL 中（SessionEventLog 只记显式 logger.log()
    调用，且 search_done 事件只记 quality_flags_count 计数，不序列化 flag 本身）。
    """
    from harness.session_log import SessionEventLog

    # 构造搜索阶段超时的 flags（terminates_flow=True, B1-1 后）
    timeout_flags = [QualityFlag(
        category="search_phase_timeout",
        field="search_phase",
        severity="high",
        detail="搜索阶段整体超时（300s），放弃搜索",
        terminates_flow=True,
    )]
    mock_step1.return_value = ({}, timeout_flags, 1)

    # 使用真实 SessionEventLog 写入 tmp_path
    logger = SessionEventLog("测试行业", trace_id="test_trace", log_dir=str(tmp_path))
    state = ReportState(industry_name="测试行业")
    context_builder = MagicMock()
    methodology_loader = MagicMock()
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    # 触发 _run_step1，期望抛 QualityGateError
    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step1(
            industry_name="测试行业",
            state=state,
            logger=logger,
            context_builder=context_builder,
            methodology_loader=methodology_loader,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_trace",
            mock=False,
            mock_search_mode=False,
        )

    # 验证 JSONL 文件
    jsonl_path = tmp_path / "test_trace.jsonl"
    assert jsonl_path.exists(), "JSONL 文件应被创建"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    # 验证 search_done 事件存在且 quality_flags_count >= 1
    search_done_events = [e for e in events if e.get("event_type") == "search_done"]
    assert len(search_done_events) >= 1, "应含 search_done 事件"
    assert search_done_events[0]["data"]["quality_flags_count"] >= 1, "quality_flags_count 应 >= 1"

    # 验证 step_complete 事件含 all_search_failed 状态
    complete_events = [e for e in events if e.get("event_type") == "step_complete"]
    assert any(
        e.get("data", {}).get("status") == "all_search_failed"
        for e in complete_events
    ), "step_complete 事件应含 status=all_search_failed"


# ============================================================
# 集成测试 2：Checkpoint 联动验证
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
@patch("frost_agent.step1_search_with_supplement", new_callable=AsyncMock)
async def test_timeout_checkpoint_integration(mock_step1, mock_call_llm, tmp_path):
    """Step 1 超时后 checkpoint 正确写入 all_search_failed 状态。

    验证点：
    1. Checkpoint 文件被写入 tmp_path/checkpoints/
    2. checkpoint 内 state.steps[-1].result["error"] == "all_search_failed"
    3. checkpoint 内 state.steps[-1].quality_flags 含 search_phase_timeout flag
    """
    from harness.checkpoint import CheckpointManager

    timeout_flags = [QualityFlag(
        category="search_phase_timeout",
        field="search_phase",
        severity="high",
        detail="超时",
        terminates_flow=True,
    )]
    mock_step1.return_value = ({}, timeout_flags, 1)

    # 使用真实 CheckpointManager 写入 tmp_path
    checkpoint_mgr = CheckpointManager(checkpoint_dir=str(tmp_path / "checkpoints"))
    logger = MagicMock()
    logger.log = MagicMock()
    context_builder = MagicMock()
    methodology_loader = MagicMock()
    state = ReportState(industry_name="测试行业")

    # 触发 _run_step1，期望抛 QualityGateError
    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step1(
            industry_name="测试行业",
            state=state,
            logger=logger,
            context_builder=context_builder,
            methodology_loader=methodology_loader,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_trace_ckpt",
            mock=False,
            mock_search_mode=False,
        )

    # 验证 checkpoint 文件
    checkpoints = list((tmp_path / "checkpoints").glob("*.json"))
    assert len(checkpoints) > 0, "应至少有 1 个 checkpoint 文件"

    content = json.loads(checkpoints[0].read_text())
    # v5 包装格式：{"saved_at": ..., "state": ...}
    assert "state" in content, "checkpoint 应为 v5 包装格式"
    steps = content["state"].get("steps", [])
    assert len(steps) > 0, "state 应含至少 1 个 step"

    last_step = steps[-1]
    assert last_step.get("result", {}).get("error") == "all_search_failed", \
        "result.error 应为 all_search_failed"

    # 验证 quality_flags 含 search_phase_timeout
    flags = last_step.get("quality_flags", [])
    spt_flags = [f for f in flags if f.get("category") == "search_phase_timeout"]
    assert len(spt_flags) == 1, "应含 1 个 search_phase_timeout flag"


# ============================================================
# 集成测试 3：TokenAudit 联动验证
# ============================================================

@pytest.mark.asyncio
async def test_timeout_token_audit_integration(tmp_path):
    """超时路径下 TokenAudit 正确处理 token_usage=None 的 Step。

    已知限制：FM 审查的 LLM 调用 token 在 step1_search_with_supplement 内部消耗，
    但未透传到 StepOutput.token_usage（设计层面限制，需 D 组或独立研究解决）。
    本测试验证 TokenAudit 在这种情况下不崩溃、文件持久化正常。

    验证点：
    1. TokenAudit.generate_report 不抛异常
    2. summary.total_tokens == 0（fail path 无 token 记录）
    3. steps[0].total_tokens == None（N/A 标记）
    4. JSON + Markdown 文件持久化到 tmp_path
    """
    from models import StepOutput
    from harness.token_audit import TokenAudit

    # 构造 fail path 的 state（token_usage=None，符合实际行为）
    state = ReportState(industry_name="测试行业")
    state.steps.append(StepOutput(
        step_id="1_info_collection",
        step_label="信息收集",
        reasoning="搜索超时",
        confidence="低",
        result={"error": "all_search_failed"},
        # 不设 token_usage，模拟 fail path（LLM 总结被跳过）
        quality_flags=[QualityFlag(
            category="search_phase_timeout",
            field="search_phase",
            severity="high",
            detail="超时",
            terminates_flow=True,
        )],
    ))

    audit = TokenAudit(log_dir=str(tmp_path))
    report = audit.generate_report(state, "test_trace", "测试行业")

    # 验证 audit 不崩溃且汇总字段存在
    summary = report["summary"]
    assert summary["total_tokens"] == 0, "fail path 无 token 记录，应为 0"

    # 验证 step 在报表中标记为 N/A
    steps_data = report["steps"]
    assert len(steps_data) == 1
    assert steps_data[0]["total_tokens"] is None, "step 的 total_tokens 应为 None（N/A）"

    # 验证文件持久化
    assert (tmp_path / "test_trace_token_audit.json").exists(), "JSON 报表应持久化"
    assert (tmp_path / "test_trace_token_audit.md").exists(), "Markdown 报表应持久化"


# ============================================================
# 补充测试（采纳 architecture-critic P2 风险2）：
# Step 2/3/4 or_fallback_result 终止路径专门测试
# 现有 9 个测试只覆盖 search_phase_timeout + 复合场景，
# 本测试覆盖 or_fallback_result 在 Step 2/3/4 触发终止的路径
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
async def test_step2_or_fallback_result_terminates(mock_call_llm):
    """Step 2 or_fallback_result(selected_dimensions) 触发 _check_quality_gate 终止。

    验证点：
    1. mock call_llm 返回空 selected_dimensions → 触发 or_fallback_result flag
    2. _check_quality_gate 检测到 terminates_flow=True flag → raise QualityGateError
    3. 异常消息含 "触发终止性降级"
    """
    # mock LLM 返回不含 selected_dimensions 的 JSON
    mock_call_llm.return_value = {
        "text": json.dumps({"reasoning": "测试", "abandoned_dimensions": []}, ensure_ascii=False),
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }

    state = ReportState(industry_name="测试行业")
    logger = MagicMock()
    logger.log = MagicMock()
    context_builder = MagicMock()
    context_builder.build = MagicMock(return_value="context")
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step(
            step_index=2,
            state=state,
            logger=logger,
            context_builder=context_builder,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_step2",
            mock=False,
        )

    # 验证 step 被添加且 quality_flags 含 or_fallback_result
    assert len(state.steps) == 1
    flags = state.steps[-1].quality_flags
    or_flags = [f for f in flags if f.category == "or_fallback_result"]
    assert len(or_flags) == 1
    assert or_flags[0].terminates_flow is True
    assert or_flags[0].field == "selected_dimensions"


@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
async def test_step3_or_fallback_result_terminates(mock_call_llm):
    """Step 3 or_fallback_result(chapters) 触发 _check_quality_gate 终止。"""
    # mock LLM 返回不含 chapters 的 JSON
    mock_call_llm.return_value = {
        "text": json.dumps({"reasoning": "测试"}, ensure_ascii=False),
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }

    state = ReportState(industry_name="测试行业")
    logger = MagicMock()
    logger.log = MagicMock()
    context_builder = MagicMock()
    context_builder.build = MagicMock(return_value="context")
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step(
            step_index=3,
            state=state,
            logger=logger,
            context_builder=context_builder,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_step3",
            mock=False,
        )

    assert len(state.steps) == 1
    flags = state.steps[-1].quality_flags
    or_flags = [f for f in flags if f.category == "or_fallback_result"]
    assert len(or_flags) == 1
    assert or_flags[0].terminates_flow is True
    assert or_flags[0].field == "chapters"


@pytest.mark.asyncio
@patch("frost_agent.call_llm", new_callable=AsyncMock)
async def test_step4_or_fallback_result_terminates(mock_call_llm):
    """Step 4 or_fallback_result(report_text < 500) 触发 _check_quality_gate 终止。"""
    # mock LLM 返回极短文本（< 500 字符）
    mock_call_llm.return_value = {
        "text": "太短了",  # < 500 字符
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }

    state = ReportState(industry_name="测试行业")
    logger = MagicMock()
    logger.log = MagicMock()
    context_builder = MagicMock()
    context_builder.build = MagicMock(return_value="context")
    checkpoint_mgr = MagicMock()
    checkpoint_mgr.save = MagicMock()

    with pytest.raises(QualityGateError, match="触发终止性降级"):
        await _run_step(
            step_index=4,
            state=state,
            logger=logger,
            context_builder=context_builder,
            checkpoint_mgr=checkpoint_mgr,
            trace_id="test_step4",
            mock=False,
        )

    assert len(state.steps) == 1
    flags = state.steps[-1].quality_flags
    or_flags = [f for f in flags if f.category == "or_fallback_result"]
    assert len(or_flags) == 1
    assert or_flags[0].terminates_flow is True
    assert or_flags[0].field == "report_text"
