"""B1-2 补搜 stop_reason 单元测试（v1.4：前瞻继续论证范式）。

v1.4 范式：默认不搜下一轮，除非FM给出有效继续理由（三要素）；
保底轮（MIN_GUARANTEED_ROUNDS=1）内无条件放行；影子模式下理由无效仅记录不拦截；
v1.3回顾性机制（fm_effective/三信号OR/None断链/low_yield）已移除。
所有测试 mock search_with_fallback / _fm_review_search_results / search_single_query，
不依赖真实 API。
"""
import hashlib
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

import frost_agent
from frost_agent import (
    step1_search_with_supplement,
    _validate_justification,
    _make_fingerprint,
    _content_fingerprint_overlap,
)
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


_VALID_JUSTIFICATION = [{
    "target_gap_index": 0,
    "new_direction": "换标准号定点搜：检索GB/T正式发布文本",
    "reachability": "标准号已在搜索结果中出现，全文检索有命中可能",
}]


def _fm_result(data_gaps, suggested_queries=None, justification=None):
    """构造 FM 审查返回值（v1.4：含继续理由）。"""
    return {
        "data_gaps": data_gaps,
        "gap_types": ["untyped"] * len(data_gaps),
        "suggested_queries": suggested_queries or [],
        "next_round_justification": justification if justification is not None else [],
    }


def _mock_search_single_query_result(query):
    """模拟 search_single_query 的同步返回值。"""
    return [{"title": f"补搜结果-{query}", "url": f"http://sup-{query}.com", "content": f"补搜内容-{query}"}]


def _unique_results_factory(prefix: str):
    """构造每次返回不同URL的搜索结果（指纹/机械审计均productive）。"""
    counter = {"n": 0}

    def _side_effect(query):
        counter["n"] += 1
        return [{
            "title": f"{prefix}-结果{counter['n']}",
            "url": f"http://{prefix}-{counter['n']}.com",
            "content": f"{prefix}内容{counter['n']}",
        }]

    return _side_effect


def _mock_methodology_loader():
    """创建一个返回合理字符串的 methodology_loader mock。"""
    ml = MagicMock()
    ml.load_slice.return_value = "### 信息优先级\n1. 行业边界\n2. 技术路线\n3. 竞争格局"
    return ml


# ============================================================
# v1.4 信号1：_validate_justification 验证规则
# ============================================================

class TestValidateJustification:
    def test_validate_justification_valid(self):
        """三要素齐全+index合法 → 通过。"""
        assert _validate_justification(_VALID_JUSTIFICATION, ["缺口A"]) is True

    def test_validate_justification_partial_valid(self):
        """部分条目无效但至少一条有效 → 通过（任一有效即通过）。"""
        justification = [
            {"target_gap_index": 5, "new_direction": "x", "reachability": "y"},  # 超界
            "not-a-dict",  # 非dict
            {"target_gap_index": 0, "new_direction": "换英文", "reachability": "标准号已知"},  # 有效
        ]
        assert _validate_justification(justification, ["缺口A"]) is True

    def test_validate_justification_empty(self):
        """空数组/None/非list（含v1.3旧格式字符串）→ 无效。"""
        assert _validate_justification([], ["缺口A"]) is False
        assert _validate_justification(None, ["缺口A"]) is False
        assert _validate_justification("字符串旧格式", ["缺口A"]) is False

    def test_validate_justification_index_bounds(self):
        """target_gap_index 超界/负数 → 无效。"""
        assert _validate_justification(
            [{"target_gap_index": 1, "new_direction": "x", "reachability": "y"}], ["缺口A"]
        ) is False
        assert _validate_justification(
            [{"target_gap_index": -1, "new_direction": "x", "reachability": "y"}], ["缺口A"]
        ) is False

    def test_validate_justification_bool_rejected(self):
        """target_gap_index 为 bool → 该条无效（bool是int子类会穿透isinstance）。"""
        assert _validate_justification(
            [{"target_gap_index": True, "new_direction": "x", "reachability": "y"}], ["缺口A"]
        ) is False

    def test_validate_justification_empty_fields(self):
        """new_direction/reachability空字符串 → 该条无效。"""
        assert _validate_justification(
            [{"target_gap_index": 0, "new_direction": "  ", "reachability": "y"}], ["缺口A"]
        ) is False
        assert _validate_justification(
            [{"target_gap_index": 0, "new_direction": "x", "reachability": ""}], ["缺口A"]
        ) is False


# ============================================================
# 指纹（v1.4 降为纯审计，机制保留，防回归覆盖）
# ============================================================

