# 架构设计 — Agent 架构 v2

> 版本：v2.0 | 日期：2026-06-04 | 给 Trae 的开发 spec
>
> 本版基于 v1 架构（A2：结构化分步单Agent + State驱动），融合了对以下来源的学习：
> - Anthropic Harness Engineering 2026（Managed Agents / Three-Agent Harness / Session Event Log）
> - Claude Code 架构分析 (arXiv:2604.14228v1)
> - OpenClaw Skills 系统 / Lobster 循环
> - Hermes Agent 三层记忆 / 模型分层

---

## 一、总体架构：A2 + Harness/Environment 分层

v2 的核心升级：在 v1 的六步流程之上，引入 **Harness（控制面）** 和 **Environment（执行边界）** 两层基础设施。

```
┌──────────────────────────────────────────────────────────────────┐
│                     Harness（控制面 / 进程内）                       │
│                                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │   Context    │ │   Sprint     │ │   Independent Evaluator   │ │
│  │   Builder    │ │   Contract   │ │   (Step 5, 独立LLM实例)    │ │
│  │ (动态组装)    │ │   Negotiator │ │                           │ │
│  └──────────────┘ └──────────────┘ └───────────────────────────┘ │
│                                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │   Circuit    │ │   Model      │ │   Session Event Log       │ │
│  │   Breaker    │ │   Router     │ │   (JSONL, append-only)     │ │
│  └──────────────┘ └──────────────┘ └───────────────────────────┘ │
│                                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │   Search     │ │   Result     │ │   Checkpoint              │ │
│  │   SubAgent   │ │   Compactor  │ │   Manager                 │ │
│  │   (并行搜索)  │ │   (渐进压缩)  │ │   (崩溃恢复)              │ │
│  └──────────────┘ └──────────────┘ └───────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                   ▼
     ┌──────────┐      ┌──────────┐       ┌──────────┐
     │  Step 1  │      │  Step 2  │  …    │  Step 6  │
     │ 信息收集  │      │ 维度筛选  │       │   输出    │
     │ (搜索并行)│      │+Sprint   │       │          │
     └──────────┘      │ Contract  │       └──────────┘
           │           └──────────┘            │
           └───────────────────────────────────┘
                           │
                           ▼
           ┌───────────────────────────────────┐
           │       Session Event Log            │
           │       (JSONL, append-only)         │
           │                                    │
           │   每步执行 → 追加事件 → 持久化      │
           │   进程崩溃 → 读日志恢复 → 续跑      │
           └───────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│               Minimal Environment（执行边界 / 进程外）              │
│                                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │ Credential   │ │ Output       │ │ Token Usage               │ │
│  │ Vault        │ │ Safety       │ │ Audit                     │ │
│  │ (API密钥管理) │ │ Check        │ │ (成本追踪)                 │ │
│  └──────────────┘ └──────────────┘ └───────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**设计哲学（来源：Anthropic Harness Engineering 2026）** [^1]：

> "模型是引擎，Harness 才是整辆车。" Prompt Engineering 和 Context Engineering 都是"给模型下指令"，Harness Engineering 是"给模型搭舞台"——设计一个让模型持续、稳定、可靠工作的运行时环境。

与 v1 的关键区别：
- v1 只有核心循环（六步流程），没有 Harness 基础设施
- v2 把核心循环包裹在 Harness 层中（Circuit Breaker、Checkpoint、Session Log、Context Builder）
- 新增了 Minimal Environment 层隔离凭证和输出安全

---

## 二、State Schema

### 2.1 StepOutput（每一步的输出）

```python
from pydantic import BaseModel
from typing import Any

class StepOutput(BaseModel):
    """每一步的输出结构，强制包含推理痕迹"""
    step_id: str                        # "1_info_collection", "2_dimension_screening", ...
    step_label: str                     # 人类可读的步骤名，如 "信息收集"
    reasoning: str                      # 元规则：该步的判断推理过程（必须填写）
    confidence: str                     # "high" | "medium" | "low" + 依据简述
    result: dict[str, Any]              # 该步的结构化产出（内容因步骤而异）
    abandoned: list[str] = []           # 放弃的选择 + 为什么放弃
    methodology_ref: str                # 引用了方法论文档的哪一节
```

### 2.2 ReportState（贯穿全流程的状态对象）

```python
class ReportState(BaseModel):
    """贯穿全流程的状态对象"""
    methodology_version: str = "v2"      # 方法论文档版本
    industry_name: str                   # 用户输入
    steps: list[StepOutput] = []         # 每一步的完整记录
    final_report: str | None = None      # 最终报告 markdown
