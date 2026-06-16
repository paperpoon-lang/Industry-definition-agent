"""
Independent Evaluator — 独立评估器 (v4 Demo)

关键约束：Evaluator 只看最终报告文本，不接收 Step 1-4 的 reasoning。
把"干活"和"挑刺"彻底分开，解决 Self-Evaluation Bias。
"""

from __future__ import annotations

import json
import re
from typing import Any


# ============================================================
# Evaluator System Prompt — 挑剔的审查员
# ============================================================

EVALUATOR_PROMPT = """你是一个严格的行业定义报告审查员。

审查维度（C1-C5）：
C1. 区分度测试：遮住行业名称，读者能否从定义本身判断出是哪个行业？
C2. 废话过滤：是否存在对任何行业都成立的通用陈述？
C3. 结构性测试：核心逻辑是否独立于短期市场数据？
C4. 边界清晰度：读者能否说清楚"什么不是这个行业"？
C5. 推理可见：每个关键判断是否有"为什么"的解释？

对每个维度输出 PASS 或 FAIL，并附一句话具体说明。

你必须只输出以下 JSON 格式，不要输出任何其他文字：
{
    "overall": "pass 或 fail_with_fixes",
    "evaluator_confidence": "high 或 medium 或 low",
    "dimensions": {
        "C1": {"status": "PASS 或 FAIL", "detail": "一句话具体说明"},
        "C2": {"status": "PASS 或 FAIL", "detail": "一句话具体说明"},
        "C3": {"status": "PASS 或 FAIL", "detail": "一句话具体说明"},
        "C4": {"status": "PASS 或 FAIL", "detail": "一句话具体说明"},
        "C5": {"status": "PASS 或 FAIL", "detail": "一句话具体说明"}
    },
    "failed_dimensions": ["未通过的维度，如 C1"],
    "issues": [{"dimension": "C1", "problem": "具体问题描述"}],
    "fixes_required": ["修复建议1", "修复建议2"]
}"""


# ============================================================
# 核心评估函数
# ============================================================

async def evaluate(report: str, industry_name: str, llm_call_fn) -> dict[str, Any]:
    """独立 LLM 调用——不同的 prompt，不传入生成过程的 reasoning。

    Args:
        report: 报告文本（Markdown）。
        industry_name: 行业名称。
        llm_call_fn: LLM 调用函数，签名为 async def fn(system_prompt, user_prompt) -> str。

    Returns:
        dict: {"overall": "pass"/"fail_with_fixes", "failed_dimensions": [...],
               "issues": [...], "fixes_required": [...]}
    """
    user_prompt = f"行业：{industry_name}\n\n报告：\n{report}"
    raw = await llm_call_fn(
        system_prompt=EVALUATOR_PROMPT,
        user_prompt=user_prompt,
    )
    return parse_evaluation(raw)


# ============================================================
# JSON 解析（容错）
# ============================================================

def parse_evaluation(raw: str) -> dict[str, Any]:
    """解析 Evaluator 返回的 JSON 结果，处理 LLM 格式错误。

    支持三种回退方式：
    1. 直接 JSON 解析
    2. 提取 ```json ... ``` 代码块
    3. 提取第一个 { 到最后一个 } 的内容
    """
    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取 {...} 块
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 完全无法解析
    return {
        "overall": "fail_with_fixes",
        "failed_dimensions": ["parse_error"],
        "issues": [{"dimension": "parse", "problem": "无法解析 Evaluator 输出", "suggestion": "请检查 LLM 响应格式"}],
        "fixes_required": ["Evaluator 输出格式异常，需人工检查"],
    }


# ============================================================
# Mock 模式（不调用 LLM，用规则检查）
# ============================================================

def mock_evaluate(report: str, industry_name: str) -> dict[str, Any]:
    """Mock 模式下的评估结果：用关键词规则做基本检查。"""
    issues: list[dict] = []
    failed: list[str] = []

    # C1: 区分度——行业名称是否在报告中出现
    if industry_name not in report:
        failed.append("C1")
        issues.append({"dimension": "C1", "problem": "报告中未出现行业名称", "suggestion": "确保核心段落锚定行业特征"})

    # C2: 废话过滤
    buzzwords = ["市场前景广阔", "竞争日益激烈", "具有广阔的发展空间", "未来发展潜力巨大", "备受关注"]
    found = [w for w in buzzwords if w in report]
    if found:
        failed.append("C2")
        issues.append({"dimension": "C2", "problem": f"包含通用废话: {found}", "suggestion": "替换为行业独有的具体特征"})

    # C4: 边界清晰度
    if "排除" not in report and "不属于" not in report and "边界" not in report:
        failed.append("C4")
        issues.append({"dimension": "C4", "problem": "未找到行业边界定义", "suggestion": "添加明确的排除标准"})

    # C5: 推理可见
    reasoning_kw = ["因为", "因此", "所以", "这意味着", "依据", "推理"]
    if not any(kw in report for kw in reasoning_kw):
        failed.append("C5")
        issues.append({"dimension": "C5", "problem": "未找到推理过程标记", "suggestion": "在关键判断处添加'为什么'"})

    return {
        "overall": "pass" if not failed else "fail_with_fixes",
        "failed_dimensions": failed,
        "issues": issues,
        "fixes_required": [i["suggestion"] for i in issues],
    }
