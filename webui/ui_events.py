"""webui 事件解析器：把 frost_agent 的 stdout 行 / jsonl 事件归一化为 UI 事件。

纯函数模块，不依赖 streamlit（便于单测）。

通道分工（计划 v2.4）：
- jsonl = 时间线唯一事实源：语义卡片只从 jsonl 事件生成
- stdout = 引导（trace_id）+ jsonl 没有的信息（机械信号/停止原因/成本/报告路径/错误）+ 降级展示
- 两通道重叠的事件（补搜轮次/FM 审查/步骤边界）：stdout 侧标记 fallback_only=True，
  jsonl 激活时由调用方过滤掉，只在降级模式下展示

事件 dict 结构：
{
    "step": int | None,        # 所属步骤（1-6），None 表示全局事件
    "kind": str,               # step_start / step_complete / card / report_ready / error / info
    "icon": str,
    "title": str,
    "detail": str,
    "fallback_only": bool,     # True = 仅降级模式展示（jsonl 激活时被过滤）
}

ctx（调用方持有的解析状态 dict）：
{
    "trace_id": str | None,    # 从 stdout 启动横幅解析
    "jsonl_active": bool,      # jsonl 通道是否可用
    "jsonl_offset": int,       # tail 偏移量
}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

# step_id → 步骤号（前缀匹配，兼容 "1_info_collection_fm_review" 这类派生 id）
STEP_ID_PREFIXES = [
    ("1_info_collection", 1),
    ("2_dimension_screening", 2),
    ("3_structure_decision", 3),
    ("4_content_generation", 4),
    ("5_self_check", 5),
    ("6_output", 6),
]

STEP_LABELS = {1: "信息收集", 2: "维度筛选", 3: "结构决策", 4: "内容生成", 5: "自检", 6: "输出"}

# ---------------- stdout 正则 ----------------
RE_TRACE_ID = re.compile(r"trace_id:\s*([0-9a-f]{12})")
RE_STEP_BEGIN = re.compile(r"---\s*Step\s*(\d):\s*(.+?)\s*开始\s*---")
RE_STEP_DONE = re.compile(r"---\s*Step\s*(\d):\s*(.+?)\s*完成\s*---")
RE_STEP_SKIP = re.compile(r"\[跳过\]\s*Step\s*(\d)")
RE_MECHANICAL = re.compile(r"\[机械信号\].*unproductive")
RE_SUPPLEMENT_STOP = re.compile(r"\[补搜\].*(?:止损停止|停止|穷尽)")
RE_FM_NO_GAP = re.compile(r"\[FM 审查第\s*(\d+)\s*轮\]\s*无信息缺口")
RE_FM_FOUND_GAP = re.compile(r"\[FM 审查第\s*(\d+)\s*轮\]\s*发现缺口")
RE_SUPPLEMENT_ROUND = re.compile(r"\[补搜\]\s*第\s*(\d+)\s*轮补充\s*(\d+)\s*个 query")
RE_SELF_CHECK = re.compile(r"自检结果:\s*(.+)")
RE_TOTAL_COST = re.compile(r"总成本:\s*(.+)")
RE_REPORT_FILE = re.compile(r"报告文件:\s*(.+)")
RE_QUALITY_GATE = re.compile(r"\[质量门终止\]\s*(.*)")
RE_ERROR = re.compile(r"^\[错误\]\s*(.*)")
RE_SEARCH_TIMEOUT = re.compile(r"\[搜索阶段超时\]")
RE_FM_REVIEW_WARN = re.compile(r"\[FM 审查(?:超时|异常| JSON 解析失败)\].*")
RE_RESUME = re.compile(r"\[恢复\]\s*从 checkpoint 恢复了\s*(\d+)\s*个步骤")
RE_LLM_KEY_WARN = re.compile(r"\[警告\]\s*未配置 LLM_API_KEY")
RE_SELF_CHECK_WARN = re.compile(r"\[警告\]\s*自检未通过.*")
RE_METHODOLOGY_FAIL = re.compile(r"\[方法论加载失败.*\]")


def _ev(step, kind, icon, title, detail="", fallback_only=False) -> dict:
    return {"step": step, "kind": kind, "icon": icon, "title": title,
            "detail": detail, "fallback_only": fallback_only}


def _step_of(step_id: str) -> Optional[int]:
    for prefix, n in STEP_ID_PREFIXES:
        if step_id.startswith(prefix):
            return n
    return None


# ---------------- stdout 解析 ----------------

def parse_stdout_line(line: str, ctx: dict) -> list[dict]:
    """解析一行 stdout，返回 UI 事件列表（可能为空）。

    ctx["trace_id"] 会被就地更新；trace_id 行本身不产生卡片。
    """
    events: list[dict] = []
    s = line.rstrip()

    m = RE_TRACE_ID.search(s)
    if m and ctx.get("trace_id") is None:
        ctx["trace_id"] = m.group(1)
        return events  # 引导信息，不渲染卡片

    m = RE_STEP_BEGIN.search(s)
    if m:
        n = int(m.group(1))
        events.append(_ev(n, "step_start", "▶", f"Step {n}: {m.group(2)} 开始", fallback_only=True))
        return events

    m = RE_STEP_DONE.search(s)
    if m:
        n = int(m.group(1))
        events.append(_ev(n, "step_complete", "✅", f"Step {n}: {m.group(2)} 完成", fallback_only=True))
        return events

    m = RE_STEP_SKIP.search(s)
    if m:
        n = int(m.group(1))
        events.append(_ev(n, "card", "⏭", f"Step {n} 已从 checkpoint 恢复，跳过",
                          fallback_only=False))  # jsonl 不记录跳过步骤，stdout 独有
        return events

    m = RE_RESUME.search(s)
    if m:
        events.append(_ev(None, "card", "♻", f"从 checkpoint 恢复了 {m.group(1)} 个步骤"))
        return events

    if RE_MECHANICAL.search(s):
        events.append(_ev(1, "card", "⚠️", "机械信号：本轮补搜判定 unproductive",
                          _tail(s)))
        return events

    m = RE_SUPPLEMENT_STOP.search(s)
    if m and "补充" not in s:  # 排除 "[补搜] 第 N 轮补充 M 个 query"
        events.append(_ev(1, "card", "⛔", "补搜停止", _tail(s)))
        return events

    m = RE_SUPPLEMENT_ROUND.search(s)
    if m:
        events.append(_ev(1, "card", "⚡", f"补搜第 {m.group(1)} 轮：补充 {m.group(2)} 个 query",
                          fallback_only=True))  # jsonl supplement_search_done 覆盖
        return events

    m = RE_FM_NO_GAP.search(s)
    if m:
        events.append(_ev(1, "card", "✅", f"FM 审查第 {m.group(1)} 轮：无信息缺口，补搜完成",
                          fallback_only=True))  # jsonl search_gap_record 覆盖
        return events

    m = RE_FM_FOUND_GAP.search(s)
    if m:
        events.append(_ev(1, "card", "🧠", f"FM 审查第 {m.group(1)} 轮：发现信息缺口",
                          fallback_only=True))  # jsonl llm_raw_response(fm_review) 覆盖
        return events

    if RE_SEARCH_TIMEOUT.search(s):
        events.append(_ev(1, "card", "⏰", "搜索阶段整体超时兜底触发，放弃搜索", _tail(s)))
        return events

    if RE_FM_REVIEW_WARN.search(s):
        events.append(_ev(1, "card", "⚠️", "FM 审查异常", _tail(s)))
        return events

    if RE_METHODOLOGY_FAIL.search(s):
        events.append(_ev(1, "card", "⚠️", "方法论加载失败，跳过 FM 审查", _tail(s)))
        return events

    m = RE_SELF_CHECK.search(s)
    if m:
        events.append(_ev(5, "card", "🔍", f"自检结果：{m.group(1).strip()}",
                          fallback_only=True))  # jsonl step_complete(5_self_check) 覆盖
        return events

    if RE_SELF_CHECK_WARN.search(s):
        events.append(_ev(5, "card", "⚠️", "自检未通过，报告含审查警告，请人工复核"))
        return events

    m = RE_TOTAL_COST.search(s)
    if m:
        events.append(_ev(6, "card", "💰", f"总成本：{m.group(1).strip()}"))
        return events

    m = RE_REPORT_FILE.search(s)
    if m:
        events.append(_ev(6, "report_ready", "📄", "报告已生成", m.group(1).strip()))
        return events

    m = RE_QUALITY_GATE.search(s)
    if m:
        events.append(_ev(None, "error", "❌", "质量门终止", m.group(1).strip()))
        return events

    m = RE_ERROR.match(s.strip())
    if m:
        events.append(_ev(None, "error", "❌", "执行错误", m.group(1).strip()))
        return events

    if RE_LLM_KEY_WARN.search(s):
        events.append(_ev(None, "card", "⚠️", "未配置 LLM_API_KEY，已自动降级为 Mock 模式"))
        return events

    return events


def _tail(s: str, limit: int = 200) -> str:
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------- jsonl 解析 ----------------

def tail_jsonl(path: Path, offset: int) -> tuple[list[dict], int]:
    """增量读取 jsonl 文件，半行保护。

    返回 (解析出的原始事件 dict 列表, 新偏移量)。文件不存在/读失败返回 ([], offset)。
    只推进到最后一个完整行，半行留待下次重读。
    注意：必须用二进制模式——偏移量是字节单位，文本模式会把字符索引当字节用，
    中文等多字节字符会导致错位。
    """
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except (OSError, IOError):
        return [], offset
    if not chunk:
        return [], offset
    last_nl = chunk.rfind(b"\n")
    if last_nl == -1:
        return [], offset  # 整块都不完整，回退重读
    events: list[dict] = []
    for raw in chunk[:last_nl].split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # 损坏行跳过，不崩溃
    return events, offset + last_nl + 1


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t


def _parse_fm_preview(text: str) -> tuple[Optional[dict], int]:
    """解析 FM 审查 JSON。返回 (parsed_dict|None, data_gaps 近似条数)。

    text_preview 截断 1000 字符（frost_agent.py L484），超限时 JSON 不完整：
    降级为正则提取 data_gaps 条数（近似值）。
    """
    t = _strip_fences(text)
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            gaps = obj.get("data_gaps", [])
            return obj, len(gaps) if isinstance(gaps, list) else 0
    except (json.JSONDecodeError, ValueError):
        pass
    # 降级：正则提取 data_gaps 数组内的字符串条数（截断场景为近似值）
    m = re.search(r'"data_gaps"\s*:\s*\[(.*)$', t, re.DOTALL)
    if m:
        region = m.group(1)
        end = region.find("]")
        if end != -1:
            region = region[:end]
        count = len(re.findall(r'"(?:[^"\\]|\\.)*"', region))
        return None, count
    return None, 0


def parse_jsonl_event(event: dict, ctx: dict) -> list[dict]:
    """解析一条 jsonl 事件，返回 UI 事件列表。"""
    etype = event.get("event_type", "")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    events: list[dict] = []

    if etype == "start":
        mode = "Mock" if data.get("mock") else "真实 API"
        events.append(_ev(None, "card", "🚀",
                          f"任务开始：{data.get('industry', '?')}（{mode}）",
                          f"trace_id: {data.get('trace_id', '?')}"))

    elif etype == "step_start":
        n = _step_of(data.get("step_id", ""))
        if n:
            events.append(_ev(n, "step_start", "▶",
                              f"Step {n}: {STEP_LABELS.get(n, '?')} 开始"))

    elif etype == "step_complete":
        n = _step_of(data.get("step_id", ""))
        if n:
            if n == 1 and data.get("confidence"):
                detail = f"置信度：{data['confidence']}"
            elif n == 5:
                failed = data.get("failed") or []
                detail = f"结果：{data.get('overall', '?')}" + (
                    f"；失败维度：{', '.join(failed)}" if failed else "；失败维度：无")
            else:
                flags = data.get("quality_flags_count", 0)
                detail = f"降级标记：{flags} 个" if flags else ""
            events.append(_ev(n, "step_complete", "✅",
                              f"Step {n}: {STEP_LABELS.get(n, '?')} 完成", detail))

    elif etype == "llm_raw_response":
        step_id = data.get("step_id", "")
        if "fm_review" in step_id:
            round_label = data.get("round_label", "")
            parsed, gap_count = _parse_fm_preview(data.get("text_preview", ""))
            if parsed is not None:
                gaps = parsed.get("data_gaps", []) or []
                queries = parsed.get("suggested_queries", []) or []
                title = f"FM 审查{round_label}：发现 {len(gaps)} 个信息缺口" if gaps \
                    else f"FM 审查{round_label}：无信息缺口"
                lines = [f"· {g}" for g in gaps[:2]]
                if len(gaps) > 2:
                    lines.append(f"…等共 {len(gaps)} 条")
                if parsed.get("yield_evidence"):
                    lines.append(f"上轮收获：{_tail(str(parsed['yield_evidence']), 120)}")
                if queries:
                    lines.append(f"建议补搜 {len(queries)} 个 query")
                events.append(_ev(1, "card", "🧠", title, "\n".join(lines)))
            elif gap_count > 0:
                events.append(_ev(1, "card", "🧠",
                                  f"FM 审查{round_label}：发现约 {gap_count} 个信息缺口（原文截断，条数为近似值）",
                                  _tail(data.get("text_preview", ""), 200)))
            else:
                events.append(_ev(1, "card", "🧠", f"FM 审查{round_label}：完成（返回非结构化）",
                                  _tail(data.get("text_preview", ""), 200)))
        else:
            n = _step_of(step_id)
            events.append(_ev(n, "card", "📝", "LLM 生成完成"))

    elif etype == "supplement_search_done":
        rnd = data.get("round", "?")
        results = data.get("results_per_query", {}) or {}
        queries = data.get("queries", []) or []
        lines = [f"· {q} → {results.get(q, 0)} 条" for q in queries[:3]]
        if len(queries) > 3:
            lines.append(f"…等共 {len(queries)} 个 query")
        events.append(_ev(1, "card", "⚡", f"补搜第 {rnd} 轮：{len(queries)} 个 query",
                          "\n".join(lines)))

    elif etype == "search_gap_record":
        stop_reason = data.get("stop_reason", "unknown")
        rounds = data.get("supplement_rounds", 0)
        remaining = data.get("remaining_gaps", []) or []
        # v1.4：映射表补全至当前枚举（v1.4起新增 no_justification；low_yield 已废弃保留兼容）
        reason_zh = {
            "gaps_closed": "缺口全部闭合",
            "budget_exhausted": "达到补搜轮数/预算上限",
            "query_space_exhausted": "补搜关键词空间穷尽",
            "no_justification": "无有效继续理由，停止补搜",
            "no_suggested_queries": "FM 未生成补搜关键词",
            "fm_review_failed": "FM 审查失败",
            "low_yield": "收益止损（v1.4 已废弃）",
            # 旧枚举兼容（v1.2 之前的历史 trace）
            "max_rounds": "达到补搜轮数上限",
            "mechanical_stop": "机械信号止损",
            "queries_exhausted": "补搜关键词空间穷尽",
            "fm_no_suggestion": "FM 未生成补搜关键词",
        }.get(stop_reason, stop_reason)
        detail = f"补搜 {rounds} 轮；剩余缺口 {len(remaining)} 个"
        if data.get("shadow_mode"):
            detail += "（影子模式）"
        if remaining:
            detail += "\n· " + "\n· ".join(str(g) for g in remaining[:2])
        events.append(_ev(1, "card", "📊", f"搜索阶段终态：{reason_zh}", detail))

    elif etype == "self_check_failed":
        failed = data.get("failed_dimensions", []) or []
        events.append(_ev(5, "card", "⚠️", "自检未通过",
                          f"失败维度：{', '.join(failed)}" if failed else ""))

    elif etype == "complete":
        events.append(_ev(6, "card", "📄", "报告生成完成",
                          f"报告长度：{data.get('report_length', '?')} 字符"))

    return events