```

### 2.3 StepContext（传给 LLM 的上下文）

```python
class StepContext(BaseModel):
    """传给 LLM 的上下文"""
    system_prompt: str                   # 方法论文档（按步切片）+ 静态身份
    task_prompt: str                     # 当前步骤的具体任务描述
    previous_steps_summary: str          # 前序步骤摘要（不传完整历史）
    current_step_id: str
```

### 2.4 StepBudget（新增：每步的成本和超时约束）

```python
class StepBudget(BaseModel):
    """每步的资源约束"""
    max_tokens: int                      # 该步最大 Token 消耗
    timeout_seconds: int                 # 该步超时时间
    max_retries: int = 2                 # 失败重试次数（Circuit Breaker 触发前）
```

```python
# 预定义各步的预算
STEP_BUDGETS = {
    "1_info_collection":    StepBudget(max_tokens=100000, timeout_seconds=120, max_retries=2),
    "2_dimension_screening": StepBudget(max_tokens=20000,  timeout_seconds=60,  max_retries=2),
    "3_structure_decision":  StepBudget(max_tokens=20000,  timeout_seconds=60,  max_retries=2),
    "4_content_generation": StepBudget(max_tokens=150000, timeout_seconds=180, max_retries=2),
    "5_self_check":         StepBudget(max_tokens=50000,  timeout_seconds=60,  max_retries=2),
}
```

**注意**：当前 v2 仅定义预算上限，不自动拦截超支。Token Budget 的强制执行（实时累计 Token 计数 + 超出时触发降级/截断）规划为 v3 功能。v2 通过 Circuit Breaker 和 timeout 机制提供基础保护。

### 2.5 SprintContract（新增：每步前的"完成"标准协商）

```python
class SprintContract(BaseModel):
    """借鉴 Anthropic Three-Agent Harness：每步执行前协商完成标准"""
    step_id: str
    deliverable: str                    # 本步骤交付物描述
    acceptance_criteria: list[str]      # 验收标准（可 testable 的条件）
    common_failures: list[str]          # 常见失败模式
    verification_method: str            # 验证方式