class TestFingerprint:
    def test_fingerprint_url_primary(self):
        """URL相同判重复（不依赖内容）。"""
        a = {"url": "http://same.com", "content": "内容A"}
        b = {"url": "http://same.com", "content": "完全不同的内容B"}
        assert _make_fingerprint(a) == _make_fingerprint(b)

    def test_fingerprint_content_fallback(self):
        """URL为空时用content前200字符hash。"""
        a = {"url": "", "content": "同样内容"}
        b = {"url": None, "content": "同样内容"}
        assert _make_fingerprint(a) == _make_fingerprint(b)
        assert _make_fingerprint(a).startswith("content:")

    def test_fingerprint_overlap_all_history(self):
        """跨轮捕获：与历史相同URL → unproductive。"""
        old = [{"url": "http://old.com", "content": "x"}]
        historical = {_make_fingerprint(r) for r in old}
        assert _content_fingerprint_overlap(
            [{"url": "http://old.com", "content": "y"}], historical, 0.8
        ) == "unproductive"

    def test_fingerprint_threshold_boundary(self):
        """阈值边界：4/5重复（0.8）触发；3/5（0.6）不触发；空结果返回productive。"""
        historical = {f"url:http://old{i}.com" for i in range(10)}
        items_4_of_5 = [{"url": f"http://old{i}.com", "content": "x"} for i in range(4)] + [
            {"url": "http://new.com", "content": "x"}
        ]
        assert _content_fingerprint_overlap(items_4_of_5, historical, 0.8) == "unproductive"

        items_3_of_5 = [{"url": f"http://old{i}.com", "content": "x"} for i in range(3)] + [
            {"url": f"http://new{i}.com", "content": "x"} for i in range(2)
        ]
        assert _content_fingerprint_overlap(items_3_of_5, historical, 0.8) == "productive"

        assert _content_fingerprint_overlap([], historical, 0.8) == "productive"

    def test_fingerprint_failed_results_excluded(self):
        """搜索失败条目不参与指纹计算（模拟循环内过滤步骤）。"""
        items = [
            {"title": "搜索失败", "url": "", "content": "TimeoutError"},
            {"title": "正常", "url": "http://new.com", "content": "新内容"},
        ]
        historical = {_make_fingerprint(items[0])}
        filtered = [r for r in items if r.get("title") != "搜索失败"]
        assert _content_fingerprint_overlap(filtered, historical, 0.8) == "productive"


