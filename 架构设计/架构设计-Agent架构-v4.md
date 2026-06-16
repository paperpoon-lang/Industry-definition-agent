
# 架构设计 — Agent 架构 v4（Demo MVP）

> 版本：v4.0 | 日期：2026-06-05 | 给 Trae 的开发 Spec
>
> v4 基于 v3（Demo MVP）的架构评审结果迭代。变更摘要：
> - Context Builder：三层 → 四层（新增任务指令层）
> - Step 5 失败处置：增加警告注入逻辑
> - methodology_loader：修正 SLICE_MAP 关键词，增加空切片降级
> - 新增成本/延迟估算章节
>
> v4 继承 v3 的设计立场："跑一次就出高质量报告"的 Demo，不是 7×24 运行的生产系统。
> 核心策略不变：对报告质量有直接影响的组件完整实现，基础设施组件保留接口、实现从简。

---

## 一、总体架构

```
┌─────────────────────────────────────────────┐
│              Orchestrator                    │
│           (frost_agent.py)                   │
│                                             │
│   初始化 → 六步管线 → Step 5 结果判断        │
│        → 注入警告（若 fail）→ 输出报告        │
│                                             │
│   每步：Context Builder 四层组装 → LLM 调用   │
│        → 结果校验 → 写 Checkpoint            │
└──────────────────┬──────────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│  Step 1  │ │  Step 2  │ …│  Step 6  │
│ 信息收集  │ │ 维度筛选  │  │   输出    │
│ (搜索并行)│ │          │  │+ 警告标记  │
└──────────┘ └──────────┘ └──────────┘
     │             │              │
     └─────────────┼──────────────┘
                   ▼
        ┌──────────────────────┐
        │   Independent        │
        │   Evaluator          │
        │   (Step 5, 独立 LLM)  │
        └──────────────────────┘
```

---

## 二、完整做（6 项）

### 2.1 核心 4 文件 + 六步管线

| 文件 | 行数估计 | 内容 |
|---|---|---|
| `frost_agent.py` | ~280 行 | Orchestrator + 六步逻辑 + Step 5 失败警告 + CLI 入口 |
| `models.py` | ~80 行 | State Schema（含 StepBudget、SprintContract 定义但实例化从简） |
| `methodology_loader.py` | ~90 行 | 加载 `方法论-v2.md` + 按章节标题正则切分 + 空切片降级 |
| `requirements.txt` | ~10 行 | pydantic, openai, tavily-python, python-dotenv |

### 2.2 Context Builder（四层修复版）

v3 的三层组装丢失了关键的任务指令层。v4 增加第四层——步骤级任务指令（包含行业名 + 具体任务描述 + 关键约束），放在方法论切片之后、前序摘要之前。

