"""
行业定义 Agent — 主程序 v5.2 (阶段二 A 组)

六步执行流程（严格线性，不做 Evaluator-Optimizer 闭环）：
  Step 1: 信息收集（并行搜索 + LLM 总结 + v5.2 搜索补搜循环）
  Step 2: 维度筛选（应用方法论 H1-H4）
  Step 3: 结构决策（设计报告章节结构）
  Step 4: 内容生成（撰写完整报告 + v5.2 内容校验）
  Step 5: 自检（独立 Evaluator，失败时注入警告而非自动修正）
  Step 6: 输出（组装最终报告 + v5.2 quality_flags 汇总 + OutputSafety + TokenAudit）

v5.2 相比 v4 的变更：
- Orchestrator 统一生成 trace_id，注入 SessionEventLog 和 TokenAudit
- Step 1 新增搜索补搜循环（FM 审查 + 最多 2 个补搜 query，总共 ≤5 个 query）
- Step 4 新增内容校验（len(report_text) < 500 时 raise）
- 生产步骤（Step 1-4）触发 or_fallback_result(high) 时终止流程（QualityGateError）
- Step 6 使用 OutputSafety 安全保存（UTC 时间戳 + 版本号上限）
- Step 6 使用 TokenAudit 持久化成本报表（JSON + Markdown）
- Step 6 报告尾部汇总 quality_flags（按严重度分组）
- Token 统计移出报告正文，CLI 保留成本摘要
- STEP4_MAX_TOKENS 默认值 16000 → 10000（P0-4 实测推荐值）
- call_with_timeout 传入 max_retries 参数
- 搜索全失败时终止流程（P1-10）

v4 继承（保持不变）：
- 六步严格线性执行（不做 Evaluator-Optimizer 闭环）
- Step 5 失败时注入警告，不自动重跑 Step 4
- Context Builder 四层组装
- Mock LLM 逻辑保留（用于单元测试）

使用方式：
  python frost_agent.py "低空经济物流"
  python frost_agent.py "低空经济物流" --mock
  python frost_agent.py "低空经济物流" --resume
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib  # v1.3 新增：内容指纹计算
import json
import os
import sys
import time
import uuid  # v5.2 新增：Orchestrator 统一生成 trace_id
from pathlib import Path
from typing import Any, Callable, Optional

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

from models import (
    ReportState, StepOutput, StepBudget, STEP_BUDGETS,
    QualityFlag, QualityGateError, flag_search_partial_failure,  # v5.2 新增
)
from context_builder import ContextBuilder
from evaluator import evaluate, mock_evaluate
from search import search_with_fallback, search_single_query, mock_search  # v5.2 新增 search_single_query
from methodology_loader import MethodologyLoader  # v5.2 新增
from harness.circuit_breaker import call_with_timeout
from harness.session_log import SessionEventLog  # v5.2 升级（替代 SimpleLogger）
from harness.checkpoint import CheckpointManager  # v5.2 升级（替代 save_checkpoint/try_resume）
from harness.token_audit import TokenAudit  # v5.2 新增
from harness.output_safety import OutputSafety  # v5.2 新增


# ============================================================
# 配置常量
# ============================================================

DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-v4-pro"

# Step 4 max_tokens：P0-1 实测推荐值 10000
# v5.2 P0-4 修正：默认值从 16000 改为 10000（阶段一收尾二分查找实测推荐值）
# 用法：STEP4_MAX_TOKENS=12000 python3 frost_agent.py "低空经济物流"
STEP4_MAX_TOKENS = int(os.getenv("STEP4_MAX_TOKENS", "10000"))

# 六步定义（Step 6 为输出组装，无 LLM 调用，故不列入 LLM 步骤列表）
STEPS_DEFINITION = [
    ("1_info_collection",       "信息收集"),
    ("2_dimension_screening",   "维度筛选"),
    ("3_structure_decision",    "结构决策"),
    ("4_content_generation",    "内容生成"),
    ("5_self_check",            "自检"),
]

# 各步骤引用的方法论章节
METHODOLOGY_REFS = {
    "1_info_collection":      "§3.2 信息优先级(P0-P3) + §6 参考框架(GICS/NAICS)",
    "2_dimension_screening":  "§3.1 维度筛选原则(H1-H4) + §5 自检清单",
    "3_structure_decision":   "§3.4 报告结构启发式 + §3.3 范围约束",
    "4_content_generation":   "全文(R1-R5 + §4 推理展示要求)",
    "5_self_check":           "§5 自检清单(C1-C5)",
}

# B1-2：搜索补搜循环常量（v1.1：按轮数计数，废弃按 query 计数的旧语义）
# 旧 MAX_SUPPLEMENT_QUERIES=2 数 query，FM 每轮建议 2 个 → 真实语义是"只允许 1 轮补搜"
MAX_SUPPLEMENT_ROUNDS = int(os.getenv("MAX_SUPPLEMENT_ROUNDS", "3"))
MAX_TOTAL_QUERIES = int(os.getenv("MAX_TOTAL_QUERIES", "10"))

# v5.2 修复 P2 #4：FM 审查单次超时阈值，30s→60s，可经环境变量覆盖
_FM_REVIEW_TIMEOUT = float(os.getenv("FM_REVIEW_TIMEOUT", "60"))

# B1-2：搜索阶段外层兜底超时（300s→400s）
# 最坏情况：首轮搜索 ~16s + 5 次 FM 审查 × 60s + 6 个补搜 query × ~8s ≈ 364s < 400s
SEARCH_PHASE_TIMEOUT = int(os.getenv("SEARCH_PHASE_TIMEOUT", "400"))

# B1-2 v1.4：前瞻继续论证配置（范式反转：默认不搜下一轮，除非给出继续理由）
# 保底轮数：第1轮补搜无条件放行，第2轮起要求有效继续理由
MIN_GUARANTEED_ROUNDS = int(os.getenv("MIN_GUARANTEED_ROUNDS", "1"))
# 影子模式：true 时继续理由照常要求/验证/记录，但理由无效不拦截（v1.3 STOP_LOSS_SHADOW_MODE 改名，
# v1.4 罩的是理由门控而非止损；该变量无外部依赖，直接改不留别名）
JUSTIFICATION_SHADOW_MODE = os.getenv("JUSTIFICATION_SHADOW_MODE", "true").lower() == "true"
# 指纹阈值（v1.4 降为纯审计，不参与任何拦截）
FINGERPRINT_OVERLAP_THRESHOLD = float(os.getenv("FINGERPRINT_OVERLAP_THRESHOLD", "0.8"))

# v5.2 新增：生产步骤集合（触发 or_fallback_result 时终止流程）
PRODUCTION_STEPS = {
    "1_info_collection", "2_dimension_screening",
    "3_structure_decision", "4_content_generation",
}

# v5.2 新增：FM 审查 prompt（基于方法论"信息优先级"）；v1.4 重写：前瞻继续论证范式
FM_REVIEW_PROMPT = """你是行业定义信息完整性审查员。你的任务是判断当前搜索结果是否覆盖了行业定义所需的关键信息维度，并论证是否值得继续补搜。

## 行业
{industry_name}

## 信息优先级（来自方法论）
{methodology_info_priority}

## 当前搜索结果摘要
{search_results_summary}

## 已试 query 清单（生成 suggested_queries 时避免重复，换角度如换英文/标准号/机构名定点搜）
{seen_queries_list}

## 你的任务
1. 对照"信息优先级"，判断当前搜索结果是否有明显缺失的**事实性信息**维度
2. **只报告可通过搜索补全的事实性信息缺口**——以下不属于 data_gaps：
   - 维度选择/放弃的理由说明（属于报告推理义务，R2规则）
   - 结构性特征与当前热点的区分（属于报告推理义务，C3自检项）
   - 任何"为什么选择X而非Y"的论证（属于报告推理义务）
   若发现上述推理义务类缺口，在内部识别后从 data_gaps 中排除，不写入返回列表
3. 为每个事实性缺口标注 `gap_type`：
   - `not_found`：信息可能不存在（如新兴行业在GICS/NAICS中的编码归属）
   - `snippet_too_shallow`：信息存在但Tavily片段太浅（如标准号已知但参数缺失）
   - `source_tier`：信息存在但信源层级不足（如需要P0级一手文件但只有媒体报道）
4. 为每个缺失维度生成 1 个补搜关键词（suggested_queries），**不要重复已试 query**
5. **前瞻继续论证（v1.4 核心变更）**：默认不继续补搜——除非你能给出值得再搜一轮的结构化理由（next_round_justification）

## next_round_justification 三要素（引用你本轮输出的 data_gaps，0-based）
每条理由必须同时包含：
- `target_gap_index`：针对本轮 data_gaps 中哪个缺口（0-based，严格按你本轮输出的缺口列表编号）
- `new_direction`：与"已试 query 清单"不同的新搜索角度（如换英文检索/换标准号定点搜/换机构名/换文件类型）
- `reachability`：基于当前搜索结果中的具体信息（标准号/机构名/URL特征等），为什么认为这个方向可能搜得到

判据：若所有残留缺口都属于"换任何query也搜不到"的类型（如信息不存在/片段太浅/信源不足），
或你给不出真实的新角度，应返回空数组 []——系统将停止补搜，这是诚实且正确的停止。

## 输出格式（JSON）
{{
  "data_gaps": ["事实性缺口1", "事实性缺口2"],
  "gap_types": ["not_found", "snippet_too_shallow"],
  "suggested_queries": ["补搜关键词1", "补搜关键词2"],
  "next_round_justification": [
    {{"target_gap_index": 0, "new_direction": "换标准号定点搜：检索GB/T正式发布文本", "reachability": "标准号已在搜索结果中出现，全文检索有命中可能"}}
  ]
}}