```

---

## 三、Step Contracts（六步契约）— v2 增强版

### 3.1 总体流程

v2 的每步执行不再是简单的"调 LLM → 存 State"。每步增加了 Sprint Contract 协商：

```
步骤流程（v2）：
1. Sprint Contract 协商（定义"完成"标准）—— 当前为人工审查，v3 计划实现自动化
2. 执行步骤（LLM 调用，带 Circuit Breaker 保护）
3. Session Event Log 追加写入（每步完成后持久化）
4. Checkpoint 到文件（支持崩溃后恢复）
```

### 3.2 Step 1：信息收集

| 字段 | 值 |
|---|---|
| **step_id** | `1_info_collection` |
| **做什么** | 搜索行业相关信息，建立基础知识面 |
| **方法论切片** | R1-R5 (Hard Rules) + 3.2 信息优先级(P0-P3) + 6.参考框架(GICS/NAICS) |
| **需要使用** | Tavily 搜索 API + Search SubAgent 并行执行 |
| **v2 增强** | 3 个搜索 query **并行**执行，结果经**渐进压缩**后注入 LLM |

**输入**：`industry_name`

**输出**（`result` 字段）：
```python
{
    "summary": str,                   # 行业概览（200-300字）
    "official_definitions": list,     # 官方/权威定义（来源+原文）
    "key_regulations": list,          # 关键政策/标准文件（标题+来源+要点）
    "structural_factors": list,       # 结构性影响因素（技术/制度/需求）
    "adjacent_industries": list,      # 相邻行业列表
    "data_gaps": list                 # 搜索后仍不清晰的关键问题
}
```

**Sprint Contract 验收标准**：
- P0 级来源至少找到 1 个
- 搜索覆盖了边界类 query
- 有相邻行业信息

---

### 3.3 Step 2：维度筛选

| 字段 | 值 |
|---|---|
| **step_id** | `2_dimension_screening` |
| **做什么** | 基于 Step 1 的信息，应用方法论 H1-H4 筛选维度 |
| **方法论切片** | 3.1 维度筛选原则(H1-H4) + 5.自检清单 C1-C3 |
| **v2 增强** | Sprint Contract 协商（验收标准前置） |

**输出**（`result` 字段）：不变，与 v1 相同。

**Sprint Contract 验收标准**：
- 选中的维度覆盖 ≥ 2 个独立侧
- 每个维度有明确的经营结果传导
- 放弃的维度有记录

---

### 3.4 Step 3：结构决策

| 字段 | 值 |
|---|---|
| **step_id** | `3_structure_decision` |
| **做什么** | 基于 Step 2 选出的维度，设计报告的具体结构 |
| **方法论切片** | 3.4 报告结构启发式 + 3.3 范围约束 |
| **v2 增强** | Sprint Contract 协商（验收标准前置） |

**输出**（`result` 字段）：不变，与 v1 相同。

**Sprint Contract 验收标准**：
- 每一章对应 Step 2 的至少一个维度
- 没有竞争格局/市场规模/投资建议类章节

---

### 3.5 Step 4：内容生成

| 字段 | 值 |
|---|---|
| **step_id** | `4_content_generation` |
| **做什么** | 按 Step 3 的结构逐章撰写报告正文 |
| **方法论切片** | 全部（R1-R5 + 第四章推理展示要求） |
| **v2 增强** | 使用高质量推理模型（如 Claude Sonnet 4.5）|

**输出**（`result` 字段）：不变，与 v1 相同。

---

### 3.6 Step 5：自检（Evaluator 独立化）

| 字段 | 值 |
|---|---|
| **step_id** | `5_self_check` |
| **做什么** | 对完整报告执行 C1-C5 自检清单 |
| **方法论切片** | 5.自检清单(C1-C5) |
| **v2 核心升级** | **Evaluator 独立化**：Step 5 使用独立的 LLM 调用实例，独立的 system prompt，看不到 Step 1-4 的推理过程。被故意调得"挑剔"。 |

**为什么独立化（来源：Anthropic Three-Agent Harness）** [^1]：

v1 的 Step 5 用的是**同一个 LLM 实例**——模型自己生成报告，然后自己检查。Anthropic 发现了这个模式的系统性问题：模型倾向于对自己生成的内容过度乐观（Self-Evaluation Bias）。

v2 的解决方案：
- Evaluator 是独立 LLM 调用——不同的 system prompt，甚至不同的模型
- Evaluator 只看最终产出，看不到生成过程的 reasoning
- Evaluator 的 system prompt 明确其定位是"挑剔的审查员"，被训练方向为发现而非确认

**输出**（`result` 字段）：不变，与 v1 相同。

**Sprint Contract 验收标准**：
- C1-C5 全部 pass
- 如果 fail_with_fixes → 注入 fixes_required → 回到 Step 4（Evaluator-Optimizer 闭环，最多 3 轮）

---

### 3.7 Step 6：输出

| 字段 | 值 |
|---|---|
| **step_id** | `6_output` |
| **做什么** | 将从 Step 4 的内容 + Step 5 的自检结果 + 方法论附注组装为最终报告 |
| **v2 增强** | 报告中追加 `<fix_log>` 注释区（供后续分析经验积累用） |

**报告模板**：与 v1 相同，尾部增加可选的经验记录注释。

---

## 四、Harness 层组件详解

### 4.1 Session Event Log（借鉴 Anthropic Managed Agents / Claude Code）

**设计来源**：Anthropic 2026 年 Managed Agents 架构中的 Session Event Log 设计 [^1]。核心认知："Session 是账本，Context 是工作区。"

**设计**：
- JSONL 格式，追加写入，不修改
- 事件类型：`step_start`、`llm_call`、`tool_call`、`tool_result`、`step_complete`、`error`、`retry`、`checkpoint`
- 每条记录带时间戳
- 崩溃恢复：读取日志到最后一条完整记录即可重建 State

```python
# frost_agent.py — Session Event Log

import json
from datetime import datetime
from pathlib import Path

class SessionEventLog:
    def __init__(self, industry_name: str):
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self.log_path = self.log_dir / f"{industry_name}_{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    def log(self, event_type: str, data: dict):
        event = {"timestamp": datetime.utcnow().isoformat(), "event_type": event_type, "data": data}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def recover_state(self) -> ReportState | None:
        """从事件日志恢复 ReportState"""
        if not self.log_path.exists():
            return None
        state = ReportState(industry_name="", methodology_version="v2")
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue  # 最后一行可能不完整（崩溃时正在写入），跳过
                if event["event_type"] == "step_complete":
                    state.steps.append(StepOutput.model_validate(event["data"]["output"]))
                if event["event_type"] == "industry_set":
                    state.industry_name = event["data"]["industry_name"]
        return state if state.steps else None