```python
# context_builder.py (~90 行)

class ContextBuilder:
    """四层上下文组装：静态身份 + 方法论切片 + 任务指令 + 前序摘要"""

    def build(self, step_id: str, state: ReportState) -> str:
        parts = [
            self._static_identity(),                        # Layer 1
            self._methodology_slice(step_id),               # Layer 2
            self._task_directive(step_id, state.industry_name),  # Layer 3（v4 新增）
            self._previous_summary(state),                  # Layer 4
        ]
        return "\n\n---\n\n".join(parts)

    def _static_identity(self) -> str:
        return (
            "你是行业定义分析助手。\n"
            "你的任务是：输入行业名称，产出符合行业定义方法论标准的行业定义报告。\n"
            "报告不包含竞争排名、市场规模预测、投资建议。"
        )

    def _methodology_slice(self, step_id: str) -> str:
        return methodology_loader.load_slice(step_id)

    def _task_directive(self, step_id: str, industry: str) -> str:
        """当前步骤的具体任务指令（v4 新增）"""
        template = STEP_TASKS.get(step_id, "请执行当前步骤。")
        return f"## 当前任务\n\n{template.format(industry=industry)}"

    def _previous_summary(self, state: ReportState) -> str:
        if not state.steps:
            return ""
        lines = ["## 前序步骤摘要\n"]
        for step in state.steps[-3:]:
            key = step.result.get("summary", step.reasoning[:150])
            lines.append(f"- **{step.step_label}**: {key} (置信度: {step.confidence})")
        return "\n".join(lines)


# 步骤级任务指令（v4 新增）
STEP_TASKS = {
    "1_info_collection": (
        "请搜索并整理以下行业的基础信息：{industry}。\n"
        "要求：覆盖官方定义、关键政策/标准、结构性影响因素、相邻行业。\n"
        "标注信息来源和可信度（P0-P3）。"
    ),
    "2_dimension_screening": (
        "基于 Step 1 的信息，对行业「{industry}」应用 H1-H4 维度筛选原则。\n"
        "选出核心维度，并明确记录：选了什么、放弃了什么、为什么。\n"
        "验收标准：覆盖 ≥ 2 个独立侧，每个维度有经营结果传导。"
    ),
    "3_structure_decision": (
        "为行业「{industry}」设计报告结构。\n"
        "每章对应 Step 2 的至少一个维度。\n"
        "严格禁止出现竞争格局/市场规模/投资建议类章节。"
    ),
    "4_content_generation": (
        "为行业「{industry}」撰写完整的行业定义报告正文。\n"
        "严格禁止：企业排名、市场份额、竞争格局分析、市场规模预测、投资建议。\n"
        "每个关键判断必须附带推理链和置信度标注。\n"
        "所有数据必须标注来源和可信度。"
    ),
    "5_self_check": (
        "对行业「{industry}」的报告执行 C1-C5 自检清单。\n"
        "你是一个严格的审查员，倾向于发现问题而非确认一切正常。"
    ),
}
```

### 2.3 搜索并行 + 结果压缩

```python
# search.py (~80 行)

import asyncio

SEARCH_QUERIES = [
    "{industry} 行业定义 官方定义 标准",
    "{industry} 政策 监管 产业链",
    "{industry} 边界 与相邻行业区分",
]

async def search_parallel(industry: str, max_chars_per_result: int = 1500) -> dict:
    """并行搜索 + 结果截断压缩"""
    queries = [q.format(industry=industry) for q in SEARCH_QUERIES]

    results = await asyncio.gather(
        *[tavily_search(q) for q in queries],
        return_exceptions=True,
    )

    merged = {}
    for q, r in zip(queries, results):
        if isinstance(r, Exception):
            merged[q] = [{"title": "搜索失败", "content": str(r), "url": ""}]
        else:
            for item in r:
                if len(item.get("content", "")) > max_chars_per_result:
                    item["content"] = item["content"][:max_chars_per_result] + "...[截断]"
            merged[q] = r

    return merged

async def search_with_fallback(industry: str) -> dict:
    try:
        return await search_parallel(industry)
    except Exception:
        return await tavily_search(industry)
```

### 2.4 StepBudget（数据模型，不强执行）

```python
# models.py

class StepBudget(BaseModel):
    max_tokens: int
    timeout_seconds: int
    max_retries: int = 2

STEP_BUDGETS = {
    "1_info_collection":    StepBudget(100000, 120, 2),
    "2_dimension_screening": StepBudget(20000,  60,  2),
    "3_structure_decision":  StepBudget(20000,  60,  2),
    "4_content_generation": StepBudget(150000, 180, 2),
    "5_self_check":         StepBudget(50000,  60,  2),
}
```

不强执行：不拦截超支，但每步 LLM 调用后顺手记录 `token_usage`，出问题时有参照。

### 2.5 Independent Evaluator（Step 5 独立审查）