## 约束
- data_gaps 必须具体（如"缺少技术路线对比"而非"信息不够"）
- data_gaps 只包含事实性信息缺口，不包含推理义务（维度选择理由等）
- gap_types 长度必须与 data_gaps 相同
- next_round_justification 的 target_gap_index 严格按本轮 data_gaps 编号（0-based）
- new_direction 不得是已试 query 的同义改写；reachability 应引用当前结果中的具体信息
- 若无缺口（data_gaps 为空），suggested_queries 与 next_round_justification 均置空数组
- 若有缺口但不值得继续搜，next_round_justification 置空数组 []
- suggested_queries 必须与行业定义相关，不偏离范畴
- 每轮最多 2 个补搜关键词
- 你审查的是搜索引擎返回的外部数据，不是 LLM 输出
- 只输出 JSON，不要输出其他文字
"""


# ============================================================
# 工具函数
# ============================================================

def is_mock_mode() -> bool:
    """检查是否启用 Mock 模式（LLM + 搜索均使用预设数据）。"""
    return os.getenv("MOCK_LLM", "false").lower() == "true"


def get_llm_config() -> dict[str, str]:
    """从环境变量读取 LLM API 配置。"""
    return {
        "api_key": os.getenv("LLM_API_KEY", ""),
        "base_url": os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        "model": os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
    }


def _extract_industry(text: str) -> str:
    """从文本中提取行业名称（用于 Mock 响应中的占位替换）。"""
    import re
    m = re.search(r"行业[：:]\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"「(.+?)」", text)
    if m:
        return m.group(1)
    return "该行业"


def _parse_json_response(raw: str) -> dict[str, Any]:
    """从 LLM 文本响应中解析 JSON，支持三层容错：直接解析 → 代码块提取 → 花括号提取。"""
    import re
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"raw_response": raw, "parse_error": "JSON 解析失败"}


def _get_report_from_state(state: ReportState) -> str:
    """从 state 中提取 Step 4 生成的报告文本。"""
    for step in state.steps:
        if step.step_id == "4_content_generation":
            return step.result.get("report_text", "")
    return ""


def _strip_preamble(text: str) -> str:
    """剥离 LLM 在报告正文前附加的开场白。"""
    import re
    m = re.search(r"^#{1,4}\s+", text, re.MULTILINE)
    if m:
        if m.start() > 0:
            return text[m.start():].lstrip("\n")
        return text
    m = re.search(r"^---", text, re.MULTILINE)
    if m and m.start() > 0:
        stripped = text[m.start():].lstrip("\n")
        if len(stripped) > 50:
            return stripped
    return text


# ============================================================
# v5.2 新增：质量门检查（B1-1 重构：基于 terminates_flow 终止）
# ============================================================

def _check_quality_gate(step_output: StepOutput, step_id: str) -> None:
    """B1-1 重构：基于 terminates_flow 元数据统一判断终止条件（SSOT）。

    替代原 v5.2 硬编码 category == 'or_fallback_result' 的方式。
    任何 flag 设置 terminates_flow=True 且 severity='high' 时触发终止。
    新增需终止的 category 时，只需在创建 QualityFlag 实例时设 terminates_flow=True，
    无需修改本函数。

    Args:
        step_output: 刚完成的步骤输出
        step_id: 步骤标识

    Raises:
        QualityGateError: 当 step_output.quality_flags 含任何 terminates_flow=True 的 flag 时
    """
    if step_id not in PRODUCTION_STEPS:
        return
    terminating_flags = [
        f for f in step_output.quality_flags
        if f.terminates_flow and f.severity == "high"
    ]
    if terminating_flags:
        first = terminating_flags[0]
        raise QualityGateError(
            f"步骤 {step_id} 触发终止性降级：{first.category}/{first.field} — {first.detail}。"
            f"无法继续生成报告。请重跑。"
            f"（共 {len(terminating_flags)} 个终止性 flag）"
        )


# ============================================================
# v5.2 新增：quality_flags 汇总到报告尾部
# ============================================================

def _build_quality_flags_summary(state: ReportState) -> str:
    """汇总所有步骤的 quality_flags 到报告尾部。

    v5.1 修正（评议 Q3）：报告尾部只保留自检警告 + quality_flags 汇总 + 方法论附注。
    Token 统计移到独立的 TokenAudit 报表，不在报告正文中显示。
    """
    all_flags: list[QualityFlag] = []
    for step in state.steps:
        all_flags.extend(step.quality_flags)

    if not all_flags:
        return ""

    lines = ["\n\n---\n\n## ⚠️ 降级记录（quality_flags）\n"]
    high_flags = [f for f in all_flags if f.severity == "high"]
    medium_flags = [f for f in all_flags if f.severity == "medium"]
    low_flags = [f for f in all_flags if f.severity == "low"]

    if high_flags:
        lines.append("### 高严重度（影响报告质量，建议人工复核）\n")
        for f in high_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")
    if medium_flags:
        lines.append("\n### 中严重度（有降级但质量可接受）\n")
        for f in medium_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")
    if low_flags:
        lines.append("\n### 低严重度（仅记录）\n")
        for f in low_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")

    return "\n".join(lines)


# ============================================================
# v5.2 新增：Step 1 搜索补搜循环辅助函数
# ============================================================

def _extract_info_priority(methodology_text: str) -> str:
    """从方法论切片中提取"信息优先级"章节内容。"""
    import re
    # 匹配"信息优先级"标题到下一个同级或上级标题
    m = re.search(
        r"(###?\s*.*?信息优先级.*?)(?=\n###?\s|\n##\s|\Z)",
        methodology_text,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    # 兜底：返回切片前 2000 字符
    return methodology_text[:2000]


def _summarize_search_results(results: dict[str, list[dict]]) -> str:
    """将搜索结果汇总为 FM 审查可读的摘要文本。"""
    lines: list[str] = []
    for query, items in results.items():
        lines.append(f"### Query: {query}")
        if not items:
            lines.append("  （无结果）")
            continue
        for i, item in enumerate(items[:3], 1):  # 每个 query 最多 3 条
            title = item.get("title", "")[:80]
            content = item.get("content", "")[:200]
            lines.append(f"  {i}. [{title}]")
            lines.append(f"     {content}")
        if len(items) > 3:
            lines.append(f"  ...（共 {len(items)} 条结果）")
    return "\n".join(lines)


def _record_fm_failure_flag(
    quality_flags: list,
    error_type: str,
    round_label: str,
    fm_result: dict,
) -> None:
    """v5.2 修复 P2 #5：统一记录 FM 审查失败 flag（循环内 + 最终审查复用）。

    detail 使用 `[type=xxx]` 结构化前缀，便于离线统计失败原因分布（回应 architecture-critic P2-2）。

    Args:
        quality_flags: 待追加的 flag 列表
        error_type: timeout / parse_error / exception / empty
        round_label: 如 "第 1 轮" / "最终审查"
        fm_result: _fm_review_search_results 的返回值，用于提取异常信息
    """
    detail_map = {
        "timeout": f"[type=timeout] FM 审查{round_label}超时（{_FM_REVIEW_TIMEOUT}s）",
        "parse_error": f"[type=parse_error] FM 审查{round_label}返回非 JSON",
        "exception": f"[type=exception] FM 审查{round_label}异常：{fm_result.get('_error_msg', '')}",
        "empty": f"[type=empty] FM 审查{round_label}返回空结果",
    }
    quality_flags.append(QualityFlag(
        category="fm_review_skipped",  # v5.2 修复：统一专用 category
        field="fm_review",
        severity="medium",
        detail=detail_map.get(error_type, f"[type=unknown] FM 审查{round_label}未知错误"),
    ))


def _mechanical_yield_judgment(
    queries_this_round: list[str],
    results_per_query: dict[str, int],
    seen_queries: set[str],
) -> str:
    """v1.2：机械信号收益判定。返回 'productive' | 'unproductive'。

    零 LLM 成本、可单测。v1.4 起降为纯审计信号（mechanical_history 字段），不参与任何拦截。
    覆盖局限：无法捕获"不同query返回相似内容"场景（该场景由指纹审计同记录）。

    判定规则（按优先级）：
    1. 全部重复query → unproductive（步骤1去重后应0次触发，作安全网）
    2. 全部零返回 → unproductive
    3. 其他 → productive（保守，不轻易误判）
    """
    # 信号1：全部重复（步骤1去重后理论上不会发生，作安全网）
    if all(q.strip() in seen_queries for q in queries_this_round):
        return "unproductive"

    # 信号2：全部零返回
    if all(results_per_query.get(q, 0) == 0 for q in queries_this_round):
        return "unproductive"

    return "productive"


def _make_fingerprint(item: dict) -> str:
    """v1.3 信号2：单条搜索结果指纹。URL优先，URL为空时fallback到内容前200字符。

    URL相同 = 同一页面 = 信息必然重复，且字符串相等比对零成本；
    内容hash可捕获镜像/转载（不同URL同内容），URL为空时兜底。
    """
    url = (item.get("url") or "").strip()
    if url:
        return f"url:{url}"
    content = (item.get("content") or "")[:200]
    return f"content:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


def _content_fingerprint_overlap(
    round_items: list[dict],
    historical_fingerprints: set[str],
    threshold: float = FINGERPRINT_OVERLAP_THRESHOLD,
) -> str:
    """v1.3 信号2：本轮结果与全历史指纹集合的重叠判定。

    重叠率 = 本轮中已存在于历史集合的条目数 / 本轮总条目数（不去重计数：
    同一URL在本轮2个query各返回一次算2条——都返回老页面即无新信息的语义成立）。

    与全部历史比对（非仅上一轮）：捕获"第3轮返回第1轮内容"的跨轮回归。

    Returns:
        'unproductive'：重叠率 >= threshold
        'productive'：重叠率 < threshold，或本轮无有效条目（零返回由机械信号负责，职责分离）
    """
    if not round_items:
        return "productive"
    fps = [_make_fingerprint(r) for r in round_items]
    overlap = sum(1 for fp in fps if fp in historical_fingerprints)
    return "unproductive" if overlap / len(fps) >= threshold else "productive"


def _validate_justification(
    justification: Any,
    current_data_gaps: list[str],
) -> bool:
    """v1.4：验证FM继续理由有效性。任一条有效即返回True（前瞻继续论证闸门）。

    验证规则（按方案§3.1只做两层：非空+index合法，不做内容二次验证）：
    1. 非数组（含v1.3旧格式字符串/None）→ 无效
    2. 数组为空 → 无效（= 给不出理由 → 不支持继续）
    3. 元素非dict / 缺 target_gap_index/new_direction/reachability → 该条无效
    4. target_gap_index 为 bool → 该条无效（bool是int子类，True==1会穿透isinstance检查）
    5. target_gap_index 非整数或超出当前缺口列表范围 → 该条无效
    6. new_direction / reachability 为空字符串 → 该条无效

    注：new_direction"是否真的新"不在此验证——由机器质检（query去重）+人工抽查把关。

    Args:
        justification: FM返回的继续理由（应为 [{"target_gap_index": int, "new_direction": str, "reachability": str}]）
        current_data_gaps: 本轮FM自己输出的缺口列表（验证基准，同源自引用，无跨轮错位）
    """
    if not isinstance(justification, list) or not justification:
        return False
    for item in justification:
        if not isinstance(item, dict):
            continue
        gi = item.get("target_gap_index")
        new_direction = item.get("new_direction", "")
        reachability = item.get("reachability", "")
        if isinstance(gi, bool):
            continue
        if not isinstance(gi, int):
            continue
        if gi < 0 or gi >= len(current_data_gaps):
            continue
        if not (new_direction or "").strip() or not (reachability or "").strip():
            continue
        return True  # 任一条有效
    return False


async def _fm_review_search_results(
    industry_name: str,
    methodology_info_priority: str,
    search_results_summary: str,
    llm_call_fn: Callable,
    logger: Optional[SessionEventLog] = None,
    round_label: str = "",
    seen_queries_list: str = "（首轮无已试 query）",  # v1.2 步骤3：注入已试query清单
) -> dict[str, Any]:
    """FM 审查搜索结果，返回 data_gaps + gap_types + suggested_queries + next_round_justification。

    v1.4 范式重写：移除 previous_round_info/last_round_yield/yield_evidence（回顾性机制废弃），
    新增 next_round_justification（前瞻继续论证）。理由引用FM同响应内的 data_gaps，无跨轮错位。
    v1.2 新增：seen_queries_list 参数 + gap_types 返回字段。
    v5.2 修复 P2 #4/#5/#3：
    - 超时阈值 30s → _FM_REVIEW_TIMEOUT（默认 60s，可经环境变量覆盖）
    - 区分 timeout / parse_error / exception 三种失败，返回 {"_error_type": ...}
    - 记录 llm_raw_response 日志（含 round_label），便于审计 FM 审查 LLM 调用

    Args:
        industry_name: 行业名
        methodology_info_priority: 方法论"信息优先级"章节文本
        search_results_summary: 搜索结果摘要文本
        llm_call_fn: LLM 调用函数
        logger: 可选的 SessionEventLog
        round_label: 轮次标签
        seen_queries_list: 已试query清单文本（v1.2 步骤3，注入prompt防止FM重复建议）

    Returns:
        成功：{"data_gaps": [...], "gap_types": [...], "suggested_queries": [...], "next_round_justification": [...]}
        超时：{"_error_type": "timeout"}
        解析失败：{"_error_type": "parse_error"}
        其他异常：{"_error_type": "exception", "_error_msg": str}
    """
    prompt = FM_REVIEW_PROMPT.format(
        industry_name=industry_name,
        methodology_info_priority=methodology_info_priority,
        search_results_summary=search_results_summary,
        seen_queries_list=seen_queries_list,
    )

    try:
        result = await call_with_timeout(
            lambda: llm_call_fn(
                system_prompt="你是行业定义信息完整性审查员。",
                user_prompt=prompt,
                max_tokens=2000,
                reasoning_effort="none",  # B1-2：FM 审查是 JSON 格式判断，关闭思考避免 content 为空
            ),
            timeout_seconds=_FM_REVIEW_TIMEOUT,  # v5.2 修复 P2 #4：30s → 60s（可配置）
            max_retries=1,
        )
        # v5.2 修复 P2 #3：记录 FM 审查的 LLM 调用
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        if logger is not None:
            logger.log("llm_raw_response", {
                "step_id": "1_info_collection_fm_review",
                "round_label": round_label,
                "text_preview": text[:1000],
            })
        parsed = _parse_json_response(text)
        if "parse_error" in parsed:
            print(f"  [FM 审查 JSON 解析失败] {round_label}：返回非 JSON")
            return {"_error_type": "parse_error"}  # v5.2 修复 P2 #5
        return {
            "data_gaps": parsed.get("data_gaps", []),
            "gap_types": parsed.get("gap_types", []),
            "suggested_queries": parsed.get("suggested_queries", []),
            "next_round_justification": parsed.get("next_round_justification", []),  # v1.4（验证函数容忍非list）
        }
    except asyncio.TimeoutError:
        # v5.2 修复 P2 #4/#5：区分超时
        print(f"  [FM 审查超时] {round_label}（timeout={_FM_REVIEW_TIMEOUT}s），跳过")
        return {"_error_type": "timeout"}
    except Exception as e:
        # v5.2 修复 P2 #5：区分其他异常（网络/API 错误等）
        print(f"  [FM 审查异常] {round_label} {type(e).__name__}: {e}")
        return {"_error_type": "exception", "_error_msg": str(e)}


async def step1_search_with_supplement(
    industry_name: str,
    tavily_api_key: str,
    methodology_loader: MethodologyLoader,
    llm_call_fn: Callable,
    mock_search_mode: bool = False,
    logger: Optional[SessionEventLog] = None,  # v5.2 修复 P2 #3
) -> tuple[dict[str, list[dict]], list[QualityFlag], int]:
    """v5.2 新增：Step 1 搜索 + FM 审查补搜循环。

    不改 search.py 接口，循环封装在此函数内部。

    流程：
    1. 首轮 3 个静态模板搜索（v4 逻辑，通过 search_with_fallback）
    2. FM 审查搜索结果（基于方法论"信息优先级"）
    3. 若有信息缺口且 FM 能生成补搜关键词 → 补搜，最多 2 个补搜 query
    4. 总共 ≤5 个 query
    5. 补搜后仍有缺口记录 data_gaps_remaining（medium）

    P0-3 修正：最多 2 个补搜 query（不是 2 轮），与预算逻辑一致。
    P2-5.12：补搜改并行（asyncio.gather）。
    v5.2 修复 P2 #3：传入 logger 以记录 FM 审查 LLM 调用。

    Args:
        industry_name: 行业名
        tavily_api_key: Tavily API 密钥
        methodology_loader: 方法论加载器
        llm_call_fn: LLM 调用函数
        mock_search_mode: 是否使用 Mock 搜索
        logger: 可选的 SessionEventLog，传入则记录 FM 审查 LLM 调用

    Returns:
        (all_results, quality_flags, error_count)
        all_results: {query: [items]} 格式的搜索结果
        quality_flags: 降级标记列表
        error_count: 失败的 query 数
    """
    quality_flags: list[QualityFlag] = []

    # 1. 首轮：3 个静态模板搜索（v4 逻辑不变）
    if mock_search_mode or not tavily_api_key:
        mock_result = mock_search(industry_name)
        all_results: dict[str, list[dict]] = mock_result["results"]
        error_count = mock_result.get("error_count", 0)
    else:
        first_round = await search_with_fallback(industry_name, tavily_api_key)
        all_results = first_round["results"]
        error_count = first_round.get("error_count", 0)

    queries_used = len(all_results)

    # P1-10：搜索全失败终止（不基于空搜索结果生成报告）
    if error_count >= queries_used and queries_used > 0:
        quality_flags.append(QualityFlag(
            category="search_partial_failure",
            field="all_queries",
            severity="high",
            detail=f"所有 {queries_used} 个搜索 query 全部失败，无法继续",
            terminates_flow=True,  # B1-1：SSOT 元数据，_check_quality_gate 统一扫描
        ))
        return all_results, quality_flags, error_count

    # Mock 模式跳过 FM 审查（无真实搜索结果可审查）
    if mock_search_mode or not tavily_api_key:
        return all_results, quality_flags, error_count

    # 2. 加载方法论"信息优先级"章节
    try:
        methodology_slice = methodology_loader.load_slice("1_info_collection")
        info_priority = _extract_info_priority(methodology_slice)
    except Exception as e:
        print(f"  [方法论加载失败，跳过 FM 审查] {e}")
        return all_results, quality_flags, error_count

    # B1-2：FM 审查 + 补搜循环（v1.4：前瞻继续论证范式）
    # v1.2：seen_queries 去重（strip 规范化）
    # v1.4：默认不搜下一轮，除非FM给出有效继续理由（三要素）；保底轮内无条件放行；
    #       移除v1.3全部回顾性机制（fm_effective/三信号OR/None断链/consecutive/low_yield）；
    #       指纹/机械信号降为纯审计采集
    supplement_rounds_used = 0
    supplement_queries_used = 0
    stop_reason = ""
    prev_data_gaps: list = []
    prev_suggested_queries: list = []
    seen_queries: set[str] = {q.strip() for q in all_results.keys()}  # 首轮3个query入集合
    # v1.4 审计状态
    justification_history: list = []         # 每轮FM继续理由原样落盘（审计主数据源）
    justification_valid_history: list = []   # 每轮理由验证结果
    round_gap_types: list = []               # 每轮审查的gap_types（r3：支持gap_type门控对照分析）
    round_partial_signals: list[dict] = []   # 每轮审计信号（指纹+机械，纯记录不拦截），1-based补搜轮编号
    # 首轮静态搜索结果指纹预填充历史集合（审计基准）
    historical_fingerprints: set[str] = {
        _make_fingerprint(r)
        for items in all_results.values()
        for r in items
        if r.get("title") != "搜索失败"
    }

    for round_num in range(MAX_SUPPLEMENT_ROUNDS):
        if queries_used >= MAX_TOTAL_QUERIES:
            stop_reason = "budget_exhausted"
            break

        # FM 审查（v1.4：无previous_round_info——理由引用当前轮缺口清单，同源自引用）
        search_summary = _summarize_search_results(all_results)
        # v1.2 步骤3：构造已试query清单文本（注入prompt防止FM重复建议）
        seen_queries_list = "\n".join(f"  - {q}" for q in sorted(seen_queries)) if seen_queries else "（无）"

        fm_result = await _fm_review_search_results(
            industry_name, info_priority, search_summary, llm_call_fn,
            logger=logger, round_label=f"第 {round_num + 1} 轮",
            seen_queries_list=seen_queries_list,
        )

        # FM 失败（补记既有行为：记 flag + break）
        if not fm_result or "_error_type" in fm_result:
            error_type = fm_result.get("_error_type", "empty") if fm_result else "empty"
            _record_fm_failure_flag(quality_flags, error_type, f"第 {round_num + 1} 轮", fm_result or {})
            stop_reason = "fm_review_failed"
            break

        data_gaps = fm_result.get("data_gaps", [])
        suggested_queries = fm_result.get("suggested_queries", [])
        gap_types = fm_result.get("gap_types", [])
        justification = fm_result.get("next_round_justification", [])

        # v1.4：理由验证 + 审计记录（验证基准=本轮FM自己输出的data_gaps，同源无错位）
        justification_valid = _validate_justification(justification, data_gaps)
        justification_history.append(justification)
        justification_valid_history.append(justification_valid)
        round_gap_types.append((gap_types or [])[:len(data_gaps)])

        # 信号 A：缺口闭合
        if not data_gaps:
            stop_reason = "gaps_closed"
            print(f"  [FM 审查第 {round_num + 1} 轮] 无信息缺口，补搜完成")
            break

        # v1.4 核心门控：保底轮后要求有效继续理由（影子模式下仅记录不拦截）
        # 时序保证：理由验证在query去重判定之前（P值分母不被硬闸门污染，方案§3.6）
        if round_num >= MIN_GUARANTEED_ROUNDS and not justification_valid:
            if JUSTIFICATION_SHADOW_MODE:
                print(f"  [理由门控-影子] 第 {round_num + 1} 轮继续理由缺失/无效，影子模式仅记录不拦截")
            else:
                stop_reason = "no_justification"
                print(f"  [FM 审查第 {round_num + 1} 轮] 有缺口但无有效继续理由，停止补搜（前瞻论证范式）")
                break

        # 安全网：轮数上限
        if round_num + 1 >= MAX_SUPPLEMENT_ROUNDS:
            stop_reason = "budget_exhausted"
            print(f"  [补搜] 达到轮数上限 {MAX_SUPPLEMENT_ROUNDS}，停止")
            break

        # FM 未生成补搜关键词
        if not suggested_queries:
            stop_reason = "no_suggested_queries"
            print(f"  [FM 审查第 {round_num + 1} 轮] 有缺口但 FM 未生成补搜关键词，停止")
            break

        print(f"  [FM 审查第 {round_num + 1} 轮] 发现缺口: {data_gaps}")

        # 执行补搜（FM 建议的全部 query，受 MAX_TOTAL_QUERIES 约束）
        # v1.2 步骤1：执行前去重（strip 规范化），避免重复 query 白烧预算
        remaining_budget = MAX_TOTAL_QUERIES - queries_used
        new_queries = [q for q in suggested_queries if q.strip() not in seen_queries]
        queries_to_search = new_queries[:remaining_budget]

        if not queries_to_search:
            if not new_queries:
                stop_reason = "query_space_exhausted"  # FM 建议的全部 query 已试过
                print(f"  [补搜] 第 {round_num + 1} 轮 FM 建议的 query 全部已试过，关键词空间穷尽")
            else:
                stop_reason = "budget_exhausted"  # 有新 query 但预算用尽
            break

        # 补搜并行（执行前不更新 seen_queries，避免机械信号误判本轮query为重复）
        tasks = [search_single_query(q, tavily_api_key) for q in queries_to_search]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for query, result in zip(queries_to_search, gathered):
            if isinstance(result, Exception):
                all_results[query] = [{"title": "搜索失败", "url": "", "content": str(result)}]
                error_count += 1
            else:
                if result and "搜索失败" in result[0].get("title", ""):
                    error_count += 1
                all_results[query] = result
            queries_used += 1
            supplement_queries_used += 1

        supplement_rounds_used += 1
        prev_data_gaps = data_gaps
        prev_suggested_queries = suggested_queries

        print(f"  [补搜] 第 {round_num + 1} 轮补充 {len(queries_to_search)} 个 query，总共 {queries_used} 个")

        # 补搜过程采集（诊断基础）
        current_results_per_query = {q: len(all_results.get(q, [])) for q in queries_to_search}
        current_content_lengths = {q: sum(len(r.get("content", "")) for r in all_results.get(q, [])) for q in queries_to_search}
        # 过滤搜索失败条目后收集本轮有效结果（指纹计算用）
        current_valid_items = [
            r for q in queries_to_search for r in all_results.get(q, [])
            if r.get("title") != "搜索失败"
        ]
        if logger is not None:
            logger.log("supplement_search_done", {
                "round": round_num + 1,
                "queries": queries_to_search,
                "results_per_query": current_results_per_query,
                "content_lengths": current_content_lengths,
                # 指纹样本（完整指纹的hash前缀，等长无碰撞歧义，支持离线重算）
                "fingerprints_sample": [
                    hashlib.sha256(fp.encode()).hexdigest()[:16]
                    for fp in (_make_fingerprint(r) for r in current_valid_items)
                ],
            })

        # v1.4：指纹/机械信号降为纯审计采集（不参与任何拦截）
        fingerprint_yield = _content_fingerprint_overlap(
            current_valid_items, historical_fingerprints, FINGERPRINT_OVERLAP_THRESHOLD,
        )
        mechanical_yield = _mechanical_yield_judgment(
            queries_to_search, current_results_per_query, seen_queries,
        )
        round_partial_signals.append({
            "round": round_num + 1,  # 1-based 补搜轮编号
            "fingerprint": fingerprint_yield,
            "mechanical": mechanical_yield,
        })
        if fingerprint_yield == "unproductive":
            print(f"  [审计-指纹] 第 {round_num + 1} 轮返回与历史重叠率≥{FINGERPRINT_OVERLAP_THRESHOLD}")
        if mechanical_yield == "unproductive":
            print(f"  [审计-机械] 第 {round_num + 1} 轮重复query或零返回")

        # 更新 seen_queries（供下一轮去重 + prompt注入）
        seen_queries.update(q.strip() for q in queries_to_search)
        # 指纹并入历史集合（供后续审计比对）
        historical_fingerprints.update(_make_fingerprint(r) for r in current_valid_items)

    # 最终审查：如果做过补搜且未因 gaps_closed/fm_review_failed/no_justification 停止，再审查一次
    if supplement_queries_used > 0 and stop_reason not in ("gaps_closed", "fm_review_failed", "no_justification"):
        search_summary = _summarize_search_results(all_results)
        # 注入已试query清单（v1.4：无previous_round_info，与循环内格式一致）
        seen_queries_list = "\n".join(f"  - {q}" for q in sorted(seen_queries)) if seen_queries else "（无）"
        fm_result = await _fm_review_search_results(
            industry_name, info_priority, search_summary, llm_call_fn,
            logger=logger, round_label="最终审查",
            seen_queries_list=seen_queries_list,
        )
        if not fm_result or "_error_type" in fm_result:
            error_type = fm_result.get("_error_type", "empty") if fm_result else "empty"
            _record_fm_failure_flag(quality_flags, error_type, "最终审查", fm_result or {})
            print(f"  [FM 最终审查] 失败（{error_type}），缺口状态未知")
            if not stop_reason:
                stop_reason = "fm_review_failed"
        elif fm_result.get("data_gaps"):
            remaining_gaps = fm_result["data_gaps"]
            final_gap_types = fm_result.get("gap_types", [])
            if not stop_reason:
                stop_reason = "budget_exhausted"  # 补搜循环结束后仍有缺口
            # v1.2 步骤3：QualityFlag detail 按 gap_type 路由不同文案（zip_longest 兜底）
            from itertools import zip_longest
            # BUG修复：gap_types 截断到 data_gaps 长度，避免幽灵 gap 名
            final_gap_types = (final_gap_types or [])[:len(remaining_gaps)]
            not_found_gaps = [g for g, t in zip_longest(remaining_gaps, final_gap_types, fillvalue="untyped") if t == "not_found"]
            shallow_gaps = [g for g, t in zip_longest(remaining_gaps, final_gap_types, fillvalue="untyped") if t == "snippet_too_shallow"]
            source_tier_gaps = [g for g, t in zip_longest(remaining_gaps, final_gap_types, fillvalue="untyped") if t == "source_tier"]
            # BUG修复：用排除式而非 == "untyped"，捕获非标准 gap_type 值
            untyped_gaps = [g for g, t in zip_longest(remaining_gaps, final_gap_types, fillvalue="untyped") if t not in ("not_found", "snippet_too_shallow", "source_tier")]
            # 兜底：若所有分组都为空（不应发生但防御），回退到列出全部缺口
            if not any([not_found_gaps, shallow_gaps, source_tier_gaps, untyped_gaps]):
                untyped_gaps = list(remaining_gaps)
            detail_parts = []
            if not_found_gaps:
                detail_parts.append(f"信息不存在型({len(not_found_gaps)}个): {'; '.join(not_found_gaps)}")
            if shallow_gaps:
                detail_parts.append(f"片段过浅型({len(shallow_gaps)}个，待阶段三深搜): {'; '.join(shallow_gaps)}")
            if source_tier_gaps:
                detail_parts.append(f"信源不足型({len(source_tier_gaps)}个，待阶段三一手源): {'; '.join(source_tier_gaps)}")
            if untyped_gaps:
                detail_parts.append(f"未分类({len(untyped_gaps)}个): {'; '.join(untyped_gaps)}")
            detail = f"补搜 {supplement_rounds_used} 轮（{supplement_queries_used} 个 query）后仍有 {len(remaining_gaps)} 个缺口；停止原因: {stop_reason}；" + "；".join(detail_parts)
            quality_flags.append(QualityFlag(
                category="data_gaps_remaining",
                field="data_gaps",
                severity="medium",
                detail=detail,
            ))
            print(f"  [FM 最终审查] 补搜后仍有缺口: {remaining_gaps}")
        else:
            if not stop_reason:
                stop_reason = "gaps_closed"
            print(f"  [FM 最终审查] 补搜后无缺口")
    elif not stop_reason:
        stop_reason = "gaps_closed"

    # B1-2 步骤2：结构化终态记录写入 Session Event Log（机器通道，给阶段三循环消费）
    # v1.4：justification_history/justification_valid_history/round_gap_types（审计主数据源）
    #       指纹/机械降为审计字段；移除v1.3的yield_history/round_signals/low_yield_trigger_history
    if logger is not None:
        logger.log("search_gap_record", {
            "queries_used": list(all_results.keys()),
            "supplement_rounds": supplement_rounds_used,
            "supplement_queries": supplement_queries_used,
            "remaining_gaps": fm_result.get("data_gaps", []) if 'fm_result' in dir() and isinstance(fm_result, dict) else [],
            "gap_types": fm_result.get("gap_types", []) if 'fm_result' in dir() and isinstance(fm_result, dict) else [],
            "stop_reason": stop_reason,
            "justification_history": justification_history,  # v1.4：每轮继续理由原样落盘（审计主数据源）
            "justification_valid_history": justification_valid_history,  # v1.4：每轮理由验证结果
            "round_gap_types": round_gap_types,  # v1.4：每轮审查的gap_types（gap_type门控对照分析用）
            "fingerprint_history": [r["fingerprint"] for r in round_partial_signals],  # 指纹审计（不拦截）
            "mechanical_history": [r["mechanical"] for r in round_partial_signals],  # 机械审计（不拦截）
            "fingerprint_threshold": FINGERPRINT_OVERLAP_THRESHOLD,
            "shadow_mode": JUSTIFICATION_SHADOW_MODE,
        })

    # 5. 搜索部分失败 flag（按失败比例计算 severity）
    if error_count > 0 and queries_used > 0:
        quality_flags.append(flag_search_partial_failure(
            failed=error_count, total=queries_used,
            field_name="search_results",
            detail=f"Step 1 搜索 {error_count}/{queries_used} 个 query 失败",
        ))

    return all_results, quality_flags, error_count


# ============================================================
# LLM 调用封装
# ============================================================

async def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 16000, timeout: float = 180.0, reasoning_effort: str = "none") -> dict[str, Any]:
    """统一的 LLM 调用函数（OpenAI 兼容 SDK）。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        max_tokens: 输出 Token 上限（API 参数，控制生成长度）
        timeout: HTTP 请求超时（秒），作为底层兜底；上层 call_with_timeout 提供步骤级超时
        reasoning_effort: 推理强度（"none"/"high"/"max"），默认 "none" 关闭思考。
                          DeepSeek 官方 API 默认 high 会导致响应过慢+content 为空问题。
                          如需开思考模式，显式传 "high" 或 "max"。

    Returns:
        {"text": str, "token_usage": {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}}
    """
    if is_mock_mode():
        return {
            "text": _mock_llm_response(system_prompt, user_prompt),
            "token_usage": _mock_token_usage(system_prompt, user_prompt),
        }

    config = get_llm_config()
    if not config["api_key"]:
        print("  [警告] 未配置 LLM_API_KEY，自动降级为 Mock 模式")
        return {
            "text": _mock_llm_response(system_prompt, user_prompt),
            "token_usage": _mock_token_usage(system_prompt, user_prompt),
        }

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=config["api_key"], base_url=config["base_url"], timeout=timeout)

    # 构造 API 参数
    api_kwargs = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    # DeepSeek V4 Pro 的 reasoning_effort 参数（通过 extra_body 传递）
    if reasoning_effort is not None:
        api_kwargs["extra_body"] = {
            "thinking": {
                "type": "enabled" if reasoning_effort != "none" else "disabled",
            }
        }
        if reasoning_effort != "none":
            api_kwargs["extra_body"]["thinking"]["reasoning_effort"] = reasoning_effort

    response = await client.chat.completions.create(**api_kwargs)

    # DeepSeek 思考模式：content 是最终回答，reasoning_content 是思考过程
    # 如果 content 为空但 reasoning_content 有值，从 reasoning_content fallback
    msg = response.choices[0].message
    text = msg.content or ""
    if not text and hasattr(msg, 'reasoning_content') and msg.reasoning_content:
        text = msg.reasoning_content
        print("  [LLM 警告] content 为空，从 reasoning_content fallback")
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }
    return {"text": text, "token_usage": usage}


# ============================================================
# Mock LLM 响应（v4 继承，保持不变）
# ============================================================

def _mock_token_usage(system: str, user: str) -> dict[str, int]:
    """Mock 模式下的 token 估算。"""
    return {
        "prompt_tokens": len(system) + len(user),
        "completion_tokens": 2000,
        "total_tokens": len(system) + len(user) + 2000,
    }


def _mock_llm_response(system_prompt: str, user_prompt: str) -> str:
    """Mock 模式下根据步骤返回预设 JSON / Markdown 响应。

    检测逻辑：匹配各步骤Task指令中的唯一关键词（来自 context_builder.STEP_TASKS）。
    """
    industry = _extract_industry(user_prompt)
    combined = system_prompt + user_prompt

    # Step 1: 信息收集（关键词："搜索并整理以下行业的基础信息"）
    if "搜索并整理以下行业的基础信息" in combined:
        return json.dumps({
            "summary": f"{industry}是指利用特定技术和商业模式，围绕核心活动形成的行业集合。其核心特征由技术路线、政策准入、需求结构、成本特征共同定义。",
            "official_definitions": [
                {"source": "国民经济行业分类（GB/T 4754）", "definition": f"{industry}属于相关大类下的细分领域", "credibility": "P1:权威二手数据"},
            ],
            "key_regulations": [
                {"title": f"{industry}相关管理办法（Mock）", "source": "相关部委", "key_point": f"对{industry}的准入条件、运营标准、监管框架进行了规定。"},
            ],
            "structural_factors": [
                {"factor": "技术驱动", "description": f"{industry}的发展高度依赖于核心技术的成熟度与迭代速度。", "type": "技术侧"},
                {"factor": "政策监管", "description": f"{industry}受到准入许可和安全标准的严格监管。", "type": "制度侧"},
                {"factor": "需求特性", "description": f"需求呈现特定模式（频次/场景/支付意愿）。", "type": "需求侧"},
                {"factor": "成本结构", "description": f"固定成本与可变成本的比例塑造了行业竞争逻辑。", "type": "成本侧"},
            ],
            "adjacent_industries": [
                {"name": "相邻行业A（Mock）", "relationship": f"与{industry}的边界在于核心活动不同"},
                {"name": "相邻行业B（Mock）", "relationship": f"与{industry}的边界在于服务对象不同"},
            ],
            "data_gaps": ["营收规模数据不可得（未找到权威统计来源）"],
        }, ensure_ascii=False, indent=2)

    # Step 2: 维度筛选（关键词："H1-H4 维度筛选原则"）
    if "H1-H4 维度筛选原则" in combined:
        return json.dumps({
            "selected_dimensions": [
                {"dimension": "技术成熟度与迭代速度", "side": "技术侧",
                 "reasoning": f"技术路线影响研发策略和产品周期（H1：独特形态）", "business_impact": "技术迭代速度决定竞争窗口期和研发投入策略", "methodology_ref": "H1, H3"},
                {"dimension": "监管准入制度", "side": "制度侧",
                 "reasoning": f"准入许可是最重要的结构特征之一（H1：被极端放大）", "business_impact": "准入壁垒影响供给端竞争强度和合规成本", "methodology_ref": "H1, H3"},
                {"dimension": "需求的结构性特征", "side": "需求侧",
                 "reasoning": f"需求具有特定模式（H2：独立侧——需求侧）", "business_impact": "需求特征决定客户获取策略和收入模式", "methodology_ref": "H2, H3"},
                {"dimension": "成本结构特征", "side": "成本侧",
                 "reasoning": f"成本结构呈现特定特征（H2：独立侧——成本侧）", "business_impact": "成本结构影响盈亏平衡和规模扩张逻辑", "methodology_ref": "H2, H3"},
            ],
            "abandoned_dimensions": [
                {"dimension": "市场份额分布", "reason": "属于竞争格局分析，不在行业定义范围内（方法论 §3.3）"},
                {"dimension": "营收规模数据", "reason": "数据不可得（H4：数据可获得性是合法的筛选标准）"},
            ],
            "reasoning": f"从 8 个候选维度中应用 H1-H4 筛选出 4 个核心维度。放弃 2 个并记录原因。覆盖技术、制度、需求、成本 4 个独立方向。",
        }, ensure_ascii=False, indent=2)

    # Step 3: 结构决策（关键词："设计报告结构"）
    if "设计报告结构" in combined:
        return json.dumps({
            "chapters": [
                {"title": "一、行业核心定义", "dimensions": ["所有维度"], "summary": "从核心活动和经济需求出发，给出行业的简明定义"},
                {"title": "二、行业边界划定", "dimensions": ["监管准入制度"], "summary": "明确包含范围、排除标准和与相邻行业的区分"},
                {"title": "三、结构性特征分析", "dimensions": ["技术", "需求", "成本"], "summary": "从独立侧分析使行业形成当前形态的根本原因"},
                {"title": "四、制度与监管环境", "dimensions": ["监管准入制度"], "summary": "制度如何塑造行业形态"},
                {"title": "五、方法论附注", "dimensions": [], "summary": "解释报告结构选择、维度取舍、方法论应用"},
            ],
            "reasoning": "采用五章结构：先定义核心再划边界，分析结构性特征，专门讨论制度因素，最后附方法论附注。不含禁止内容。",
        }, ensure_ascii=False, indent=2)

    # Step 4: 内容生成（关键词："撰写完整的行业定义报告"）
    if "撰写完整的行业定义报告" in combined:
        return f"""# 行业定义报告（Mock 模式）

