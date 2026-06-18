"""
行业定义 Agent — 主程序 v4 (Demo MVP)

六步执行流程（严格线性，不做 Evaluator-Optimizer 闭环）：
  Step 1: 信息收集（并行搜索 + LLM 总结）
  Step 2: 维度筛选（应用方法论 H1-H4）
  Step 3: 结构决策（设计报告章节结构）
  Step 4: 内容生成（撰写完整报告）
  Step 5: 自检（独立 Evaluator，失败时注入警告而非自动修正）
  Step 6: 输出（组装最终报告）

v4 与 v2 的关键差异：
- 不做 Evaluator-Optimizer 自动修正闭环（Step 5 失败只注入警告）
- 不做 Model Router（单一模型）
- Circuit Breaker 打桩为 call_with_timeout（非完整状态机，仅超时+重试）
- Context Builder 四层（新增任务指令层）

使用方式：
  python frost_agent.py "低空经济物流"
  python frost_agent.py "低空经济物流" --mock
  python frost_agent.py "低空经济物流" --resume
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

from models import ReportState, StepOutput, StepBudget, STEP_BUDGETS
from context_builder import ContextBuilder
from evaluator import evaluate, mock_evaluate
from search import search_with_fallback, mock_search
from harness.circuit_breaker import call_with_timeout
from harness.session_log import SimpleLogger
from harness.checkpoint import save_checkpoint, try_resume


# ============================================================
# 配置常量
# ============================================================

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V4-Pro"

# Step 4 max_tokens：二分查找安全冗余值（候选：16000→12000→10000→8000）
# 当前值 16000 保持与 v4 一致，待二分查找后调整
# 用法：STEP4_MAX_TOKENS=12000 python3 frost_agent.py "低空经济物流"
STEP4_MAX_TOKENS = int(os.getenv("STEP4_MAX_TOKENS", "16000"))

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
        "base_url": os.getenv("LLM_BASE_URL", SILICONFLOW_BASE_URL),
        "model": os.getenv("LLM_MODEL", SILICONFLOW_MODEL),
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
    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 { 到最后一个 }
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
    """剥离 LLM 在报告正文前附加的开场白。

    寻找第一个 # 标题或 --- 分隔符，将之前的内容视为导语删除。
    如果找不到明显的正文标记，返回原文。
    """
    import re
    # 尝试找第一个 Markdown 标题（# 开头）
    m = re.search(r"^#{1,4}\s+", text, re.MULTILINE)
    if m:
        if m.start() > 0:
            return text[m.start():].lstrip("\n")
        # 标题在位置 0，说明文本直接从报告正文开始，无需剥离
        return text
    # 无 Markdown 标题时，尝试找第一个水平分隔线作为正文起点
    m = re.search(r"^---", text, re.MULTILINE)
    if m and m.start() > 0:
        stripped = text[m.start():].lstrip("\n")
        # 如果剥离后内容太短（只剩分隔线），返回原文
        if len(stripped) > 50:
            return stripped
    return text


# ============================================================
# LLM 调用封装
# ============================================================

async def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 16000, timeout: float = 180.0) -> dict[str, Any]:
    """统一的 LLM 调用函数（OpenAI 兼容 SDK，默认走硅基流动 SiliconFlow）。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        max_tokens: 输出 Token 上限（API 参数，控制生成长度）
        timeout: HTTP 请求超时（秒），作为底层兜底；上层 call_with_timeout 提供步骤级超时

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
    response = await client.chat.completions.create(
        model=config["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=max_tokens,
    )
    text = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }
    return {"text": text, "token_usage": usage}


# ============================================================
# Mock LLM 响应
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
# 主流程：Orchestrator（v4：严格线性，不做 E-O 闭环）
# ============================================================