```python
# evaluator.py (~60 行)

EVALUATOR_PROMPT = """你是一个严格的行业定义报告审查员。

审查维度（C1-C5）：
C1. 区分度测试：遮住行业名称，读者能否从定义本身判断出是哪个行业？
C2. 废话过滤：是否存在对任何行业都成立的通用陈述？
C3. 结构性测试：核心逻辑是否独立于短期市场数据？
C4. 边界清晰度：读者能否说清楚"什么不是这个行业"？
C5. 推理可见：每个关键判断是否有"为什么"的解释？

对每个维度输出：PASS/FAIL + 具体问题。
总体输出：pass / fail_with_fixes + failed_dimensions 列表 + fixes_required 列表。"""

async def evaluate(report: str, industry_name: str) -> dict:
    """独立 LLM 调用——不同的 prompt，不传入生成过程的 reasoning"""
    result = await llm_call(
        system=EVALUATOR_PROMPT,
        user=f"行业：{industry_name}\n\n报告：\n{report}",
    )
    return parse_evaluation(result)
```

关键约束：Evaluator 只看最终报告文本，不接收 Step 1-4 的 reasoning。

### 2.6 methodology_loader（按 step_id 切片 + 空切片降级）

```python
# methodology_loader.py (~90 行)

import re
from pathlib import Path

# step_id → 需要加载的方法论章节关键词映射（v4 修正）
SLICE_MAP = {
    "1_info_collection":       ["信息优先级", "参考框架", "Hard Rules"],
    "2_dimension_screening":   ["维度筛选原则", "Heuristics", "自检清单"],
    "3_structure_decision":    ["报告结构", "范围约束"],
    "4_content_generation":    ["Hard Rules", "推理展示", "范围约束"],
    "5_self_check":            ["自检清单"],
}

_METHODOLOGY_CACHE: str | None = None

def load_methodology(path: str = "方法论-v2.md") -> str:
    """加载方法论文档（带缓存）"""
    global _METHODOLOGY_CACHE
    if _METHODOLOGY_CACHE is None:
        _METHODOLOGY_CACHE = Path(path).read_text(encoding="utf-8")
    return _METHODOLOGY_CACHE

def load_slice(step_id: str) -> str:
    """按 step_id 返回相关的方法论章节"""
    full = load_methodology()
    keywords = SLICE_MAP.get(step_id, [])

    # 按 ## 标题切分，取包含关键词的章节
    sections = re.split(r'(?=^## )', full, flags=re.MULTILINE)
    matched = [s for s in sections if any(kw in s for kw in keywords)]

    # v4 新增：空切片降级
    if not matched or sum(len(s) for s in matched) < 100:
        print(f"[警告] Step {step_id} 的方法论切片为空或过短，回退到全量方法论")
        return full

    return "\n\n".join(matched)
```

**v3→v4 修正说明**：Step 4 的关键词从 `"内容生成"` 改为 `"范围约束"`。`"内容生成"` 在方法论文档中没有对应章节标题，仅出现在七、执行流程的代码块中——匹配到的是一个不含实际规则的流程描述。而 `"范围约束"` 匹配到三.3 报告范围约束，这正是 Step 4 生成报告时最需要的"不能写什么"的约束。同时 `"Hard Rules"`（二节，含 R1-R5）和 `"推理展示"`（四节，含推理展示要求）保持不变。

---

## 三、打桩做（5 项）

### 3.1 Circuit Breaker → `call_with_retry()`

```python
# harness/circuit_breaker.py (~20 行，打桩)

import asyncio

async def call_with_retry(fn, max_retries: int = 2):
    """简化版：指数退避重试。未来可替换为完整 CircuitBreaker。"""
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)
```

### 3.2 Session Event Log → `SimpleLogger`

```python
# harness/session_log.py (~30 行，打桩)

import json
from datetime import datetime

class SimpleLogger:
    """简化版：print + 可选文件写入。未来可替换为 SessionEventLog。"""

    def __init__(self, industry_name: str):
        self.industry = industry_name

    def log(self, event_type: str, data: dict):
        msg = f"[{datetime.now():%H:%M:%S}] [{event_type}] {json.dumps(data, ensure_ascii=False)}"
        print(msg)
```

