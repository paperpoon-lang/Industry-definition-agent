"""B1-2 步骤1：补搜 stop_reason 单元测试。

验证 5 种 stop_reason 的触发条件和边界行为。
所有测试 mock search_with_fallback / _fm_review_search_results / search_single_query，
不依赖真实 API。
"""
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

import frost_agent
from frost_agent import step1_search_with_supplement
from models import QualityFlag


def _mock_first_round_results():
    """模拟首轮 3 个 query 的搜索结果。"""
    return {
        "results": {
            "query1": [{"title": "结果1", "url": "http://1.com", "content": "内容1"}],
            "query2": [{"title": "结果2", "url": "http://2.com", "content": "内容2"}],
            "query3": [{"title": "结果3", "url": "http://3.com", "content": "内容3"}],
        },
        "error_count": 0,
    }


def _fm_result(data_gaps, suggested_queries=None, yield_flag=None):
    """构造 FM 审查返回值。"""
    return {
        "last_round_yield": yield_flag,
        "data_gaps": data_gaps,
        "suggested_queries": suggested_queries or [],
    }


def _mock_search_single_query_result(query):
    """模拟 search_single_query 的同步返回值。"""
    return [{"title": f"补搜结果-{query}", "url": f"http://sup-{query}.com", "content": f"补搜内容-{query}"}]


def _mock_methodology_loader():
    """创建一个返回合理字符串的 methodology_loader mock。"""
    ml = MagicMock()
    ml.load_slice.return_value = "### 信息优先级\n1. 行业边界\n2. 技术路线\n3. 竞争格局"
    return ml


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_gaps_closed(mock_search, mock_fm, mock_single):
    """缺口闭合时提前停止，不耗尽预算。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"]),
        _fm_result([], yield_flag="productive"),  # 第 2 轮缺口闭合
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) == 0, "缺口闭合后不应有 data_gaps_remaining flag"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_continue_on_gap_turnover(mock_search, mock_fm, mock_single):
    """换口不缩量不止损：prev=[a,b] → new=[c,d]（同计数不同内容、FM 判 productive）→ 继续补搜。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A", "缺口B"], ["补搜A", "补搜B"], yield_flag=None),
        _fm_result(["缺口C", "缺口D"], ["补搜C", "补搜D"], yield_flag="productive"),  # 换口，判 productive
        _fm_result(["缺口E"], ["补搜E"], yield_flag="productive"),  # 第 3 轮
        _fm_result(["缺口E"], yield_flag="productive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) == 1, "3 轮后仍有缺口应有 data_gaps_remaining flag"
    assert "budget_exhausted" in gap_flags[0].detail, "应因 budget_exhausted 停止"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 5)
@patch("frost_agent.MAX_TOTAL_QUERIES", 20)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_low_yield(mock_search, mock_fm, mock_single):
    """FM 连续 2 轮判 unproductive 才止损，stop_reason=low_yield。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),  # 首轮
        _fm_result(["缺口A"], ["补搜A2"], yield_flag="unproductive"),  # 1st
        _fm_result(["缺口A"], ["补搜A3"], yield_flag="unproductive"),  # 2nd consecutive → low_yield
        _fm_result(["缺口A"], yield_flag="unproductive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    assert "low_yield" in gap_flags[0].detail, "应因 low_yield 停止"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_no_stop_single_unproductive(mock_search, mock_fm, mock_single):
    """仅 1 轮 unproductive 不止损。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),
        _fm_result(["缺口A"], ["补搜B"], yield_flag="unproductive"),  # 仅 1 次
        _fm_result(["缺口A"], yield_flag="unproductive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    assert "low_yield" not in gap_flags[0].detail, "仅 1 轮 unproductive 不应触发 low_yield"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_budget_exhausted(mock_search, mock_fm, mock_single):
    """补搜满 MAX_SUPPLEMENT_ROUNDS 轮停止，stop_reason=budget_exhausted。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),
        _fm_result(["缺口B"], ["补搜B"], yield_flag="productive"),
        _fm_result(["缺口C"], yield_flag="productive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    assert "budget_exhausted" in gap_flags[0].detail, "应因 budget_exhausted 停止"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_fm_failed(mock_search, mock_fm, mock_single):
    """FM 审查失败时停止，stop_reason=fm_review_failed。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.return_value = {"_error_type": "timeout"}

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    fm_flags = [f for f in flags if f.category == "fm_review_skipped"]
    assert len(fm_flags) >= 1, "FM 失败应有 fm_review_skipped flag"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_no_suggested_queries(mock_search, mock_fm, mock_single):
    """suggested_queries 为空时停止，stop_reason=no_suggested_queries。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], suggested_queries=[], yield_flag=None),
        _fm_result(["缺口A"], yield_flag=None),  # 最终审查
    ]

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    assert mock_single.call_count == 0, "无 suggested_queries 不应执行补搜"


# ============================================================
# Event Log 测试（步骤 2）
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_gap_record_event_logged(mock_search, mock_fm, mock_single, tmp_path):
    """Event Log 中出现 search_gap_record 事件，含 queries_used/supplement_rounds/remaining_gaps/stop_reason/yield_history。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),
        _fm_result(["缺口B"], ["补搜B"], yield_flag="productive"),
        _fm_result(["缺口C"], yield_flag="productive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    logger = SessionEventLog("测试行业", trace_id="test_gap", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
        logger=logger,
    )

    jsonl_path = tmp_path / "test_gap.jsonl"
    assert jsonl_path.exists(), "JSONL 文件应被创建"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert len(gap_records) >= 1, "应含 search_gap_record 事件"

    data = gap_records[0]["data"]
    assert "queries_used" in data
    assert "supplement_rounds" in data
    assert "remaining_gaps" in data
    assert "stop_reason" in data
    assert "yield_history" in data


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_quality_flag_detail_human_readable(mock_search, mock_fm, mock_single):
    """QualityFlag.detail 仍为纯文本（非 JSON），含轮数、缺口数、stop_reason。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),
        _fm_result(["缺口B"], ["补搜B"], yield_flag="productive"),
        _fm_result(["缺口C"], yield_flag="productive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1, "应有 data_gaps_remaining flag"
    detail = gap_flags[0].detail

    # 验证 detail 是纯文本而非 JSON
    assert not detail.startswith("{"), "detail 不应是 JSON 开头"
    assert "补搜" in detail
    assert "轮" in detail
    assert "停止原因" in detail


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_search_done_logged(mock_search, mock_fm, mock_single, tmp_path):
    """每轮补搜后记录 supplement_search_done 事件，含 queries/results_per_query/content_lengths。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], yield_flag=None),
        _fm_result(["缺口B"], ["补搜B"], yield_flag="productive"),
        _fm_result(["缺口C"], yield_flag="productive"),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    logger = SessionEventLog("测试行业", trace_id="test_sup", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
        logger=logger,
    )

    jsonl_path = tmp_path / "test_sup.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    sup_events = [e for e in events if e.get("event_type") == "supplement_search_done"]
    assert len(sup_events) >= 1, "应至少有 1 个 supplement_search_done 事件"

    data = sup_events[0]["data"]
    assert "round" in data
    assert "queries" in data
    assert "results_per_query" in data
    assert "content_lengths" in data
