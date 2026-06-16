"""
Context Builder — 四层上下文组装器 (v4)

v4 核心改进：v3 只有三层（静态身份 + 方法论切片 + 前序摘要），
v4 新增"任务指令层"（Layer 3），将每步的任务描述和 Sprint Contract 验收标准
直接注入上下文，避免 v3 中任务指令与前序摘要混在一起的模糊问题。
"""

from __future__ import annotations

from methodology_loader import load_slice
from models import ReportState, StepOutput


# ============================================================
# STEP_TASKS — 步骤级任务指令（v4 核心——内嵌 Sprint Contract 验收标准）
# ============================================================

STEP_TASKS: dict[str, str] = {
    "1_info_collection": (
        "请搜索并整理以下行业的基础信息：{industry}。\n"
        "要求：覆盖官方定义、关键政策/标准、结构性影响因素、相邻行业。\n"
        "标注信息来源和可信度（P0-P3）。\n"
        "输出 JSON 格式，包含 summary、official_definitions、key_regulations、"
        "structural_factors、adjacent_industries、data_gaps 字段。"
        "注意：summary 字段不可为空，必须包含对搜索结果的归纳摘要（至少 50 字）。"
    ),
    "2_dimension_screening": (
        "基于 Step 1 的信息，对行业「{industry}」应用 H1-H4 维度筛选原则。\n"
        "选出核心维度，并明确记录：选了什么、放弃了什么、为什么。\n"
        "验收标准：覆盖 ≥ 2 个独立侧，每个维度有经营结果传导。\n"
        "输出 JSON 格式，包含 selected_dimensions、abandoned_dimensions、reasoning 字段。"
    ),
    "3_structure_decision": (
        "为行业「{industry}」设计报告结构。\n"
        "每章对应 Step 2 的至少一个维度。\n"
        "严格禁止出现竞争格局/市场规模/投资建议类章节。\n"
        "输出 JSON 格式，包含 chapters（每章含 title、dimensions、summary）、reasoning 字段。"
    ),
    "4_content_generation": (
        "为行业「{industry}」撰写完整的行业定义报告正文。\n"
        "严格禁止：企业排名、市场份额、竞争格局分析、市场规模预测、投资建议。\n"
        "每个关键判断必须附带推理链和置信度标注。\n"
        "所有数据必须标注来源和可信度。\n"
        "直接输出 Markdown 格式报告，从第一个 # 标题开始，不要加任何开场白或礼貌用语。"
    ),
    "5_self_check": (
        "对行业「{industry}」的报告执行 C1-C5 自检清单。\n"
        "你是一个严格的审查员，倾向于发现问题而非确认一切正常。\n"
        "输出 JSON 格式，包含 overall(pass/fail_with_fixes)、failed_dimensions、issues、fixes_required 字段。"
    ),
}


# ============================================================
# ContextBuilder
# ============================================================

class ContextBuilder:
    """四层上下文组装：静态身份 + 方法论切片 + 任务指令 + 前序摘要"""

    def build(self, step_id: str, state: ReportState) -> str:
        """组装完整上下文，四层用 `\\n\\n---\\n\\n` 分隔。

        Args:
            step_id: 当前步骤标识，如 '1_info_collection'。
            state: ReportState 对象（从 models 导入）。
        """
        parts = [
            self._static_identity(),
            self._methodology_slice(step_id),
            self._task_directive(step_id, state.industry_name),
            self._previous_summary(state),
        ]
        return "\n\n---\n\n".join(p.strip() for p in parts if p.strip())

    # ----------------------------------------------------------
    # Layer 1: 静态身份
    # ----------------------------------------------------------

    @staticmethod
    def _static_identity() -> str:
        return (
            "你是行业定义分析引擎。\n"
            "你的任务是：输入行业名称，产出符合行业定义方法论标准的行业定义报告。\n"
            "报告不包含竞争排名、市场规模预测、投资建议。"
        )

    # ----------------------------------------------------------
    # Layer 2: 方法论切片
    # ----------------------------------------------------------

    @staticmethod
    def _methodology_slice(step_id: str) -> str:
        return load_slice(step_id)

    # ----------------------------------------------------------
    # Layer 3: 任务指令（v4 新增）
    # ----------------------------------------------------------

    @staticmethod
    def _task_directive(step_id: str, industry: str) -> str:
        template = STEP_TASKS.get(step_id, "请执行当前步骤。")
        return f"## 当前任务\n\n{template.format(industry=industry)}"

    # ----------------------------------------------------------
    # Layer 4: 前序摘要
    # ----------------------------------------------------------

    @staticmethod
    def _previous_summary(state: ReportState) -> str:
        """前序步骤摘要（最近 3 步）"""
        if not state.steps:
            return ""
        lines = ["## 前序步骤摘要\n"]
        for step in state.steps[-3:]:
            key = step.result.get("summary", step.reasoning[:150])
            lines.append(f"- **{step.step_label}**: {key} (置信度: {step.confidence})")
        return "\n".join(lines)