### 3.3 Checkpoint → `save_checkpoint()` / `try_resume()`

```python
# harness/checkpoint.py (~40 行，打桩)

import json
from pathlib import Path

CHECKPOINT_DIR = Path("checkpoints")
CHECKPOINT_DIR.mkdir(exist_ok=True)

def save_checkpoint(state: ReportState, step_id: str):
    """保存当前 State 到 JSON 文件（覆盖写入）"""
    path = CHECKPOINT_DIR / f"{state.industry_name}.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

def try_resume(industry_name: str) -> ReportState | None:
    """尝试从 checkpoint 恢复。存在就读取，不存在返回 None。"""
    path = CHECKPOINT_DIR / f"{industry_name}.json"
    if not path.exists():
        return None
    try:
        return ReportState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
```

### 3.4 Sprint Contract → prompt 内嵌

不创建 SprintContract 对象，不实现协商流程。把验收标准直接写进 `STEP_TASKS`（见 2.2 节）对应步骤的 task prompt。`SprintContract` 数据模型保留在 `models.py` 中（接口不堵死），但 Orchestrator 中不实例化。

### 3.5 Token Audit → StepOutput 字段

```python
# models.py — StepOutput 增加字段

class StepOutput(BaseModel):
    # ... 原有字段 ...
    token_usage: dict | None = None  # {"input": 1234, "output": 567, "model": "xxx"}
```

每步 LLM 调用后顺手填入，报告输出时附一行统计。不做持久化审计。

---

## 四、不做（3 项）

| 功能 | 不做原因 |
|---|---|
| **Evaluator-Optimizer 自动修正闭环** | 改变行为契约（项目 Brief 约束 #3："不通过则标记，不允许直接输出"），Demo 不需要全自动修正。v4 改为 Step 5 失败时注入警告标记到报告头部。 |
| **Model Router（多模型降级链）** | Demo 用单一模型，换模型引入的行为差异是噪音。成本优化在 Demo 阶段优先级低于功能正确性。 |
| **methodology/ 目录拆分** | Demo 阶段单文件 + 正则切分够用。方法论稳定后再重构，不影响管线。 |

---

## 五、成本与延迟估算

> 以下为推测值，标注为 `[推测]`，待首次实际运行后更新为实测数据。

### 5.1 单次运行成本（以 deepseek-v4-pro 计价）

| 步骤 | 估计 input tokens | 估计 output tokens | 估计 API 成本 [推测] |
|------|-------------------|--------------------|---------------------|
| Step 1: 搜索+总结 | ~8,000 | ~2,000 | ~$0.0045 |
| Step 2: 维度筛选 | ~6,000 | ~1,500 | ~$0.0033 |
| Step 3: 结构决策 | ~5,000 | ~1,000 | ~$0.0025 |
| Step 4: 内容生成 | ~12,000 | ~8,000-15,000 | ~$0.012-0.020 |
| Step 5: 自检 | ~10,000 | ~1,500 | ~$0.0045 |
| **端到端总计** | **~41,000** | **~18,000-21,000** | **~$0.027-0.035** |

### 5.2 单次运行延迟（以 deepseek-v4-pro 计价）

| 步骤 | 预估耗时 [推测] | 说明 |
|------|----------------|------|
| Step 1: 搜索并行 | 3-8 秒 | 3 个 Tavily 搜索并行 + 结果截断 |
| Step 1: LLM 总结 | 5-15 秒 | 取决于模型负载 |
| Step 2: 维度筛选 | 5-10 秒 | |
| Step 3: 结构决策 | 5-10 秒 | |
| Step 4: 内容生成 | 15-35 秒 | 长文生成，最慢的一步 |
| Step 5: 自检 | 5-15 秒 | |
| Step 6: 输出 | < 1 秒 | 纯文本拼接 |
| **端到端总计** | **~40-90 秒** | |