```

### 4.2 Context Builder（借鉴 Anthropic Context Engineering / Claude Code）

**设计来源**：Anthropic Context Builder + Claude Code 的 18 层 System Prompt 组装思想 [^1][^2]。

**设计**：
- 不再简单拼接所有历史，而是按"静态放前、动态放后、摘要级前序步骤"原则组装
- 五层组装结构：
  1. 静态身份 + Hard Rules R1-R5（所有步骤共享，可缓存）
  2. 当前步骤的方法论切片
  3. 任务上下文（行业名称 + 步骤描述）
  4. 前序步骤的结构化摘要（不是完整历史）
  5. 当前步骤最高权重的具体指令（放最后，模型注意力最强）

```python
# context_builder.py

class ContextBuilder:
    MAX_CONTEXT_TOKENS = 30000

    @staticmethod
    def _load_static_identity() -> str:
        """Layer 1：静态身份 + Hard Rules（始终不变，所有步骤共享）"""
        return identity + hard_rules  # 从 methodoogy/ 目录的独立文件加载

    @staticmethod
    def _slice_methodology(step_id: str) -> str:
        """Layer 2：当前步骤的方法论切片"""
        return methodology_loader.load_methodology(step_id)

    @staticmethod
    def _summarize_previous_steps(steps: list[StepOutput], current_step_id: str) -> str:
        """Layer 4：前序步骤摘要（不传完整历史）"""
        summary = "## 前序步骤摘要\n\n"
        for step in steps:
            summary += f"### {step.step_label}\n"
            summary += f"- 关键结论：{step.result.get('summary', step.reasoning[:100])}\n"
            summary += f"- 置信度：{step.confidence}\n\n"
        return summary

    @staticmethod
    def build(step_id: str, state: ReportState) -> str:
        layers = [
            ContextBuilder._load_static_identity(),
            ContextBuilder._slice_methodology(step_id),
            f"行业名称：{state.industry_name}\n\n任务：{STEP_TASKS[step_id]}",
            ContextBuilder._summarize_previous_steps(state.steps, step_id),
            STEP_DIRECTIVES[step_id],  # 最高权重指令放最后
        ]
        return "\n\n---\n\n".join(layers)

    @staticmethod
    def set_fix_instructions(instructions: dict):
        """v2 新增：Evaluator-Optimizer 闭环的回调方法。
        当 Step 5 自检失败时，将修正指示注入上下文，
        供下一轮 Step 4 使用。"""
        # 实现细节：instructions 中的数据会在 build() 的 Layer 3 和 Layer 5 之间
        # 作为一个额外的"修正层"注入
        ContextBuilder._fix_instructions = instructions