## 一、行业核心定义

**{industry}** 是指围绕特定核心活动形成的行业集合。该行业解决的核心经济需求是……（Mock 数据）。

### 为什么这样定义
- 该定义锚定在行业的核心活动上，而非企业组织形式
- 该定义明确了行业的经济功能，而非技术实现路径
- 该定义为边界划定提供了可操作的判断标准

## 二、行业边界划定

### 包含范围
该行业包含以下活动：……（Mock 数据：完整范围在实际运行时由 LLM 生成）。

### 排除标准
1. **排除相邻行业A**：核心活动不同——以X活动为主 vs 以Y活动为主
2. **排除相邻行业B**：服务对象不同——面向C群体 vs 面向D群体

### 与相邻行业的区分
| 相邻行业 | 与本行业的区别 | 边界划分依据 |
|---------|-------------|------------|
| 相邻行业A | 核心活动差异 | 以X活动为主 vs 以Y活动为主 |
| 相邻行业B | 服务对象差异 | 面向C群体 vs 面向D群体 |

## 三、结构性特征分析

### 3.1 技术特征（技术侧）
该行业的技术路线尚未完全收敛，技术成熟度直接影响运营效率和成本结构。

### 3.2 需求特征（需求侧）
需求呈现特定模式，受到场景、频次、支付意愿等因素的结构性约束。