**演示建议**：端到端约 1 分钟。演示时若需控制时间，可预先运行并保存结果。Step 4 是最大瓶颈——长报告行业可能需要 90 秒，短报告约 40 秒。

---

## 六、Orchestrator 逻辑（v4）

```python
# frost_agent.py 骨架 (~280 行)

import asyncio
import sys
from models import ReportState, StepOutput, STEP_BUDGETS
from context_builder import ContextBuilder
from evaluator import evaluate
from methodology_loader import load_slice
from harness.circuit_breaker import call_with_retry
from harness.session_log import SimpleLogger
from harness.checkpoint import save_checkpoint, try_resume
from search import search_with_fallback

# ─── 六步函数 ───

async def step1_info_collection(state: ReportState) -> StepOutput:
    """并行搜索 + LLM 总结"""
    search_results = await call_with_retry(
        lambda: search_with_fallback(state.industry_name)
    )
    context = ContextBuilder().build("1_info_collection", state)
    # LLM 调用生成总结...
    return StepOutput(...)

async def step2_dimension_screening(state: ReportState) -> StepOutput:
    context = ContextBuilder().build("2_dimension_screening", state)
    # LLM 推理...
    return StepOutput(...)

# ... step3, step4 类似 ...

async def step5_self_check(state: ReportState) -> StepOutput:
    """独立 Evaluator 审查"""
    report_text = _assemble_report_draft(state)
    eval_result = await evaluate(report_text, state.industry_name)
    return StepOutput(
        step_id="5_self_check",
        step_label="自检",
        reasoning=f"独立Evaluator审查: {eval_result.get('overall', 'unknown')}",
        confidence="high" if eval_result.get("overall") == "pass" else "low",
        result=eval_result,
        methodology_ref="5.自检清单(C1-C5)",
    )

def step6_output(state: ReportState) -> str:
    """组装最终报告（含自检失败时注入的警告标记）"""
    report_body = _assemble_report_body(state)
    header = ""
    if hasattr(state, "_self_check_warning"):
        header = state._self_check_warning
    footer = _methodology_appendix(state)
    # Token 统计
    token_summary = _build_token_summary(state)
    return header + report_body + footer + token_summary


# ─── 主流程 ───

async def run(industry_name: str) -> str:
    # 1. 尝试恢复
    state = try_resume(industry_name) or ReportState(industry_name=industry_name)
    logger = SimpleLogger(industry_name)
    logger.log("start", {"industry": industry_name})

    # 2. 执行未完成的步骤
    steps = [
        ("1_info_collection",      step1_info_collection),
        ("2_dimension_screening",  step2_dimension_screening),
        ("3_structure_decision",   step3_structure_decision),
        ("4_content_generation",   step4_content_generation),
        ("5_self_check",           step5_self_check),
    ]

    completed = {s.step_id for s in state.steps}
    for step_id, step_fn in steps:
        if step_id in completed:
            logger.log("skip", {"step_id": step_id, "reason": "already completed"})
            continue

        logger.log("step_start", {"step_id": step_id})
        result = await call_with_retry(lambda: step_fn(state))
        state.steps.append(result)
        save_checkpoint(state, step_id)
        logger.log("step_complete", {"step_id": step_id, "confidence": result.confidence})

    # 3. Step 5 结果判断（v4 新增）
    step5 = next((s for s in state.steps if s.step_id == "5_self_check"), None)
    if step5 and step5.result.get("overall") != "pass":
        failed = step5.result.get("failed_dimensions", [])
        issues = step5.result.get("issues", [])

        warning = (
            "\n\n---\n\n"
            "## ⚠️ 自检未通过\n\n"
            f"以下维度未通过审查：{', '.join(failed)}\n\n"
        )
        for issue in issues:
            warning += f"- {issue}\n"
        warning += "\n**请人工审查后再使用此报告。**\n"
        state._self_check_warning = warning

        logger.log("self_check_failed", {
            "failed_dimensions": failed,
            "issues": issues,
        })
        print(f"\n[警告] 自检未通过 — 失败维度: {failed}")
        print("[警告] 报告已生成但包含审查警告，请人工复核\n")

    # 4. 输出
    final_report = step6_output(state)
    logger.log("complete", {"report_length": len(final_report)})
    return final_report

if __name__ == "__main__":
    industry = sys.argv[1] if len(sys.argv) > 1 else "低空经济物流"
    report = asyncio.run(run(industry))
    print(report)
```