async def run(industry_name: str, force_resume: bool = False) -> str:
    """主执行流程 —— Orchestrator (v4)。

    六步严格线性执行：
      Step 1→2→3→4→5→6，无循环。
      Step 5 失败时注入警告，**不**自动重跑 Step 4。
    """

    # ---- 1. 初始化或恢复 ----
    state = None
    if force_resume:
        state = try_resume(industry_name)
        if state:
            print(f"[恢复] 从 checkpoint 恢复了 {len(state.steps)} 个步骤")
        else:
            print(f"[恢复] 未找到 {industry_name} 的 checkpoint，从头开始")

    if state is None:
        state = ReportState(industry_name=industry_name)

    # ---- 2. 初始化组件 ----
    logger = SimpleLogger(industry_name)
    context_builder = ContextBuilder()
    mock = is_mock_mode()
    mock_search_mode = os.getenv("MOCK_SEARCH", "false").lower() == "true"

    logger.log("start", {"industry": industry_name, "mock": mock, "mock_search": mock_search_mode})
    print(f"\n{'='*60}")
    print(f"行业定义 Agent v4 (Demo MVP)")
    print(f"行业: {industry_name}")
    print(f"模式: {'Mock (LLM+搜索均为预设)' if mock else 'API (硅基流动 DeepSeek-V4-Pro)'}")
    print(f"{'='*60}\n")

    # ---- 3. 确定已完成的步骤（支持 checkpoint 恢复） ----
    completed_ids = {s.step_id for s in state.steps}

    # ---- 4. Step 1: 信息收集 ----
    if "1_info_collection" not in completed_ids:
        await _run_step1(industry_name, state, logger, context_builder, mock, mock_search_mode)
    else:
        print(f"[跳过] Step 1: 信息收集 — 已从 checkpoint 恢复")

    # ---- 5. Step 2: 维度筛选 ----
    if "2_dimension_screening" not in completed_ids:
        await _run_step(2, state, logger, context_builder, mock)
    else:
        print(f"[跳过] Step 2: 维度筛选 — 已从 checkpoint 恢复")

    # ---- 6. Step 3: 结构决策 ----
    if "3_structure_decision" not in completed_ids:
        await _run_step(3, state, logger, context_builder, mock)
    else:
        print(f"[跳过] Step 3: 结构决策 — 已从 checkpoint 恢复")

    # ---- 7. Step 4: 内容生成 ----
    if "4_content_generation" not in completed_ids:
        await _run_step(4, state, logger, context_builder, mock)
    else:
        print(f"[跳过] Step 4: 内容生成 — 已从 checkpoint 恢复")

    # ---- 8. Step 5: 自检 ----
    if "5_self_check" not in completed_ids:
        self_check_warning = await _run_step5(industry_name, state, logger, mock)
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

    # ---- 9. Step 6: 输出 ----
    final_report = await _run_step6(industry_name, state, logger, self_check_warning)

    return final_report


# ============================================================
# 各步骤实现
# ============================================================

async def _run_step1(
    industry_name: str, state: ReportState, logger: SimpleLogger,
    context_builder: ContextBuilder, mock: bool, mock_search_mode: bool,
) -> None:
    """Step 1: 信息收集——并行搜索 + LLM 总结。"""
    step_id = "1_info_collection"
    print(f"\n--- Step 1: 信息收集 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if mock or mock_search_mode or not tavily_key:
        search_result = mock_search(industry_name)
        if not mock and not tavily_key:
            print("  [提示] 无 TAVILY_API_KEY，使用 Mock 搜索")
    else:
        search_result = await search_with_fallback(industry_name, tavily_key)

    logger.log("search_done", {
        "query_count": len(search_result.get("results", {})),
        "errors": search_result.get("error_count", 0),
    })

    context = context_builder.build(step_id, state)
    user_prompt = context + f"\n\n## 搜索结果\n\n{json.dumps(search_result, ensure_ascii=False, indent=2)}"
    llm_result = await call_with_timeout(
        lambda: call_llm(context, user_prompt),
        timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
    )
    logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})
    parsed = _parse_json_response(llm_result["text"])

    state.steps.append(StepOutput(
        step_id=step_id, step_label="信息收集",
        reasoning=parsed.get("summary", "")[:300] or "（LLM 未返回摘要，已从搜索结果生成）",
        confidence="中：Mock 模式" if mock else "中：LLM 生成",
        result=parsed, abandoned=[],
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=llm_result.get("token_usage"),
    ))
    save_checkpoint(state, step_id)
    logger.log("step_complete", {"step_id": step_id, "confidence": state.steps[-1].confidence})
    print(f"  完成 — 置信度: {state.steps[-1].confidence}")