### 3.3 成本特征（成本侧）
固定成本与可变成本的比例决定了企业的盈亏平衡点和规模扩张逻辑。

## 四、制度与监管环境

准入制度是该行业最重要的制度特征，直接决定了供给端的竞争强度和合规成本。

## 五、方法论附注

本报告采用行业定义方法论文档 v2 的分析框架。

### 维度选择理由
| 维度 | 所属侧 | 方法论依据 | 选择理由 |
|------|-------|----------|---------|
| 技术成熟度与迭代速度 | 技术侧 | H1：独特形态 | 技术路线影响行业结构 |
| 监管准入制度 | 制度侧 | H1：被极端放大 | 准入壁垒塑造供给端竞争 |
| 需求的结构性特征 | 需求侧 | H2：独立侧 | 需求特征决定商业模式 |
| 成本结构特征 | 成本侧 | H2：独立侧 | 成本结构影响规模逻辑 |

### 放弃的维度
1. 市场份额分布 — 不在行业定义范围内（方法论 §3.3）
2. 营收规模数据 — 数据不可得（H4 筛选标准）

---
*报告生成时间：{time.strftime('%Y-%m-%d %H:%M')}*
*方法论文档版本：v2*
*运行模式：Mock（仅供开发测试）*
"""

    # Step 5: 自检（关键词："C1-C5 自检清单" 或 "严格的审查员"）
    if "C1-C5 自检清单" in combined or "严格的审查员" in combined:
        return json.dumps({
            "overall": "pass",
            "evaluator_confidence": "high",
            "dimensions": {
                "C1": {"status": "PASS", "detail": "报告包含行业特有的具体特征描述"},
                "C2": {"status": "PASS", "detail": "未发现通用废话"},
                "C3": {"status": "PASS", "detail": "核心定义锚定在结构性特征上"},
                "C4": {"status": "PASS", "detail": "包含明确的排除标准和相邻行业区分"},
                "C5": {"status": "PASS", "detail": "关键判断附有'为什么'的解释"},
            },
            "failed_dimensions": [],
            "issues": [],
            "fixes_required": [],
            "summary": f"Mock 评估：{industry}报告通过所有 C1-C5 检查项。",
        }, ensure_ascii=False, indent=2)

    # 兜底
    return json.dumps({"response": "Mock 响应（未匹配到步骤标识）"}, ensure_ascii=False)


# ============================================================
# 主流程：Orchestrator（v5.2）
# ============================================================

async def run(industry_name: str, force_resume: bool = False) -> str:
    """主执行流程 —— Orchestrator (v5.2)。

    v5.2 变更：
    - Orchestrator 统一生成 trace_id，注入 SessionEventLog 和 TokenAudit
    - 使用 CheckpointManager（多版本）替代 v4 的 save_checkpoint/try_resume
    - Step 1 集成搜索补搜循环
    - 生产步骤（Step 1-4）触发 or_fallback_result(high) 时终止流程
    - Step 6 使用 OutputSafety 安全保存 + TokenAudit 持久化成本报表

    v4 继承：
    - 六步严格线性执行（不做 Evaluator-Optimizer 闭环）
    - Step 5 失败时注入警告，不自动重跑 Step 4
    """

    # ---- v5.2 新增：Orchestrator 统一生成 trace_id ----
    trace_id = uuid.uuid4().hex[:12]

    # ---- 1. 初始化或恢复 ----
    # v5.2：使用 CheckpointManager 替代 v4 的 try_resume
    checkpoint_mgr = CheckpointManager(
        checkpoint_dir=str(PROJECT_ROOT / "checkpoints"),
    )

    state = None
    if force_resume:
        state = checkpoint_mgr.load(industry_name)
        if state:
            print(f"[恢复] 从 checkpoint 恢复了 {len(state.steps)} 个步骤")
        else:
            print(f"[恢复] 未找到 {industry_name} 的 checkpoint，从头开始")

    if state is None:
        state = ReportState(industry_name=industry_name)

    # ---- 2. 初始化 v5.2 组件（注入 trace_id）----
    logger = SessionEventLog(
        industry_name, trace_id=trace_id,
        log_dir=str(PROJECT_ROOT / "logs"),
    )
    token_audit = TokenAudit(log_dir=str(PROJECT_ROOT / "logs"))
    output_safety = OutputSafety(reports_dir=str(PROJECT_ROOT / "reports"))
    methodology_loader = MethodologyLoader(methodology_dir="方法论")
    context_builder = ContextBuilder()

    mock = is_mock_mode()
    mock_search_mode = os.getenv("MOCK_SEARCH", "false").lower() == "true"

    logger.log("start", {
        "industry": industry_name, "trace_id": trace_id,
        "mock": mock, "mock_search": mock_search_mode,
    })
    print(f"\n{'='*60}")
    print(f"行业定义 Agent v5.2 (阶段二 A 组)")
    print(f"行业: {industry_name}")
    print(f"trace_id: {trace_id}")
    print(f"模式: {'Mock (LLM+搜索均为预设)' if mock else 'API (DeepSeek-V4-Pro)'}")
    print(f"{'='*60}\n")

    # ---- 3. 确定已完成的步骤（支持 checkpoint 恢复） ----
    completed_ids = {s.step_id for s in state.steps}

    # ---- 4. Step 1: 信息收集（v5.2：集成搜索补搜循环）----
    if "1_info_collection" not in completed_ids:
        await _run_step1(
            industry_name, state, logger, context_builder,
            methodology_loader, checkpoint_mgr, trace_id,
            mock, mock_search_mode,
        )
    else:
        print(f"[跳过] Step 1: 信息收集 — 已从 checkpoint 恢复")

    # ---- 5. Step 2: 维度筛选 ----
    if "2_dimension_screening" not in completed_ids:
        await _run_step(2, state, logger, context_builder, checkpoint_mgr, trace_id, mock)
    else:
        print(f"[跳过] Step 2: 维度筛选 — 已从 checkpoint 恢复")

    # ---- 6. Step 3: 结构决策 ----
    if "3_structure_decision" not in completed_ids:
        await _run_step(3, state, logger, context_builder, checkpoint_mgr, trace_id, mock)
    else:
        print(f"[跳过] Step 3: 结构决策 — 已从 checkpoint 恢复")

    # ---- 7. Step 4: 内容生成（v5.2：新增内容校验）----
    if "4_content_generation" not in completed_ids:
        await _run_step(4, state, logger, context_builder, checkpoint_mgr, trace_id, mock)
    else:
        print(f"[跳过] Step 4: 内容生成 — 已从 checkpoint 恢复")

    # ---- 8. Step 5: 自检 ----
    if "5_self_check" not in completed_ids:
        self_check_warning = await _run_step5(
            industry_name, state, logger, checkpoint_mgr, trace_id, mock,
        )
    else:
        print(f"[跳过] Step 5: 自检 — 已从 checkpoint 恢复")
        step5 = next(s for s in state.steps if s.step_id == "5_self_check")
        overall = step5.result.get("overall", "fail_with_fixes")
        if overall != "pass":
            failed = step5.result.get("failed_dimensions", [])
            issues = step5.result.get("issues", [])
            self_check_warning = _build_self_check_warning(failed, issues)
            logger.log("self_check_failed", {"failed_dimensions": failed, "issues": issues})
        else:
            self_check_warning = ""

    # ---- 9. Step 6: 输出（v5.2：OutputSafety + TokenAudit + quality_flags 汇总）----
    final_report = await _run_step6(
        industry_name, state, logger, checkpoint_mgr, trace_id,
        token_audit, output_safety, self_check_warning,
    )

    return final_report


# ============================================================
# 各步骤实现
# ============================================================

async def _run_step1(
    industry_name: str, state: ReportState, logger: SessionEventLog,
    context_builder: ContextBuilder, methodology_loader: MethodologyLoader,
    checkpoint_mgr: CheckpointManager, trace_id: str,
    mock: bool, mock_search_mode: bool,
) -> None:
    """Step 1: 信息收集——并行搜索 + v5.2 搜索补搜循环 + LLM 总结。"""
    step_id = "1_info_collection"
    print(f"\n--- Step 1: 信息收集 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    tavily_key = os.getenv("TAVILY_API_KEY", "")

    # v5.2：搜索补搜循环
    # v5.2 修复2：外层 asyncio.wait_for 兜底，防止修复1（FM 超时 30s→60s）后搜索阶段最坏 258s 无保护
    # v5.2 修复 P2 #3：传入 logger 以记录 FM 审查 LLM 调用
    try:
        search_results, search_quality_flags, error_count = await asyncio.wait_for(
            step1_search_with_supplement(
                industry_name=industry_name,
                tavily_api_key=tavily_key,
                methodology_loader=methodology_loader,
                llm_call_fn=call_llm,
                mock_search_mode=(mock or mock_search_mode or not tavily_key),
                logger=logger,
            ),
            timeout=SEARCH_PHASE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # v5.2 修复2 方案Y（architecture-critic）：新增专用 search_phase_timeout category（high），
        # 不复用 timeout_retry（语义=重试成功，与"放弃"相反），无需 [severity-overridden] 绕过 validator
        # B1-1：设 terminates_flow=True，统一走 _check_quality_gate 终止路径
        print(f"  [搜索阶段超时] 整体 {SEARCH_PHASE_TIMEOUT}s 兜底触发，放弃搜索")
        search_results = {}
        search_quality_flags = [QualityFlag(
            category="search_phase_timeout",
            field="search_phase",
            severity="high",
            detail=f"搜索阶段整体超时（{SEARCH_PHASE_TIMEOUT}s），放弃搜索",
            terminates_flow=True,  # B1-1：SSOT 元数据
        )]
        error_count = 1

    logger.log("search_done", {
        "query_count": len(search_results),
        "errors": error_count,
        "quality_flags_count": len(search_quality_flags),
    })

    # v5.2 P1-10：搜索全失败终止（quality_flags 含 high severity 的 search_partial_failure）
    # v5.2 修复2 P1-3（architecture-critic）：search_phase_timeout 也走终止路径，
    # 避免空 search_results 流到 LLM 总结触发 or_fallback_result(high)，产生两个 high flag 叠加
    # B1-1：基于 terminates_flow 元数据统一判断（SSOT），消除原 has_search_all_failed 的硬编码 category 检查
    will_terminate = any(
        f.terminates_flow and f.severity == "high"
        for f in search_quality_flags
    )
    if will_terminate:
        state.steps.append(StepOutput(
            step_id=step_id, step_label="信息收集",
            reasoning="搜索阶段失败，跳过 LLM 总结",
            confidence="低：搜索失败",
            result={"error": "all_search_failed"},
            abandoned=[],
            methodology_ref=METHODOLOGY_REFS[step_id],
            quality_flags=search_quality_flags,
        ))
        checkpoint_mgr.save(state, step_id, trace_id=trace_id)
        logger.log("step_complete", {"step_id": step_id, "status": "all_search_failed"})
        # B1-1：统一走 _check_quality_gate（SSOT），不再直接 raise QualityGateError
        # _check_quality_gate 会扫描 terminates_flow=True 的 flag 并 raise，以下代码不可达
        _check_quality_gate(state.steps[-1], step_id)
        return

    # LLM 总结（v4 逻辑）
    context = context_builder.build(step_id, state)
    user_prompt = context + f"\n\n## 搜索结果\n\n{json.dumps(search_results, ensure_ascii=False, indent=2)}"

    # v5.2：传入 max_retries 参数
    llm_result = await call_with_timeout(
        lambda: call_llm(context, user_prompt),
        timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
        max_retries=STEP_BUDGETS[step_id].max_retries,
    )
    logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})
    parsed = _parse_json_response(llm_result["text"])

    # v5.2：检测 or_fallback（summary 为空时注入占位符）
    quality_flags = list(search_quality_flags)
    summary = parsed.get("summary", "")
    if not summary:
        # or_fallback_result：result 字段被占位符替代
        parsed["summary"] = "（LLM 未返回摘要，已用占位符替代）"
        quality_flags.append(QualityFlag(
            category="or_fallback_result",
            field="summary",
            severity="high",
            detail="LLM 未返回 summary 字段，已用占位符替代",
            terminates_flow=True,  # B1-1：SSOT 元数据
        ))

    state.steps.append(StepOutput(
        step_id=step_id, step_label="信息收集",
        reasoning=(summary[:300] if summary else "（LLM 未返回摘要，已从搜索结果生成）"),
        confidence="中：Mock 模式" if mock else "中：LLM 生成",
        result=parsed, abandoned=[],
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=llm_result.get("token_usage"),
        quality_flags=quality_flags,
    ))
    checkpoint_mgr.save(state, step_id, trace_id=trace_id)
    logger.log("step_complete", {
        "step_id": step_id, "confidence": state.steps[-1].confidence,
        "quality_flags_count": len(quality_flags),
    })
    print(f"  完成 — 置信度: {state.steps[-1].confidence}")
    if quality_flags:
        print(f"  降级标记: {len(quality_flags)} 个")

    # v5.2：生产步骤质量门检查
    _check_quality_gate(state.steps[-1], step_id)


async def _run_step(
    step_index: int, state: ReportState, logger: SessionEventLog,
    context_builder: ContextBuilder, checkpoint_mgr: CheckpointManager,
    trace_id: str, mock: bool,
) -> None:
    """Step 2-4 的通用模板：构建上下文 → 调用 LLM → 解析 → 记录。

    v5.2 变更：
    - 传入 max_retries 参数给 call_with_timeout
    - Step 4 新增内容校验（len < 500 时 raise）
    - 检测 or_fallback 并注入 quality_flags
    - 生产步骤质量门检查
    """
    step_id = STEPS_DEFINITION[step_index - 1][0]
    step_label = STEPS_DEFINITION[step_index - 1][1]
    print(f"\n--- Step {step_index}: {step_label} 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    context = context_builder.build(step_id, state)
    # Step 4 使用 STEP4_MAX_TOKENS（P0-4：默认值 10000），其他步骤用默认值
    step4_max_tokens = STEP4_MAX_TOKENS if step_id == "4_content_generation" else 16000
    llm_result = await call_with_timeout(
        lambda: call_llm(context, context, max_tokens=step4_max_tokens),
        timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
        max_retries=STEP_BUDGETS[step_id].max_retries,
    )
    logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})
    parsed = _parse_json_response(llm_result["text"])

    quality_flags: list[QualityFlag] = []

    # 构建 reasoning 和 abandoned
    if step_id == "2_dimension_screening":
        _reasoning_raw = parsed.get("reasoning", "")
        reasoning = (_reasoning_raw if isinstance(_reasoning_raw, str) else str(_reasoning_raw))[:300] or "（LLM 未返回推理，已根据方法论完成维度筛选）"
        abandoned = [f"{a.get('dimension', '未知')}: {a.get('reason', '无理由')}"
                      for a in parsed.get("abandoned_dimensions", [])]
        extra = f" — 选中 {len(parsed.get('selected_dimensions', []))} 个维度，放弃 {len(abandoned)} 个"
        # 检测 or_fallback
        if not parsed.get("selected_dimensions"):
            quality_flags.append(QualityFlag(
                category="or_fallback_result",
                field="selected_dimensions",
                severity="high",
                detail="LLM 未返回 selected_dimensions，result 字段被占位符替代",
                terminates_flow=True,  # B1-1：SSOT 元数据
            ))
    elif step_id == "3_structure_decision":
        _reasoning_raw = parsed.get("reasoning", "")
        reasoning = (_reasoning_raw if isinstance(_reasoning_raw, str) else str(_reasoning_raw))[:300] or "（LLM 未返回推理，已根据维度筛选结果设计章节结构）"
        abandoned = []
        extra = f" — {len(parsed.get('chapters', []))} 章"
        # 检测 or_fallback
        if not parsed.get("chapters"):
            quality_flags.append(QualityFlag(
                category="or_fallback_result",
                field="chapters",
                severity="high",
                detail="LLM 未返回 chapters，result 字段被占位符替代",
                terminates_flow=True,  # B1-1：SSOT 元数据
            ))
    else:  # Step 4: 剥离开场白后存为报告文本
        report_text = _strip_preamble(llm_result["text"])
        parsed = {"report_text": report_text}
        reasoning = f"生成了 {len(report_text)} 字符的报告"
        abandoned = []
        extra = f" — 报告 {len(report_text)} 字符"

        # v5.2 P1-7：Step 4 内容校验（len < 500 时 raise）
        if len(report_text) < 500:
            quality_flags.append(QualityFlag(
                category="or_fallback_result",
                field="report_text",
                severity="high",
                detail=f"Step 4 报告内容过短（{len(report_text)} 字符 < 500），可能生成失败",
                terminates_flow=True,  # B1-1：SSOT 元数据
            ))

    state.steps.append(StepOutput(
        step_id=step_id, step_label=step_label,
        reasoning=reasoning,
        confidence="中：Mock 模式" if mock else "中：LLM 生成",
        result=parsed, abandoned=abandoned,
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=llm_result.get("token_usage"),
        quality_flags=quality_flags,
    ))
    checkpoint_mgr.save(state, step_id, trace_id=trace_id)
    logger.log("step_complete", {
        "step_id": step_id,
        "quality_flags_count": len(quality_flags),
    })
    print(f"  完成{extra}")
    if quality_flags:
        print(f"  降级标记: {len(quality_flags)} 个")

    # v5.2：生产步骤质量门检查
    _check_quality_gate(state.steps[-1], step_id)


def _build_self_check_warning(failed: list[str], issues: list[dict]) -> str:
    """构建 Step 5 失败时的警告文本。"""
    if not failed:
        return ""
    warning_lines = [
        "\n\n---\n\n",
        "## ⚠️ 自检未通过\n\n",
        f"以下维度未通过审查：{', '.join(failed)}\n\n",
    ]
    for issue in issues:
        problem = issue.get("problem", issue.get("dimension", ""))
        warning_lines.append(f"- {problem}\n")
    warning_lines.append("\n**请人工审查后再使用此报告。**\n")
    return "".join(warning_lines)


async def _run_step5(
    industry_name: str, state: ReportState, logger: SessionEventLog,
    checkpoint_mgr: CheckpointManager, trace_id: str, mock: bool,
) -> str:
    """Step 5: 独立 Evaluator 自检。

    v4 关键约束：失败时只注入警告，不自动重跑 Step 4。
    返回警告文本（空字符串表示全部通过）。

    v5.2 变更：
    - 传入 max_retries 参数给 call_with_timeout
    - Step 5 不是生产步骤，不触发质量门终止
    """
    step_id = "5_self_check"
    print(f"\n--- Step 5: 自检 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    report_to_check = _get_report_from_state(state)

    # 包装 llm_call_fn 供 evaluator 使用（evaluator 用 keyword args 调用）
    step5_token_usage: dict = {}

    async def _llm_call_fn(system_prompt: str, user_prompt: str) -> str:
        r = await call_llm(system_prompt, user_prompt)
        if r.get("token_usage"):
            step5_token_usage.update(r["token_usage"])
        return r["text"]

    if mock:
        eval_result = mock_evaluate(report_to_check, industry_name)
    else:
        eval_result = await call_with_timeout(
            lambda: evaluate(report_to_check, industry_name, _llm_call_fn),
            timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
            max_retries=STEP_BUDGETS[step_id].max_retries,
        )
        # v5.2 修复 P2 #2：记录 Step 5 的 LLM 调用，补齐 LLM 调用次数审计
        # mock 模式不调真实 LLM，故不记日志；验收标准要求真实 API 下含 5 个 llm_raw_response 事件
        logger.log("llm_raw_response", {
            "step_id": step_id,
            "text_preview": json.dumps(eval_result, ensure_ascii=False)[:1000],
        })

    overall = eval_result.get("overall", "fail_with_fixes")
    failed = eval_result.get("failed_dimensions", [])
    issues = eval_result.get("issues", [])
    confidence = eval_result.get("evaluator_confidence",
                                 "中：Mock 模式" if mock else "中")

    reasoning_parts = [f"独立Evaluator审查完成。结果: {overall}。"]
    if failed:
        reasoning_parts.append(f"失败维度: {', '.join(failed)}。")
    else:
        reasoning_parts.append("失败维度: 无。")

    # v5.2：Step 5 不是生产步骤，不触发质量门终止，但记录 quality_flags
    quality_flags: list[QualityFlag] = []
    if overall != "pass":
        quality_flags.append(QualityFlag(
            category="data_gaps_remaining",
            field="self_check",
            severity="medium",
            detail=f"自检未通过，失败维度: {', '.join(failed) if failed else '未知'}",
        ))

    state.steps.append(StepOutput(
        step_id=step_id, step_label="自检",
        reasoning="".join(reasoning_parts),
        confidence=confidence,
        result=eval_result, abandoned=[],
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=step5_token_usage if step5_token_usage else None,
        quality_flags=quality_flags,
    ))
    checkpoint_mgr.save(state, step_id, trace_id=trace_id)
    logger.log("step_complete", {"step_id": step_id, "overall": overall, "failed": failed})

    print(f"  自检结果: {overall}")
    if failed:
        print(f"  失败维度: {', '.join(failed)}")

    # ---- v4 关键逻辑：失败时注入警告，不自动修正 ----
    self_check_warning = _build_self_check_warning(failed, issues)
    if self_check_warning:
        logger.log("self_check_failed", {"failed_dimensions": failed, "issues": issues})
        print(f"\n[警告] 自检未通过 — 失败维度: {failed}")
        print("[警告] 报告已生成但包含审查警告，请人工复核\n")

    print(f"--- Step 5: 自检 完成 ---")
    return self_check_warning


async def _run_step6(
    industry_name: str, state: ReportState, logger: SessionEventLog,
    checkpoint_mgr: CheckpointManager, trace_id: str,
    token_audit: TokenAudit, output_safety: OutputSafety,
    self_check_warning: str,
) -> str:
    """Step 6: 输出——组装最终报告 + v5.2 quality_flags 汇总 + OutputSafety + TokenAudit。

    v5.2 变更：
    - 使用 OutputSafety.safe_save（UTC 时间戳 + 版本号上限）
    - 使用 TokenAudit.generate_report（持久化 JSON + Markdown 成本报表）
    - 报告尾部汇总 quality_flags（按严重度分组）
    - Token 统计移出报告正文，CLI 保留成本摘要
    """
    print(f"\n--- Step 6: 输出 开始 ---")

    report_text = _get_report_from_state(state)

    # v5.2：报告尾部 = 自检警告 + quality_flags 汇总（Token 统计移出）
    quality_flags_summary = _build_quality_flags_summary(state)
    final_report = self_check_warning + report_text + quality_flags_summary

    state.final_report = final_report
    logger.log("complete", {
        "report_length": len(final_report),
        "quality_flags_summary_length": len(quality_flags_summary),
    })
    checkpoint_mgr.save(state, "6_output", trace_id=trace_id)

    # v5.2：使用 OutputSafety 安全保存（UTC 时间戳 + 版本号上限）
    report_path = output_safety.safe_save(final_report, industry_name)

    # v5.2：使用 TokenAudit 持久化成本报表
    token_report = token_audit.generate_report(state, trace_id, industry_name)
    summary = token_report.get("summary", {})
    total_cost_cny = summary.get("total_cost_cny", 0)
    total_cost_usd = summary.get("total_cost_usd", 0)
    total_tokens = summary.get("total_tokens", 0)

    # v5.1 修正（评议 Q3）：CLI 保留成本摘要 + 详细报表路径
    print(f"\n  Token 审计（trace_id: {trace_id}）:")
    print(f"  {'步骤':<25} {'prompt':>10} {'completion':>12} {'total':>10}")
    print(f"  {'-'*25} {'-'*10} {'-'*12} {'-'*10}")
    for s in state.steps:
        if s.token_usage:
            pt = s.token_usage.get("prompt_tokens", 0)
            ct = s.token_usage.get("completion_tokens", 0)
            tt = s.token_usage.get("total_tokens", 0)
            print(f"  {s.step_id:<25} {pt:>10} {ct:>12} {tt:>10}")
        else:
            print(f"  {s.step_id:<25} {'N/A':>10} {'N/A':>12} {'N/A':>10}")
    print(f"  {'-'*25} {'-'*10} {'-'*12} {'-'*10}")
    print(f"  {'合计':<25} {'':>10} {'':>12} {total_tokens:>10}")
    print(f"\n  总成本: ¥{total_cost_cny} (≈ ${total_cost_usd})")
    print(f"  详细报表: logs/{trace_id}_token_audit.md")
    print(f"  报告已保存到: {report_path}")
    print(f"--- Step 6: 输出 完成 ---")

    print(f"\n{'='*60}")
    print(f"任务完成！")
    print(f"trace_id: {trace_id}")
    print(f"总步骤数: {len(state.steps)}")
    print(f"报告长度: {len(final_report)} 字符")
    print(f"报告文件: {report_path}")
    print(f"{'='*60}\n")

    return final_report


# ============================================================
# CLI 入口
# ============================================================

def main() -> None:
    """CLI 入口：python frost_agent.py "行业名称" [--mock] [--resume]"""
    parser = argparse.ArgumentParser(
        description="行业定义 Agent v5.2 — 阶段二 A 组",
    )
    parser.add_argument(
        "industry", nargs="?", default=None,
        help="行业名称（如 '低空经济物流'）",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="启用 Mock 模式（LLM + 搜索均用预设数据）",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="从 checkpoint 恢复执行",
    )

    args = parser.parse_args()

    industry_name = args.industry
    if not industry_name:
        industry_name = input("请输入行业名称: ").strip()
        if not industry_name:
            print("错误：行业名称不能为空")
            sys.exit(1)

    if args.mock:
        os.environ["MOCK_LLM"] = "true"
        os.environ["MOCK_SEARCH"] = "true"

    try:
        final_report = asyncio.run(run(industry_name, force_resume=args.resume))
        print("\n" + "=" * 60)
        print("最终报告预览（前 500 字符）：")
        print("-" * 60)
        print(final_report[:500])
        if len(final_report) > 500:
            print("...（报告较长，完整内容请查看文件）")
        print("=" * 60)
    except QualityGateError as e:
        # v5.2：质量门终止，提示重跑
        print(f"\n[质量门终止] {e}")
        print("[建议] 请检查 API 配置或重跑。checkpoint 已保存，可用 --resume 恢复。")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消了执行。checkpoint 已自动保存。")
        sys.exit(0)
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