---

## 七、文件清单与规模

```
行业定义agent/
├── frost_agent.py              # ~280 行  Orchestrator + 六步 + Step 5 警告 + CLI
├── models.py                   # ~80 行   Schema + Budget + SprintContract定义
├── methodology_loader.py       # ~90 行   加载 + 按章节切分 + 空切片降级
├── context_builder.py          # ~90 行   四层上下文组装（v4 新增任务指令层）
├── evaluator.py                # ~60 行   Independent Evaluator
├── search.py                   # ~80 行   并行搜索 + 压缩 + 降级
├── requirements.txt            # ~10 行
│
├── harness/                    # 打桩组件（3 个文件，每个 20-40 行）
│   ├── __init__.py
│   ├── circuit_breaker.py      # ~20 行  call_with_retry
│   ├── session_log.py          # ~30 行  SimpleLogger
│   └── checkpoint.py           # ~40 行  save / try_resume
│
├── 方法论-v2.md                # 单文件（不做拆分）
├── checkpoints/                # 自动生成
├── logs/                       # 自动生成
└── reports/                    # 自动生成
```

**总计：~760 行 Python**（含注释和空行）。

---

## 八、验收标准

| 标准 | 验证方式 |
|---|---|
| `python frost_agent.py "低空经济物流"` 稳定产出报告 | 手动运行 3 次，3 次成功 |
| 方法论附注可见完整维度取舍推理 | 检查报告尾部 |
| Step 5 自检 C1-C5 逐项有 PASS/FAIL | 检查 Step 5 输出 |
| 自检 FAIL 时报告头部有警告标记 | 检查最终输出 |
| 报告中不含竞争排名、市场份额、投资建议 | 文本搜索 |
| 进程崩溃后可从 checkpoint 恢复续跑 | 模拟 kill -9 后重跑 |
| Step 1 搜索 < 10 秒 | 计时 |
| 成本/延迟有实测数据更新 | 实际运行后回填第五章 |

---

## 九、版本变更

| 版本 | 核心变化 | 日期 |
|------|----------|------|
| v1 | A2 架构：六步流程 + State 驱动 | 2026-06-04 |
| v2 | 引入 Harness/Environment 分层（9 个组件） | 2026-06-04 |
| v3 | Demo MVP 范围裁剪：完整做 6 项、打桩 5 项、不做 3 项 | 2026-06-05 |
| **v4** | **管线修复：Context Builder 四层、Step 5 失败警告注入、SLICE_MAP 修正、成本/延迟估算** | **2026-06-05** |

---

## 十、参考来源

| 借鉴点 | 来源 | 可信度 |
|---|---|---|
| Independent Evaluator | Anthropic Three-Agent Harness (2026-03) | ★★★★★ |
| Context Builder 分层思想 | Claude Code 18 层 System Prompt (arXiv:2604.14228v1) | ★★★★★ |
| Session Event Log 设计 | Anthropic Managed Agents (2026-05) | ★★★★★ |
| 搜索并行 + 渐进压缩 | Claude Code isConcurrencySafe + Compaction Pipeline | ★★★★★ |
| Circuit Breaker 设计 | Claude Code 错误处理机制 | ★★★★★ |

---

*文档版本：v4.0 | 日期：2026-06-05*
*变更：基于 v3 架构评审结果迭代——修复 Context Builder 缺层、Step 5 失败处置空窗、SLICE_MAP 关键词不匹配、新增成本/延迟估算*
*目标：~760 行 Python，跑一次出高质量报告，自检失败时明确告警*