```

**注意**：该方法需要配合 `build()` 的实现——当 `_fix_instructions` 不为空时，在 Layer 4 和 Layer 5 之间插入修正层的文本描述。

### 4.3 Circuit Breaker（借鉴 Claude Code）

**设计来源**：Claude Code 的错误处理机制 [^2]。核心思想：**没有 Circuit Breaker 的重试不是重试，是自杀。**

**设计规则**：
- 连续失败 MAX_CONSECUTIVE_FAILURES（默认 3 次）后断路
- 断路后的恢复超时 recovery_timeout（默认 30 秒）
- 适用于每步的 LLM 调用和工具调用

```python
# circuit_breaker.py

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(self, max_failures: int = 3, recovery_timeout: float = 30.0):
        self.max_failures = max_failures
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time: float | None = None

    async def call(self, fn, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - (self.last_failure_time or 0) > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen(f"断路器开启(连续失败{self.max_failures}次), 拒绝请求")

        try:
            result = await fn(*args, **kwargs)
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            return result
        except Exception:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.max_failures:
                self.state = CircuitState.OPEN
            raise
```

### 4.4 Model Router（借鉴 Hermes Agent / Claude Code）

**设计来源**：Hermes Agent 的成本优化路由 [^3] + Claude Code 的 "小工具集效率 > 大工具集" 洞察 [^2]。

**设计**：
- Step 1（搜索总结）用便宜快速模型（信息提取为主）
- Step 2-3（推理决策）用中等模型
- Step 4-5（内容生成+自检）用高质量模型
- 每个模型有 fallback 降级链

```python
# model_router.py

STEP_MODEL_CONFIG = {
    "1_info_collection": {
        "primary": "deepseek-v4-flash",
        "fallback": "deepseek-v4-pro",
    },
    "2_dimension_screening": {
        "primary": "deepseek-v4-pro",
        "fallback": "deepseek-v4",
    },
    "3_structure_decision": {
        "primary": "deepseek-v4-pro",
        "fallback": "deepseek-v4",
    },
    "4_content_generation": {
        "primary": "claude-sonnet-4-5",
        "fallback": "deepseek-v4-pro",
    },
    "5_self_check": {
        "primary": "claude-sonnet-4-5",   # Evaluator 独立模型
        "fallback": "deepseek-v4-pro",
    },
}
```

**预期成本降低**：20-30% [推测，实际效果需 benchmark 验证]。

### 4.5 Independent Evaluator（借鉴 Anthropic Three-Agent Harness）

**设计来源**：Anthropic 2026 年 Three-Agent Harness 文章 [^1]。核心认知：**把"干活"和"挑刺"彻底分开，解决 Self-Evaluation Bias。**

**设计**：
- Step 5 的 Evaluator 是**独立的 LLM 调用实例**
- Evaluator 有独立的 system prompt，定位为"挑剔的审查员"
- Evaluator **看不到** Step 1-4 的 reasoning（只看到最终产出）
- Evaluator 可以使用与 Generator 不同的模型

```python
# evaluator.py

EVALUATOR_SYSTEM_PROMPT = """你是一个严格的行业定义报告审查员。

你的工作是审查报告质量，标准非常严格。
你倾向于发现问题，而不是确认一切正常。
你不对生成过程负责，你只对最终质量负责。

审查维度（C1-C5）：
C1. 区分度测试：如果把行业名称遮掉，读者能否仅从定义本身判断出这是哪个行业？
C2. 废话过滤：定义中是否存在对任何行业都成立的陈述？
C3. 结构性测试：六个月后如果市场数据变了，定义的核心逻辑是否仍然成立？
C4. 边界清晰度：读者读完能否说清楚"什么不是这个行业"？
C5. 推理可见：每个关键判断是否都有"为什么"的解释？

输出格式：每个维度 PASS/FAIL + 具体问题描述 + 可执行的修改建议
"""

class IndependentEvaluator:
    async def evaluate(self, report: str, state: ReportState) -> dict:
        # 注意：不传入 step 1-4 的 reasoning
        eval_context = {
            "industry": state.industry_name,
            "report": report,
        }
        result = await llm_call(
            system=EVALUATOR_SYSTEM_PROMPT,
            user=json.dumps(eval_context, ensure_ascii=False),
            model=STEP_MODEL_CONFIG["5_self_check"]["primary"],
        )
        return result
```

### 4.6 Search SubAgent + 结果渐进压缩（借鉴 Claude Code / OpenClaw）

**设计来源**：
- Claude Code 的 SubAgent 上下文隔离 + `isConcurrencySafe()` 并发机制 [^2]
- Claude Code 的渐进式上下文压缩流水线 [^2]

**设计**：
- 3 个搜索 query **并行**执行（ThreadPoolExecutor，max_workers=3）
- 搜索结果为**只读操作**，标记 `is_concurrency_safe = True`
- 搜索结果经 3 级渐进压缩后注入 LLM 总结

压缩层级（从 cheap 到 expensive）：
1. Budget Reduction：单个结果超过阈值截断
2. Snip：按 P0-P3 优先级丢弃低优先级结果
3. Summarize：LLM 生成结构化摘要（最后手段）

```python
# search_subagent.py

from concurrent.futures import ThreadPoolExecutor, as_completed

SEARCH_QUERIES = [
    "{industry_name} 行业定义 官方定义",
    "{industry_name} 政策 标准文件 监管",
    "{industry_name} 产业链 边界 与相邻行业区分",
]

async def step1_info_collection(state: ReportState, methodology: str) -> StepOutput:
    queries = [q.format(industry_name=state.industry_name) for q in SEARCH_QUERIES]

    # 并行搜索（借鉴 Claude Code 的并发工具执行）
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(search, q): q for q in queries}
        for future in as_completed(futures):
            query = futures[future]
            results[query] = future.result()

    # 渐进压缩结果（借鉴 Claude Code 的 compaction pipeline）
    compactor = ResultCompactor(token_budget=30000)
    compacted = compactor.compact(results)

    # LLM 生成信息总结
    # ...
```

**搜索全失败降级策略**：如果 3 个搜索 query 全部失败（所有 `ThreadPoolExecutor` 任务抛出异常），执行以下降级：
1. 使用行业名称本身作为唯一搜索 query 单次重试
2. 如果仍然失败，将 `data_gaps` 设为 `["所有搜索渠道不可用"]`
3. 将 `confidence` 降低为 `"low:搜索数据不可得"`
4. 在 `reasoning` 中记录降级原因，供后续人工审查

### 4.7 Checkpoint Manager（崩溃恢复）

**设计来源**：Claude Code 的 append-only 存储 [^2] + LangGraph 的 Checkpointer [^4]。

**设计规则**：
- 每步完成后自动追加写入 JSONL
- 启动时自动检测未完成的 checkpoint 并恢复
- 不需要事务管理，不需要状态机回放

```python
def save_checkpoint(state: ReportState, step_id: str):
    checkpoint_path = Path("checkpoints") / f"{state.industry_name}_{step_id}.json"
    checkpoint_path.write_text(state.model_dump_json(indent=2))