# ============================================================
# v1.4 核心门控行为（保底轮/理由门控/影子模式/交互）
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_first_round_unconditional(mock_search, mock_fm, mock_single):
    """保底轮内（第1轮补搜）无理由也放行；第2轮有理由继续。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=[]),   # 审查1：无理由，保底轮内仍放行
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),  # 审查2：有理由
        _fm_result(["缺口C"]),  # 审查3：轮数上限
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _unique_results_factory("guarantee")

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    assert mock_single.await_count >= 2, "保底轮应无条件执行补搜1，理由有效应执行补搜2"


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", False)  # 赋权模式
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_no_justification_stops(mock_search, mock_fm, mock_single, tmp_path):
    """赋权模式：保底轮后理由无效 → no_justification停止，不执行第2轮补搜。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),  # 审查1（保底轮，理由有无均可）
        _fm_result(["缺口B"], ["补搜B"], justification=[]),  # 审查2：理由无效 → 停止
    ]
    mock_single.side_effect = _unique_results_factory("stop")

    logger = SessionEventLog("测试行业", trace_id="test_nojust", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    assert mock_single.await_count == 1, "仅保底轮1次补搜应执行"
    jsonl_path = tmp_path / "test_nojust.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert gap_records[0]["data"]["stop_reason"] == "no_justification"
    assert gap_records[0]["data"]["supplement_rounds"] == 1


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", True)  # 影子模式
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_shadow_mode_justification_logged_not_blocking(mock_search, mock_fm, mock_single, tmp_path):
    """影子模式：理由无效仅记录不拦截，照旧budget_exhausted收尾，审计字段完整。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=[]),  # 审查1：保底轮
        _fm_result(["缺口B"], ["补搜B"], justification=[]),  # 审查2：理由无效，影子不拦截
        _fm_result(["缺口C"]),  # 审查3：轮数上限
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _unique_results_factory("shadow")

    logger = SessionEventLog("测试行业", trace_id="test_shadow14", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    assert mock_single.await_count >= 2, "影子模式理由无效不拦截，补搜应照常执行"
    jsonl_path = tmp_path / "test_shadow14.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    data = gap_records[0]["data"]
    assert data["stop_reason"] == "budget_exhausted", "影子模式不应产生no_justification"
    assert data["shadow_mode"] is True
    assert len(data["justification_history"]) == 3, "每轮审查的理由都应落盘"
    assert data["justification_valid_history"] == [False, False, False]


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", False)  # 赋权模式（验证硬闸门影子罩外语义）
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_justification_valid_but_queries_deduped(mock_search, mock_fm, mock_single):
    """理由有效但query全已试 → query_space_exhausted（硬闸门）。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        # 审查2：理由有效，但建议的query与已试完全相同 → 去重后空 → query_space_exhausted
        _fm_result(["缺口B"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"]),  # 最终审查（query_space_exhausted不在跳过列表，仍执行）
    ]
    mock_single.side_effect = _unique_results_factory("dedup")

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    assert mock_single.await_count == 1, "第2轮query全部重复，不应执行第2次补搜"


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", True)  # 影子模式（硬闸门在罩外，影子也拦）
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_invalid_justification_shadow_continues_dedup_fires(mock_search, mock_fm, mock_single):
    """组合路径：理由无效+影子继续，但query全已试 → query_space_exhausted（影子罩外硬闸门）。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=[]),
        _fm_result(["缺口B"], ["补搜A"], justification=[]),  # 理由无效（影子放行）+ query重复（硬闸拦）
        _fm_result(["缺口B"]),  # 最终审查
    ]
    mock_single.side_effect = _unique_results_factory("combo")

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    assert mock_single.await_count == 1, "影子放行理由门控，但query去重硬闸门仍应拦截第2轮"


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", False)
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 0)  # 配置生效性：保底0
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_zero_guaranteed_rounds_config(mock_search, mock_fm, mock_single, tmp_path):
    """MIN_GUARANTEED_ROUNDS=0：第1轮即需理由（配置生效性）。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=[]),  # 审查1即无理由 → 停止
    ]
    mock_single.side_effect = _unique_results_factory("zero")

    logger = SessionEventLog("测试行业", trace_id="test_zero", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    assert mock_single.await_count == 0, "保底0+无理由 → 第1轮补搜即被拦"
    jsonl_path = tmp_path / "test_zero.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert gap_records[0]["data"]["stop_reason"] == "no_justification"


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", False)
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_low_yield_removed(mock_search, mock_fm, mock_single, tmp_path):
    """回归确认：v1.3的连续unproductive场景不再产生low_yield（防死代码路径复活）。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    # v1.4下FM不再输出last_round_yield——此测试模拟"理由持续有效"的正常流，验证stop_reason枚举中无low_yield
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口A"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口A"]),  # 审查3：轮数上限
        _fm_result(["缺口A"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    logger = SessionEventLog("测试行业", trace_id="test_nolow", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    jsonl_path = tmp_path / "test_nolow.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert gap_records[0]["data"]["stop_reason"] != "low_yield", "v1.4已移除low_yield"
    assert "low_yield_trigger_history" not in gap_records[0]["data"], "v1.3字段应已移除"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_justification_logged(mock_search, mock_fm, mock_single, tmp_path):
    """Event Log含justification_history/valid_history/round_gap_types/fingerprint_history/shadow_mode。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C"]),  # 审查3
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _unique_results_factory("logging")

    logger = SessionEventLog("测试行业", trace_id="test_v14_log", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    jsonl_path = tmp_path / "test_v14_log.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert len(gap_records) == 1
    data = gap_records[0]["data"]
    # v1.4 新字段
    assert "justification_history" in data
    assert "justification_valid_history" in data
    assert "round_gap_types" in data
    assert "fingerprint_history" in data
    assert "mechanical_history" in data
    assert "fingerprint_threshold" in data
    assert "shadow_mode" in data
    assert data["justification_valid_history"][:2] == [True, True]
    assert len(data["fingerprint_history"]) == 2, "2轮补搜各1条指纹审计"
    # v1.3 字段已移除
    assert "yield_history" not in data
    assert "round_signals" not in data


def test_prompt_no_yield_section():
    """FM prompt不再含last_round_yield段落（防回归）。"""
    prompt = frost_agent.FM_REVIEW_PROMPT
    assert "last_round_yield" not in prompt, "v1.4 prompt应移除last_round_yield"
    assert "yield_evidence" not in prompt, "v1.4 prompt应移除yield_evidence"
    assert "previous_round_info" not in prompt, "v1.4 prompt应移除previous_round_info占位符"
    assert "next_round_justification" in prompt
    assert "target_gap_index" in prompt
    assert "new_direction" in prompt
    assert "reachability" in prompt


# ============================================================
# v1.1/v1.2 保留测试（适配v1.4 helper）
# ============================================================

@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_gaps_closed(mock_search, mock_fm, mock_single):
    """缺口闭合时提前停止。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result([], justification=None),  # 第 2 轮缺口闭合
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
    """换口不缩量继续补搜：prev=[a,b] → new=[c,d]（理由持续有效）→ 搜满轮数。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A", "缺口B"], ["补搜A", "补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C", "缺口D"], ["补搜C", "补搜D"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口E"], justification=_VALID_JUSTIFICATION),  # 第 3 轮（轮数上限）
        _fm_result(["缺口E"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) == 1, "轮数耗尽后仍有缺口应有 data_gaps_remaining flag"
    assert "budget_exhausted" in gap_flags[0].detail, "应因 budget_exhausted 停止"


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_budget_exhausted(mock_search, mock_fm, mock_single):
    """补搜满轮数上限停止，stop_reason=budget_exhausted。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    assert "budget_exhausted" in gap_flags[0].detail


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_fm_failed(mock_search, mock_fm, mock_single):
    """FM审查失败时停止，stop_reason=fm_review_failed。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        {"_error_type": "timeout"},
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    fm_flags = [f for f in flags if f.category == "fm_review_skipped"]
    assert len(fm_flags) >= 1, "FM失败应有fm_review_skipped flag"


@pytest.mark.asyncio
@patch("frost_agent.JUSTIFICATION_SHADOW_MODE", False)
@patch("frost_agent.MIN_GUARANTEED_ROUNDS", 1)
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 3)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_supplement_stop_no_suggested_queries(mock_search, mock_fm, mock_single):
    """理由有效但FM未生成补搜query → no_suggested_queries。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], [], justification=_VALID_JUSTIFICATION),  # 理由有效但无query
        _fm_result(["缺口B"]),  # 最终审查（no_suggested_queries不在跳过列表，仍执行）
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    assert "no_suggested_queries" in gap_flags[0].detail


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_gap_record_event_logged(mock_search, mock_fm, mock_single, tmp_path):
    """search_gap_record事件落盘且含核心字段。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    logger = SessionEventLog("测试行业", trace_id="test_gaprec", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    jsonl_path = tmp_path / "test_gaprec.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    gap_records = [e for e in events if e.get("event_type") == "search_gap_record"]
    assert len(gap_records) == 1
    data = gap_records[0]["data"]
    assert "stop_reason" in data
    assert "supplement_rounds" in data
    assert "remaining_gaps" in data


@pytest.mark.asyncio
@patch("frost_agent.MAX_SUPPLEMENT_ROUNDS", 2)
@patch("frost_agent.MAX_TOTAL_QUERIES", 10)
@patch("frost_agent.search_single_query", new_callable=AsyncMock)
@patch("frost_agent._fm_review_search_results", new_callable=AsyncMock)
@patch("frost_agent.search_with_fallback", new_callable=AsyncMock)
async def test_quality_flag_detail_human_readable(mock_search, mock_fm, mock_single):
    """QualityFlag.detail为纯文本（含轮数/缺口/停止原因）。"""
    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False,
    )

    gap_flags = [f for f in flags if f.category == "data_gaps_remaining"]
    assert len(gap_flags) >= 1
    detail = gap_flags[0].detail
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
    """每轮补搜后记录 supplement_search_done 事件，含 queries/results_per_query/content_lengths/fingerprints_sample。"""
    from harness.session_log import SessionEventLog

    mock_search.return_value = _mock_first_round_results()
    mock_fm.side_effect = [
        _fm_result(["缺口A"], ["补搜A"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口B"], ["补搜B"], justification=_VALID_JUSTIFICATION),
        _fm_result(["缺口C"]),  # 最终审查
    ]
    mock_single.side_effect = _mock_search_single_query_result

    logger = SessionEventLog("测试行业", trace_id="test_supdone", log_dir=str(tmp_path))
    results, flags, errors = await step1_search_with_supplement(
        "测试行业", "fake_key", _mock_methodology_loader(), AsyncMock(),
        mock_search_mode=False, logger=logger,
    )

    jsonl_path = tmp_path / "test_supdone.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    sup_events = [e for e in events if e.get("event_type") == "supplement_search_done"]
    assert len(sup_events) >= 1, "应至少有 1 个 supplement_search_done 事件"

    data = sup_events[0]["data"]
    assert "round" in data
    assert "queries" in data
    assert "results_per_query" in data
    assert "content_lengths" in data
    assert "fingerprints_sample" in data, "v1.4：指纹审计样本应落盘"
