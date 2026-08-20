"""
行业定义 Agent — Pydantic 数据模型 (v5.2)

本模块定义了 Agent 全流程使用的核心数据结构。
v5.2 相比 v4 的变更：
- 新增 QualityFlag 模型：跨步骤异常传递的标准化格式（Pydantic 约束 + severity 映射代码化）
- StepOutput 新增 quality_flags 字段：该步骤产生的降级标记列表
- STEP_BUDGETS Step 1 timeout 120→180（v5.2 搜索补搜循环需要额外时间）
- 新增 QualityGateError 异常：生产步骤触发 or_fallback_result(high) 时终止流程

v4 继承（保持不变）：
- SprintContract 类定义保留，但不实例化（接口不堵死）
- StepOutput.token_usage 字段，用于顺手记录 LLM 调用消耗
- ReportState 无 fix_attempt 字段（v4 不做 E-O 闭环）

关键设计决策（回应 architecture-critic 审查 P0 项）：
- QualityFlag 由 Orchestrator 代码在检测到降级时注入，不依赖 LLM 自报告（可靠性 + 0 token 成本）
- severity 映射表通过 field_validator 代码化，防止人工填错
- category 用 str 允许扩展，但 KNOWN_CATEGORIES + 未知类别 warnings.warn 防拼写错误
- field 严格只存字段名（如 'official_definitions'），比例信息放 detail
- "or" = orchestrator-level recovery（编排层兜底），指步骤无法产出正常结果时由 Orchestrator 注入占位符
"""

from __future__ import annotations

import warnings
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================
# QualityFlag — 跨步骤异常传递的标准化格式（v5.2 新增）
# ============================================================

# 已知 category 注册表（允许扩展，但新增类别需在此登记并更新文档）
#
# v5.2 Kimi Q1 补丁（2026-06-28）：新增 category 检查清单
# B1-1 SSOT 重构（2026-06-29）：terminates_flow 字段成为唯一终止判断依据，检查清单简化
# 新增 category 时必须同步检查以下消费点：
#   1. CATEGORY_DEFAULT_SEVERITY（本文件下方）— 必须同步添加默认 severity
#   2. QualityFlag.terminates_flow 字段 — 创建 flag 实例时按需设置（per-instance，非 category 级）
#   3. frost_agent._check_quality_gate — 改为基于 terminates_flow 扫描，新 category 自动兼容
#   4. frost_agent._build_quality_flags_summary（Step 6）— 按 severity 自动分组，自动兼容
#   5. 离线统计 — 若为新失败类型，_record_fm_failure_flag 的 [type=xxx] 结构化前缀需同步扩展
#   B1-1：消除 category 硬编码，terminates_flow=True 是唯一终止判断依据
KNOWN_CATEGORIES: set[str] = {
    "llm_empty_field",          # LLM 返回空字段
    "search_partial_failure",   # 搜索部分失败（severity 按失败比例运行时计算）
    "json_parse_fallback",      # JSON 解析失败降级
    "or_fallback_result",       # result 字段被占位符替代（high，生产步骤终止）
    "or_fallback_reasoning",    # reasoning 字段被占位符替代（medium，不终止）
    "timeout_retry",            # 超时后重试成功（low；注意语义=重试成功，不是放弃）
    "data_gaps_remaining",      # v5.2 新增：补搜后仍有信息缺口
    "fm_review_skipped",        # v5.2 修复 P2 #5：FM 审查失败（timeout/parse_error/exception/empty，靠 detail 区分）
    "search_phase_timeout",     # v5.2 修复2：搜索阶段整体超时放弃（不重试、未成功，与 timeout_retry 语义相反）
}

# category → 默认 severity 映射（search_partial_failure 需运行时计算，不在此映射）
CATEGORY_DEFAULT_SEVERITY: dict[str, str] = {
    "llm_empty_field": "medium",
    "json_parse_fallback": "medium",
    "or_fallback_result": "high",       # result 是报告正文内容，占位直接污染输出
    "or_fallback_reasoning": "medium",  # reasoning 是推理痕迹，占位只影响可追溯性
    "timeout_retry": "low",
    "data_gaps_remaining": "medium",
    "fm_review_skipped": "medium",      # v5.2 修复：FM 审查失败=补搜循环失效，但首轮搜索结果仍可用，Step 1 可继续
    "search_phase_timeout": "high",     # v5.2 修复2：搜索阶段整体被砍掉，无搜索结果可用，等同于搜索全失败
}


