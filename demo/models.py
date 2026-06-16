"""
行业定义 Agent — Pydantic 数据模型 (v4 Demo MVP)

本模块定义了 Agent 全流程使用的核心数据结构。
v4 相比 v2 精简：
- 移除 StepContext 类（v2 压力测试代码，v4 不需要）
- SprintContract 类定义保留，但不实例化（接口不堵死）
- StepOutput 增加 token_usage 字段，用于顺手记录 LLM 调用消耗
- ReportState 移除 fix_attempt 字段（v4 不做 E-O 闭环）
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ============================================================
# StepOutput — 每一步的输出（强制包含推理痕迹）
# ============================================================

class StepOutput(BaseModel):
    """每一步的输出结构，强制包含 reasoning 和 confidence。"""

    step_id: str = Field(
        ...,
        description="步骤唯一标识，如 '1_info_collection'、'2_dimension_screening'。",
        examples=["1_info_collection", "5_self_check"],
    )
    step_label: str = Field(
        ...,
        description="人类可读的步骤名称，如 '信息收集'、'维度筛选'、'自检'。",
        examples=["信息收集", "维度筛选"],
    )
    reasoning: str = Field(
        ...,
        description=(
            "该步骤的判断推理过程（必须填写）。"
            "记录每一步的关键决策依据：为什么选这个、为什么放弃那个、不确定的地方在哪。"
        ),
        min_length=1,
    )
    confidence: str = Field(
        ...,
        description=(
            "置信度标注，格式为 '级别：依据简述'。"
            "级别取值：高 / 中 / 低。"
            "示例：'高：信息来源于官方政策文件和行业标准，多源交叉验证一致'"
        ),
    )
    result: dict[str, Any] = Field(
        default_factory=dict,
        description="该步骤的结构化产出，内容因步骤而异。",
    )
    abandoned: list[str] = Field(
        default_factory=list,
        description="该步骤中放弃的选择及原因。每个元素为 '选项名：放弃原因' 格式。",
    )
    methodology_ref: str = Field(
        default="",
        description="引用了方法论文档的哪一节，如 '3.1 维度筛选原则(H1-H4)'。",
    )
    token_usage: Optional[dict[str, int]] = Field(
        default=None,
        description=(
            "v4 新增：该步骤 LLM 调用的 token 消耗记录。"
            "包含 prompt_tokens、completion_tokens、total_tokens 三个字段。"
            "仅当该步骤实际调用了 LLM 时填充。"
        ),
    )


# ============================================================
# ReportState — 贯穿全流程的状态对象
# ============================================================

class ReportState(BaseModel):
    """贯穿全流程的状态对象。v4 版本移除 fix_attempt 字段。"""

    methodology_version: str = Field(
        default="v2",
        description="方法论文档版本号，当前固定为 v2。",
    )
    industry_name: str = Field(
        ...,
        description="用户输入的行业名称，如 '低空经济物流'。",
        min_length=1,
    )
    steps: list[StepOutput] = Field(
        default_factory=list,
        description="已完成步骤的完整记录，按执行顺序排列。每个元素为 StepOutput。",
    )
    final_report: Optional[str] = Field(
        default=None,
        description="最终生成的行业定义报告（Markdown 格式）。在 Step 6 完成后赋值。",
    )


# ============================================================
# StepBudget — 每步的资源约束
# ============================================================

class StepBudget(BaseModel):
    """每步的资源约束，用于成本控制和超时保护。"""

    max_tokens: int = Field(
        ...,
        description="该步骤最大 Token 消耗上限。",
        gt=0,
    )
    timeout_seconds: int = Field(
        ...,
        description="该步骤超时时间（秒）。",
        gt=0,
    )
    max_retries: int = Field(
        default=2,
        description="失败重试次数上限。",
        ge=0,
    )


# ============================================================
# SprintContract — 每步的"完成"标准（类定义保留，v4 不实例化）
# ============================================================

class SprintContract(BaseModel):
    """借鉴 Anthropic Three-Agent Harness：每步执行前协商完成标准。

    v4 版本仅保留类定义作为接口预留，Orchestrator 不实例化它。
    验收标准直接写进各步骤的 task prompt 文本中。
    """

    step_id: str = Field(
        ...,
        description="对应的步骤标识。",
    )
    deliverable: str = Field(
        ...,
        description="本步骤的交付物描述，明确说明产出什么。",
    )
    acceptance_criteria: list[str] = Field(
        ...,
        description="验收标准列表，每个条件必须可检验（testable）。",
    )
    common_failures: list[str] = Field(
        default_factory=list,
        description="常见失败模式，帮助 Agent 提前规避。",
    )
    verification_method: str = Field(
        ...,
        description="验证方式，如 '人工审查'、'C1-C5自检'、'独立Evaluator'。",
    )


# ============================================================
# 预定义的各步骤预算（5 步）
# ============================================================

STEP_BUDGETS: dict[str, StepBudget] = {
    "1_info_collection": StepBudget(
        max_tokens=100000,
        timeout_seconds=120,
        max_retries=2,
    ),
    "2_dimension_screening": StepBudget(
        max_tokens=20000,
        timeout_seconds=60,
        max_retries=2,
    ),
    "3_structure_decision": StepBudget(
        max_tokens=20000,
        timeout_seconds=60,
        max_retries=2,
    ),
    "4_content_generation": StepBudget(
        max_tokens=150000,
        timeout_seconds=180,
        max_retries=2,
    ),
    "5_self_check": StepBudget(
        max_tokens=50000,
        timeout_seconds=60,
        max_retries=2,
    ),
}
