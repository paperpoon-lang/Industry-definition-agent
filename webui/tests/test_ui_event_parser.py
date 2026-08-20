"""ui_events.py 解析器持久化单测（计划 v2.4 验证步骤 1）。

Fixture 维护说明（裁决 W8）：
手工构造的 jsonl fixture 基于 demo2/frost_agent.py 的事件格式。若 agent 日志格式变化
导致测试失效，从真实运行中提取新 fixture 的步骤：
1. 跑一次真实/半 Mock 任务：cd demo2 && python frost_agent.py "某行业"
2. 从启动横幅拿到 trace_id，打开 demo2/logs/{trace_id}.jsonl
3. 挑选所需 event_type 的行（如 llm_raw_response/supplement_search_done），
   替换下方 fixture 构造中的 data 字段即可

覆盖场景：fm_review 缺口卡片、text_preview 截断降级（W3）、supplement 卡片、
search_gap_record 终态、半行 jsonl（P2-7）、损坏行降级、stdout 各关键标记、
exit_code 错误卡片由 app.py 负责（不在解析器范围）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ui_events  # noqa: E402


def _ctx():
    return {"trace_id": None, "jsonl_active": False, "jsonl_offset": 0}


# ---------------- stdout 解析 ----------------

class TestStdout:
    def test_trace_id_captured_no_card(self):
        ctx = _ctx()
        events = ui_events.parse_stdout_line("trace_id: 08fd8d73383e", ctx)
        assert ctx["trace_id"] == "08fd8d73383e"
        assert events == []  # 引导信息不渲染卡片

    def test_trace_id_only_first_time(self):
        ctx = _ctx()
        ui_events.parse_stdout_line("trace_id: aaaaaaaaaaaa", ctx)
        # 第二次出现（如结束横幅）不覆盖
        ui_events.parse_stdout_line("trace_id: bbbbbbbbbbbb", ctx)
        assert ctx["trace_id"] == "aaaaaaaaaaaa"

    def test_step_begin_fallback_only(self):
        events = ui_events.parse_stdout_line("\n--- Step 1: 信息收集 开始 ---", _ctx())
        assert len(events) == 1
        assert events[0]["kind"] == "step_start"
        assert events[0]["step"] == 1
        assert events[0]["fallback_only"] is True

    def test_step_skip_not_fallback(self):
        events = ui_events.parse_stdout_line("[跳过] Step 2: 维度筛选 — 已从 checkpoint 恢复", _ctx())
        assert len(events) == 1
        assert events[0]["fallback_only"] is False  # jsonl 不记录跳过，stdout 独有

    def test_mechanical_signal(self):
        events = ui_events.parse_stdout_line(
            "  [机械信号] 第 2 轮 判定 unproductive（重复query或零返回）", _ctx())
        assert len(events) == 1
        assert events[0]["icon"] == "⚠️"
        assert events[0]["step"] == 1

    def test_supplement_stop(self):
        events = ui_events.parse_stdout_line(
            "  [补搜] 第 2 轮 机械信号连续2轮unproductive，止损停止", _ctx())
        assert len(events) == 1
        assert events[0]["icon"] == "⛔"

    def test_supplement_round_line_is_fallback(self):
        events = ui_events.parse_stdout_line("  [补搜] 第 1 轮补充 2 个 query，总共 5 个", _ctx())
        assert len(events) == 1
        assert events[0]["fallback_only"] is True  # jsonl supplement_search_done 覆盖

    def test_report_file(self):
        events = ui_events.parse_stdout_line(
            "报告文件: /x/reports/固态电池_20260814_155318_UTC_行业定义报告.md", _ctx())
        assert len(events) == 1
        assert events[0]["kind"] == "report_ready"
        assert "固态电池" in events[0]["detail"]

    def test_quality_gate_error(self):
        events = ui_events.parse_stdout_line("[质量门终止] 搜索阶段失败", _ctx())
        assert events[0]["kind"] == "error"

    def test_cost_card(self):
        events = ui_events.parse_stdout_line("  总成本: ¥0.1234 (≈ $0.017)", _ctx())
        assert events[0]["kind"] == "card"
        assert "¥0.1234" in events[0]["title"]

    def test_unrelated_line_no_event(self):
        assert ui_events.parse_stdout_line("随便一行无关输出", _ctx()) == []


# ---------------- jsonl 解析 ----------------

class TestJsonl:
    def test_fm_review_with_gaps(self):
        fm_json = json.dumps({
            "last_round_yield": None,
            "yield_evidence": "",
            "data_gaps": ["缺少固态电池的国家/行业标准文件原文或标准号",
                          "缺少与半固态电池的量化区分参数",
                          "缺少GICS分类编码归属"],
            "gap_types": ["not_found", "snippet_too_shallow", "not_found"],
            "suggested_queries": ["GB/T 固态电池 标准号", "固态电池 电解质含量 阈值"],
        }, ensure_ascii=False)
        event = {"event_type": "llm_raw_response", "data": {
            "step_id": "1_info_collection_fm_review", "round_label": "第 1 轮",
            "text_preview": fm_json}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert len(events) == 1
        assert "3 个信息缺口" in events[0]["title"]
        assert "建议补搜 2 个 query" in events[0]["detail"]
        assert events[0]["step"] == 1

    def test_fm_review_no_gaps(self):
        fm_json = json.dumps({"last_round_yield": "productive", "data_gaps": [],
                              "suggested_queries": []}, ensure_ascii=False)
        event = {"event_type": "llm_raw_response", "data": {
            "step_id": "1_info_collection_fm_review", "round_label": "第 3 轮",
            "text_preview": fm_json}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert "无信息缺口" in events[0]["title"]

    def test_fm_review_truncated_json_degrades(self):
        """W3：text_preview 截断 1000 字符导致 JSON 不完整 → 正则降级提取条数。"""
        fm_json = json.dumps({
            "data_gaps": ["缺口一" * 100, "缺口二" * 100, "缺口三" * 100],
            "suggested_queries": ["q1"],
        }, ensure_ascii=False)
        truncated = fm_json[:1000]  # 中间截断，json.loads 必然失败
        event = {"event_type": "llm_raw_response", "data": {
            "step_id": "1_info_collection_fm_review", "round_label": "第 1 轮",
            "text_preview": truncated}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert len(events) == 1
        # 截断场景：正则近似提取（至少识别出有缺口，不崩溃）
        assert events[0]["icon"] == "🧠"
        assert "FM 审查" in events[0]["title"]

    def test_fm_review_non_json(self):
        event = {"event_type": "llm_raw_response", "data": {
            "step_id": "1_info_collection_fm_review", "round_label": "第 1 轮",
            "text_preview": "抱歉，我无法完成这个任务。"}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert "非结构化" in events[0]["title"]

    def test_supplement_search_done(self):
        event = {"event_type": "supplement_search_done", "data": {
            "round": 1,
            "queries": ["GB/T 固态电池 术语 分类 标准号", "CATARC 固态电池 草案"],
            "results_per_query": {"GB/T 固态电池 术语 分类 标准号": 5,
                                  "CATARC 固态电池 草案": 5}}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert len(events) == 1
        assert "补搜第 1 轮" in events[0]["title"]
        assert "5 条" in events[0]["detail"]

    def test_search_gap_record(self):
        event = {"event_type": "search_gap_record", "data": {
            "stop_reason": "gaps_closed", "supplement_rounds": 2,
            "remaining_gaps": []}}
        events = ui_events.parse_jsonl_event(event, _ctx())
        assert "缺口全部闭合" in events[0]["title"]
        assert "补搜 2 轮" in events[0]["detail"]

    def test_step_complete_variants(self):
        # Step1 带 confidence
        e1 = ui_events.parse_jsonl_event({"event_type": "step_complete", "data": {
            "step_id": "1_info_collection", "confidence": "高"}}, _ctx())
        assert "置信度：高" in e1[0]["detail"]
        # Step2 只有 flags
        e2 = ui_events.parse_jsonl_event({"event_type": "step_complete", "data": {
            "step_id": "2_dimension_screening", "quality_flags_count": 0}}, _ctx())
        assert e2[0]["step"] == 2
        # Step5 带 overall/failed
        e5 = ui_events.parse_jsonl_event({"event_type": "step_complete", "data": {
            "step_id": "5_self_check", "overall": "pass", "failed": []}}, _ctx())
        assert "pass" in e5[0]["detail"]

    def test_unknown_event_type_ignored(self):
        assert ui_events.parse_jsonl_event({"event_type": "search_done", "data": {}}, _ctx()) == []
        assert ui_events.parse_jsonl_event({"event_type": "???", "data": {}}, _ctx()) == []

    def test_malformed_data_no_crash(self):
        assert ui_events.parse_jsonl_event({"event_type": "step_complete"}, _ctx()) == []
        assert ui_events.parse_jsonl_event({}, _ctx()) == []


# ---------------- jsonl tail（半行保护 P2-7） ----------------

class TestTailJsonl:
    def test_normal_read(self, tmp_path):
        p = tmp_path / "t.jsonl"
        lines = [{"event_type": "start", "data": {}}, {"event_type": "complete", "data": {}}]
        p.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
        events, offset = ui_events.tail_jsonl(p, 0)
        assert len(events) == 2
        assert offset == p.stat().st_size

    def test_half_line_not_consumed(self, tmp_path):
        """半行保护：不完整行不推进偏移量，下次重读。"""
        p = tmp_path / "t.jsonl"
        complete = json.dumps({"event_type": "start", "data": {}})
        half = '{"event_type": "comp'  # 写入中的半行
        p.write_text(complete + "\n" + half, encoding="utf-8")
        events, offset = ui_events.tail_jsonl(p, 0)
        assert len(events) == 1
        assert offset == len(complete) + 1  # 只推进到完整行，半行保留
        # 模拟写端补全后半行
        with open(p, "a", encoding="utf-8") as f:
            f.write('lete", "data": {}}\n')
        events2, offset2 = ui_events.tail_jsonl(p, offset)
        assert len(events2) == 1
        assert events2[0]["event_type"] == "complete"

    def test_only_half_line_returns_zero(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_text('{"event_type": "sta', encoding="utf-8")
        events, offset = ui_events.tail_jsonl(p, 0)
        assert events == []
        assert offset == 0

    def test_corrupt_line_skipped(self, tmp_path):
        p = tmp_path / "t.jsonl"
        good = json.dumps({"event_type": "start", "data": {}})
        p.write_text("这不是 JSON\n" + good + "\n", encoding="utf-8")
        events, offset = ui_events.tail_jsonl(p, 0)
        assert len(events) == 1
        assert offset == p.stat().st_size

    def test_missing_file(self, tmp_path):
        events, offset = ui_events.tail_jsonl(tmp_path / "不存在.jsonl", 0)
        assert events == [] and offset == 0