class QualityFlag(BaseModel):
    """跨步骤异常传递的标准化格式（v5.2 新增）。

    设计约束：
    - 由 Orchestrator 代码在检测到降级时注入，不依赖 LLM 自报告
    - 写入 StepOutput.quality_flags 独立字段，不污染 result
    - severity 映射通过 field_validator 强制一致性
    - category 允许扩展，但未知类别会触发 warnings.warn

    术语定义：
    - "or" = orchestrator-level recovery（编排层兜底），指步骤无法产出正常结果时
      由 Orchestrator 注入占位符而非让步骤失败
    - or_fallback_result(high) vs or_fallback_reasoning(medium) 的分级依据：
      result 是报告正文内容，占位会直接污染输出；reasoning 是推理痕迹，占位只影响可追溯性
    """

    category: str = Field(
        ...,
        description=(
            "降级类别。预定义值见 KNOWN_CATEGORIES。"
            "允许扩展，但新增类别需在 KNOWN_CATEGORIES 登记并更新文档。"
        ),
    )
    field: str = Field(
        ...,
        description=(
            "受影响的字段名（严格只存字段名，如 'summary'、'official_definitions'）。"
            "比例信息（如 '2/3 失败'）放 detail 字段，不混入 field。"
        ),
    )
    severity: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "严重程度。high=影响报告质量（生产步骤终止），"
            "medium=有降级但质量可接受，low=仅记录。"
            "默认映射见 CATEGORY_DEFAULT_SEVERITY，validator 会检查一致性。"
        ),
    )
    detail: str = Field(
        default="",
        description="可选的详细说明，如 'Tavily API 限流，query 3 失败（2/3 失败）'。",
    )
    terminates_flow: bool = Field(
        default=False,
        description=(
            "B1-1 新增：该 flag 是否应触发流程终止（SSOT 元数据）。"
            "仅 severity='high' 时有效。"
            "_check_quality_gate 统一扫描此字段决定是否 raise QualityGateError。"
            "per-instance 设置（非 category 级），消除原 category 硬编码的反模式。"
        ),
    )

    @field_validator("category")
    @classmethod
    def _warn_unknown_category(cls, v: str) -> str:
        """未知类别触发警告（不 raise，允许扩展），便于审计拼写错误。"""
        if v not in KNOWN_CATEGORIES:
            warnings.warn(
                f"QualityFlag category='{v}' 未在 KNOWN_CATEGORIES 中登记，"
                f"请确认拼写并更新注册表。已知: {sorted(KNOWN_CATEGORIES)}",
                stacklevel=2,
            )
        return v

    @model_validator(mode="after")
    def _check_severity_consistency(self) -> "QualityFlag":
        """检查 severity 与 category 默认映射是否一致。

        若 category 有默认映射且 severity 不匹配，raise ValueError。
        search_partial_failure 无默认映射（需运行时按比例计算），跳过检查。
        实现者如确需覆盖默认 severity，请在 detail 中写明 '[severity-overridden] 理由'。

        使用 model_validator(mode='after') 而非 field_validator，
        因为 severity 字段在 detail 之前定义，field_validator 无法访问 detail。
        """
        expected = CATEGORY_DEFAULT_SEVERITY.get(self.category)
        if expected and self.severity != expected:
            # 检查 detail 是否声明了覆盖理由
            if "[severity-overridden]" in self.detail:
                return self  # 显式覆盖，允许
            raise ValueError(
                f"category='{self.category}' 的 severity 应为 '{expected}'，"
                f"实际为 '{self.severity}'。"
                f"如确需覆盖，请在 detail 中写明 '[severity-overridden] 理由'。"
            )
        return self

    @model_validator(mode="after")
    def _check_terminates_flow_consistency(self) -> "QualityFlag":
        """B1-1 新增：terminates_flow=True 时强制 severity='high'。

        防止开发者误设 terminates_flow=True 但 severity=medium 导致
        _check_quality_gate 静默不终止（_check_quality_gate 只扫描 high）。
        """
        if self.terminates_flow and self.severity != "high":
            raise ValueError(
                f"terminates_flow=True 时 severity 必须为 'high'，"
                f"实际为 '{self.severity}'。terminates_flow 表示触发流程终止，"
                f"仅 severity='high' 时 _check_quality_gate 才会扫描。"
            )
        return self


def flag_search_partial_failure(failed: int, total: int, field_name: str, detail: str = "") -> QualityFlag:
    """工厂函数：按失败比例计算 search_partial_failure 的 severity。

    v5.2 新增（回应 architecture-critic 薄弱点 2）：统一比例计算逻辑，
    避免各调用点自己算 errors/total 出现不一致。

    判定规则：
    - 失败比例 >= 0.6（含全失败）→ high
    - 失败比例 >= 1/3（约 0.333，1/3 失败）→ medium
    - 失败比例 < 1/3 → low（但 search_partial_failure 通常不会到这）

    B1-1 注意：本工厂函数默认 terminates_flow=False。
    severity=high 不等于终止——终止由调用方按场景决定是否设 terminates_flow=True。
    例：field_name='all_queries'（全失败）时调用方应追加 terminates_flow=True；
    field_name='official_definitions'（部分失败）时保持 terminates_flow=False（仍有结果可用）。

    Args:
        failed: 失败的 query 数
        total: 总 query 数
        field_name: 受影响的产出字段名（如 'official_definitions'）
        detail: 额外说明
    """
    ratio = failed / total if total else 1.0
    if ratio >= 0.6:
        severity: Literal["high", "medium", "low"] = "high"
    elif ratio >= 1 / 3:  # 1/3 = 0.333...，用分数避免浮点误差
        severity = "medium"
    else:
        severity = "low"
    full_detail = f"{failed}/{total} 个搜索失败"
    if detail:
        full_detail += f" — {detail}"
    return QualityFlag(
        category="search_partial_failure",
        field=field_name,
        severity=severity,
        detail=full_detail,
    )


class QualityGateError(Exception):
    """v5.2 新增：生产步骤触发终止性降级时抛出。

    当 Step 1-4 的 quality_flags 含 or_fallback_result(high) 时，
    Orchestrator 抛出此异常终止流程，避免基于垃圾输入继续生成报告。
    """
    pass


# ============================================================
# StepOutput — 每一步的输出（强制包含推理痕迹）
# ============================================================

class StepOutput(BaseModel):
    """每一步的输出结构，强制包含 reasoning 和 confidence。

    v5.2 新增 quality_flags 字段：该步骤产生的降级标记列表。
    """

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
    quality_flags: list[QualityFlag] = Field(
        default_factory=list,
        description=(
            "v5.2 新增：该步骤产生的降级标记列表。空列表表示无降级。"
            "由 Orchestrator 代码在检测到降级时注入（不依赖 LLM 自报告）。"
            "Step 6 汇总到报告尾部，按严重度分组。"
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
        timeout_seconds=180,  # v5.2: 120 → 180（搜索补搜循环：首轮3 query + FM审查 + 最多2个补搜 query，最坏额外 ~45s）
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