def try_resume(industry_name: str) -> ReportState | None:
    """尝试从最近的 checkpoint 恢复"""
    checkpoints = sorted(Path("checkpoints").glob(f"{industry_name}_*.json"))
    if not checkpoints:
        return None
    return ReportState.model_validate_json(checkpoints[-1].read_text())
```

---

## 五、Environment 层设计

行业定义 Agent 不执行系统命令、不操作本地文件系统（除输出目录）、不访问外部网络（除搜索 API 和 LLM API）。因此 Environment 层比 Claude Code 的 Docker Sandbox 设计简单得多。但仍需要以下最小边界：

### 5.1 Credential Vault

```python
# environment.py
import os

class CredentialVault:
    """API 密钥不硬编码，从环境变量或 .env 文件读取"""
    def get(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise CredentialError(f"缺少凭证: {key}")
        return value
```

### 5.2 Output Safety Check

```python
class OutputSafetyCheck:
    """禁止写入到 workspace 外、禁止覆盖已有报告"""
    WORKSPACE = Path("workspace")

    @staticmethod
    def validate(file_path: Path) -> bool:
        abs_path = file_path.resolve()
        if not str(abs_path).startswith(str(OutputSafetyCheck.WORKSPACE.resolve())):
            raise EnvironmentError(f"禁止写入到 workspace 外: {file_path}")
        if abs_path.exists():
            raise EnvironmentError(f"文件已存在，防止覆盖: {file_path}")
        return True
```

### 5.3 Token Usage Audit

```python
class TokenAudit:
    """每次 LLM 调用的 Token 消耗记录，用于成本追踪"""
    def record(self, step_id: str, model: str, input_tokens: int, output_tokens: int):
        # 追加写入 audit log
        ...
```

---

## 六、Orchestrator 逻辑（v2）

```python
# frost_agent.py — v2 骨架

STEPS = [
    ("1_info_collection",       step1_info_collection),
    ("2_dimension_screening",   step2_dimension_screening),
    ("3_structure_decision",    step3_structure_decision),
    ("4_content_generation",    step4_content_generation),
    ("5_self_check",            independent_evaluator),  # v2: 独立 Evaluator
]

MAX_FIX_ATTEMPTS = 3  # Step 5 不通过时的最大修正轮次

async def run(industry_name: str) -> str:
    # 1. 尝试从 checkpoint 恢复（v2 新增）
    state = try_resume(industry_name) or ReportState(
        methodology_version="v2",
        industry_name=industry_name,
    )

    # 2. 初始化 Harness 组件（v2 新增）
    event_log = SessionEventLog(industry_name)
    context_builder = ContextBuilder()
    circuit_breaker = CircuitBreaker(max_failures=3)
    model_router = ModelRouter()
    evaluator = IndependentEvaluator()

    event_log.log("industry_set", {"industry_name": industry_name})

    # 3. 执行 Step 1-3（不变）
    completed_steps = {s.step_id for s in state.steps}
    for step_id, step_fn in [s for s in STEPS if s[0] not in completed_steps][:3]:
        if step_id in completed_steps:
            continue

        event_log.log("step_start", {"step_id": step_id})

        # Sprint Contract 协商（v2 新增，当前为人工审查占位，v3 计划自动化）
        # contract = await negotiate_sprint_contract(step_id, state)  # v3 启用

        # LLM 调用（带 Circuit Breaker 保护，v2 新增）
        result = await circuit_breaker.call(
            execute_step, step_fn, context_builder, state, model_router, step_id
        )

        state.steps.append(result)
        event_log.log("step_complete", {"step_id": step_id, "output": result.model_dump()})
        save_checkpoint(state, step_id)  # v2 新增

    # 4. Step 4 + Step 5 Evaluator-Optimizer 闭环（v2 核心升级）
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        # Step 4: 内容生成
        step4 = await circuit_breaker.call(
            execute_step, step4_content_generation,
            context_builder, state, model_router, "4_content_generation"
        )
        state.steps = [s for s in state.steps if s.step_id != "4_content_generation"]
        state.steps.append(step4)

        # Step 5: 独立 Evaluator（v2 核心升级）
        report_text = _build_report_text(step4)
        eval_result = await evaluator.evaluate(report_text, state)
        step5 = StepOutput(
            step_id="5_self_check",
            step_label="自检",
            reasoning=f"独立Evaluator审查完成, 模型: {eval_result.get('evaluator_model', 'unknown')}",
            confidence=eval_result.get("confidence", "medium"),
            result=eval_result,
            methodology_ref="5.自检清单(C1-C5)",
        )
        state.steps = [s for s in state.steps if s.step_id != "5_self_check"]
        state.steps.append(step5)

        if eval_result.get("overall") == "pass":
            break

        if attempt < MAX_FIX_ATTEMPTS:
            fixes = eval_result.get("fixes_required", [])
            print(f"自检未通过 (第{attempt}轮)，修正项: {fixes}")
            # 将修正指示注入 Context Builder 供下一轮 Step 4 使用
            context_builder.set_fix_instructions({
                "failed_dimensions": eval_result.get("failed_dimensions", []),
                "issues": eval_result.get("issues", []),
                "attempt": attempt + 1,
            })
        else:
            print(f"自检 {MAX_FIX_ATTEMPTS} 轮仍未通过，输出带警告的报告")

    # 5. Step 6: 输出
    final_report = step6_output(state)
    state.final_report = final_report
    event_log.log("task_complete", {"final_report_path": f"reports/{industry_name}.md"})
    return final_report

if __name__ == "__main__":
    import sys
    industry = sys.argv[1] if len(sys.argv) > 1 else "低空经济物流"
    report = asyncio.run(run(industry))
    print(report)
```

---

## 七、项目结构

```
行业定义agent/
├── frost_agent.py              # 主程序（Orchestrator + CLI）
├── models.py                   # State Schema (StepOutput, ReportState, StepContext, StepBudget, SprintContract)
├── methodology_loader.py       # 方法论加载 + 按 step_id 切片
├── requirements.txt            # 依赖
│
├── harness/                    # Harness 层组件（v2 新增）
│   ├── session_log.py          # Session Event Log (JSONL append-only)
│   ├── context_builder.py      # Context Builder (5层组装)
│   ├── circuit_breaker.py      # Circuit Breaker
│   ├── model_router.py         # Model Router (按步骤选模型 + fallback)
│   ├── evaluator.py            # Independent Evaluator (Step 5)
│   ├── search_subagent.py      # Search SubAgent (并行搜索 + 渐进压缩)
│   └── checkpoint.py           # Checkpoint Manager (崩溃恢复)
│
├── environment/                # Environment 层（v2 新增）
│   ├── credential_vault.py     # API 密钥管理
│   ├── output_safety.py        # 输出安全检查
│   └── token_audit.py          # Token 消耗审计
│
├── methodology/                # 方法论（拆分后的模块文件，v2 建议）
│   ├── _meta.yaml              # 版本号、更新时间
│   ├── 01_hard_rules.md        # R1-R5
│   ├── 02_heuristics_dimension.md  # H1-H4
│   ├── 03_info_priority.md     # P0-P3
│   ├── 04_report_scope.md      # 报告范围
│   ├── 05_report_structure.md  # 报告结构
│   ├── 06_reasoning_display.md # 推理展示
│   ├── 07_self_check.md        # C1-C5
│   └── 08_reference_frameworks.md  # 参考框架
│
├── methodology-v2.md           # 原方法论文档（过渡期保留）
│
├── checkpoints/                # Checkpoint 文件（自动生成）
├── logs/                       # Session Event Log（自动生成）
└── reports/                    # 最终报告（自动生成）
```

### 7.1 配置文件规范

使用 `.env` 文件管理所有凭证和模型选择（不提交到 git）：

```bash
# .env（模板，实际值由开发者配置）
TAVILY_API_KEY=your_key_here
LLM_API_KEY_STEP1=your_key_here       # Step 1 搜索总结用
LLM_API_KEY_STEP2_5=your_key_here     # Step 2-5 推理生成用
LLM_MODEL_STEP1=deepseek-v4-flash
LLM_MODEL_STEP2=deepseek-v4-pro
LLM_MODEL_STEP3=deepseek-v4-pro
LLM_MODEL_STEP4=claude-sonnet-4-5
LLM_MODEL_STEP5=claude-sonnet-4-5
```

所有凭证通过 `python-dotenv` 加载，`CredentialVault` 统一读取。

---

## 八、关键设计决策

| 决策 | v1 | v2 | 原因 |
|---|---|---|---|
| **Evaluator** | 同一个 LLM 自检 | 独立 LLM 实例（不同 model/system prompt） | Anthropic Three-Agent Harness 发现 Self-Evaluation Bias [^1] |
| **State 持久化** | 无（只存内存） | Session Event Log (JSONL) + Checkpoint | Claude Code 的 append-only 存储天然支持崩溃恢复 [^2] |
| **上下文组装** | 方法论文档切片 + 完整前序步骤 | 5 层组装（静态缓存 + 动态加权 + 摘要级历史） | Claude Code 18 层 System Prompt 的分层缓存思想 [^2] |
| **错误处理** | 无 | Circuit Breaker + 分类型重试策略 | Claude Code 的错误恢复机制 [^2] |
| **搜索** | 串行 3 轮 | 3 query 并行 + 结果渐进压缩 | Claude Code 的 `isConcurrencySafe()` + Compaction Pipeline [^2] |
| **模型选择** | 单一模型 | Model Router（按步骤选模型） | Hermes 的成本优化路由 [^3] |
| **凭证管理** | 无约束 | Credential Vault（环境变量） | Anthropic Environment Engineering [^1] |

---

## 九、给开发者的 Brief

### 9.1 需要实现的文件

| 文件 | 内容 | 优先级 |
|---|---|---|
| `models.py` | ReportState, StepOutput, StepContext, StepBudget, SprintContract | P0 |
| `methodology_loader.py` | 加载方法论文档 + 按 step_id 切片 | P0 |
| `frost_agent.py` | 主程序（Orchestrator + 六步 + CLI） | P0 |
| `harness/session_log.py` | Session Event Log | P0 |
| `harness/circuit_breaker.py` | Circuit Breaker | P0 |
| `harness/evaluator.py` | Independent Evaluator（Step 5） | P0 |
| `harness/search_subagent.py` | Search SubAgent（并行搜索） | P0 |
| `harness/context_builder.py` | Context Builder（5 层组装） | P1 |
| `harness/model_router.py` | Model Router（按步骤选模型） | P1 |
| `harness/checkpoint.py` | Checkpoint Manager | P1 |
| `environment/*.py` | Credential Vault + Output Safety + Token Audit | P2 |
| `requirements.txt` | pydantic, openai, tavily-python, python-dotenv | P0 |

### 9.2 关键约束（继承 v1 + 新增）

1. **每一步的输出必须包含 `reasoning` 字段**
2. **Confidence 必须标注**（高/中/低 + 一句依据）
3. **Step 5 自检不通过 → Evaluator-Optimizer 闭环**（最多 3 轮自动修正，仍不通过才标记 fixes_required）
4. **搜索至少 3 个 query，并行执行**
5. **方法论文档外部加载**，不硬编码在 prompt 里
6. **v2 新增：所有 LLM 调用必须通过 Circuit Breaker**（连败 3 次断路）
7. **v2 新增：每步完成后自动追加 Session Event Log + Checkpoint**
8. **v2 新增：Evaluator 独立于 Generator**（不同的 LLM 调用实例和 system prompt）

### 9.3 验收标准（继承 v1）

- `python frost_agent.py "低空经济物流"` 能稳定产出报告
- 输出的方法论附注里能看到完整的维度取舍推理
- Step 5 自检能全部 pass（或经 3 轮修正后 pass）
- 报告中不含竞争排名、市场份额、投资建议
- v2 新增：进程崩溃后可从 checkpoint 恢复续跑
- v2 新增：Circuit Breaker 能在连续失败时断路防止成本失控

---

## 附录：参考来源

| 编号 | 来源 | 可信度 | 关键内容 |
|---|---|---|---|
| [^1] | Anthropic "Harness design for long-running application development" + "Scaling Managed Agents" (2026-03 ~ 2026-05) | ★★★★★ | Three-Agent Harness, Brain/Hands 解耦, Session Event Log, Harness/Environment 分层 |
| [^2] | *Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems* (arXiv:2604.14228v1, 2026-04) | ★★★★★ | 渐进式压缩流水线, System Prompt 动态组装, Circuit Breaker, SubAgent 隔离, isConcurrencySafe |
| [^3] | Hermes Agent 官方文档 (Nous Research) | ★★★★☆ | 三层记忆系统, 模型分层路由, GEPA 自我改进 |
| [^4] | LangGraph 官方文档 | ★★★★☆ | StateGraph, Checkpointer, Human-in-the-Loop |

---

*文档版本：v2.0 | 日期：2026-06-04*
*变更：在 v1 基础上引入 Harness/Environment 分层、Session Event Log、Circuit Breaker、Independent Evaluator、Model Router、Search SubAgent、渐进压缩*