async def _run_step(
    step_index: int, state: ReportState, logger: SimpleLogger,
    context_builder: ContextBuilder, mock: bool,
) -> None:
    """Step 2-4 的通用模板：构建上下文 → 调用 LLM → 解析 → 记录。"""
    step_id = STEPS_DEFINITION[step_index - 1][0]
    step_label = STEPS_DEFINITION[step_index - 1][1]
    print(f"\n--- Step {step_index}: {step_label} 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    context = context_builder.build(step_id, state)
    # Step 4 使用 STEP4_MAX_TOKENS（支持环境变量二分查找），其他步骤用默认值
    step4_max_tokens = STEP4_MAX_TOKENS if step_id == "4_content_generation" else 16000
    llm_result = await call_with_timeout(
        lambda: call_llm(context, context, max_tokens=step4_max_tokens),
        timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
    )
    logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})
    parsed = _parse_json_response(llm_result["text"])

    # 构建 reasoning 和 abandoned
    if step_id == "2_dimension_screening":
        reasoning = parsed.get("reasoning", "")[:300] or "（LLM 未返回推理，已根据方法论完成维度筛选）"
        abandoned = [f"{a.get('dimension', '未知')}: {a.get('reason', '无理由')}"
                      for a in parsed.get("abandoned_dimensions", [])]
        extra = f" — 选中 {len(parsed.get('selected_dimensions', []))} 个维度，放弃 {len(abandoned)} 个"
    elif step_id == "3_structure_decision":
        reasoning = parsed.get("reasoning", "")[:300] or "（LLM 未返回推理，已根据维度筛选结果设计章节结构）"
        abandoned = []
        extra = f" — {len(parsed.get('chapters', []))} 章"
    else:  # Step 4: 剥离开场白后存为报告文本
        report_text = _strip_preamble(llm_result["text"])
        parsed = {"report_text": report_text}
        reasoning = f"生成了 {len(report_text)} 字符的报告"
        abandoned = []
        extra = f" — 报告 {len(report_text)} 字符"

    state.steps.append(StepOutput(
        step_id=step_id, step_label=step_label,
        reasoning=reasoning,
        confidence="中：Mock 模式" if mock else "中：LLM 生成",
        result=parsed, abandoned=abandoned,
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=llm_result.get("token_usage"),
    ))
    save_checkpoint(state, step_id)
    logger.log("step_complete", {"step_id": step_id})
    print(f"  完成{extra}")


def _build_self_check_warning(failed: list[str], issues: list[dict]) -> str:
    """构建 Step 5 失败时的警告文本。"""
    if not failed:
        return ""
    warning_lines = [
        "\n\n---\n\n",
        "## 自检未通过\n\n",
        f"以下维度未通过审查：{', '.join(failed)}\n\n",
    ]
    for issue in issues:
        problem = issue.get("problem", issue.get("dimension", ""))
        warning_lines.append(f"- {problem}\n")
    warning_lines.append("\n**请人工审查后再使用此报告。**\n")
    return "".join(warning_lines)


async def _run_step5(
    industry_name: str, state: ReportState, logger: SimpleLogger, mock: bool,
) -> str:
    """Step 5: 独立 Evaluator 自检。

    v4 关键约束：失败时只注入警告，不自动重跑 Step 4。
    返回警告文本（空字符串表示全部通过）。
    """
    step_id = "5_self_check"
    print(f"\n--- Step 5: 自检 开始 ---")
    logger.log("step_start", {"step_id": step_id})

    report_to_check = _get_report_from_state(state)

    # 包装 llm_call_fn 供 evaluator 使用（evaluator 用 keyword args 调用）
    # 捕获 token_usage 供 P0-3 成本审计（v1.2 修复：原版丢弃了 token_usage）
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
        )

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

    state.steps.append(StepOutput(
        step_id=step_id, step_label="自检",
        reasoning="".join(reasoning_parts),
        confidence=confidence,
        result=eval_result, abandoned=[],
        methodology_ref=METHODOLOGY_REFS[step_id],
        token_usage=step5_token_usage if step5_token_usage else None,
    ))
    save_checkpoint(state, step_id)
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
    industry_name: str, state: ReportState, logger: SimpleLogger,
    self_check_warning: str,
) -> str:
    """Step 6: 输出——组装最终报告，统计 Token，写入文件。"""
    print(f"\n--- Step 6: 输出 开始 ---")

    report_text = _get_report_from_state(state)
    final_report = self_check_warning + report_text

    # Token 统计
    total_tokens = sum(
        s.token_usage.get("total_tokens", 0)
        for s in state.steps if s.token_usage
    )
    final_report += (
        f"\n\n---\n\n"
        f"*总 Token 消耗: {total_tokens} | 步骤数: {len(state.steps)}*"
    )

    # P0-3 成本审计：打印每步 Token 明细
    print(f"\n  Token 明细（P0-3 成本审计）:")
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

    state.final_report = final_report
    logger.log("complete", {"report_length": len(final_report), "total_tokens": total_tokens})
    save_checkpoint(state, "6_output")

    # 保存到文件
    reports_dir = Path(os.getenv("REPORTS_DIR", str(PROJECT_ROOT / "reports")))
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = industry_name.replace("/", "_").replace(" ", "_")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"{safe_name}_{timestamp}_行业定义报告.md"
    report_path.write_text(final_report, encoding="utf-8")

    print(f"  报告已保存到: {report_path}")
    print(f"  总 Token: {total_tokens}")
    print(f"--- Step 6: 输出 完成 ---")

    print(f"\n{'='*60}")
    print(f"任务完成！")
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
        description="行业定义 Agent v4 — Demo MVP",
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
