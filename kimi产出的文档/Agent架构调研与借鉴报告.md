# Agent架构调研与借鉴报告

> 目标：从2025-2026年最先进的Agent产品中学什么、用什么
> 调研范围：Claude Code、OpenClaw、Hermes Agent、LangGraph
> 适用项目：行业定义Agent（A2架构）
> 日期：2026-06-04

---

## 一、为什么做这份调研

不是评估A2架构好不好，而是回答一个问题：**市面上最厉害的Agent产品，有哪些设计是我可以直接抄作业的？**

调研方法：
- 源码级分析：Claude Code（arXiv论文+反向工程）、OpenClaw（官方文档）、Hermes（GitHub+官方文档）
- 重点不是"他们有什么功能"，而是"他们的工程架构有什么巧妙之处可以为我所用"
- 每条借鉴都附带"能不能用"判断和"怎么用"的具体方案

---

## 二、Claude Code —— 最值得学的工程课

Claude Code是Anthropic的官方CLI Agent，~512,000行TypeScript源码，服务数十万并发用户。它的架构论文（arXiv:2604.14228v1）是Agent工程领域最权威的源码级分析之一。

### 借鉴点1：渐进式上下文压缩流水线（5-Layer Compaction Pipeline）

**Claude Code的设计**：

每次调用模型前，上下文按5个层次依次压缩（从 cheapest 到 most expensive）：

```
Budget Reduction（始终执行）
  → 单个工具结果超过大小限制时截断/替换为引用

Snip（HISTORY_SNIP开关）
  → 轻量级裁剪老旧历史段落

Microcompact（始终执行）
  → 细粒度压缩，缓存感知（优先保留命中缓存的内容）

Context Collapse（CONTEXT_COLLAPSE开关）
  → 读时虚拟投影，不修改原始历史

Auto-Compact（默认开启）
  → LLM生成完整摘要，最后手段
```

**核心思想**：不要一上来就暴力截断，而是**从 least disruptive 到 most aggressive 逐级尝试**，每级只在更便宜的策略不够时才触发。

**对我的项目有没有用？**

有。行业定义Agent的Step 1（信息收集）可能返回大量搜索结果，Step 4（内容生成）可能产生很长的报告。如果不加控制，上下文会膨胀。

**具体怎么抄**：

不需要5层，2-3层就够了。给Step 1的搜索结果设计一个简单的分级压缩：

```python
# compaction.py — 借鉴Claude Code的渐进式思想

class SearchResultCompactor:
    """对Step 1的搜索结果进行渐进式压缩"""
    
    def __init__(self, token_budget: int = 30000):
        self.token_budget = token_budget
    
    def compact(self, search_results: list[dict]) -> list[dict]:
        """三级渐进压缩：budget → snip → summarize"""
        
        # Level 1: Budget Reduction（截断过长个体）
        results = self._budget_reduce(search_results)
        if self._estimate_tokens(results) < self.token_budget:
            return results
        
        # Level 2: Snip（丢弃低优先级结果）
        results = self._snip_low_priority(results)
        if self._estimate_tokens(results) < self.token_budget:
            return results
        
        # Level 3: Summarize（LLM压缩摘要）
        results = self._summarize_batch(results)
        return results
    
    def _budget_reduce(self, results: list[dict]) -> list[dict]:
        """单个结果超过1000字截断"""
        for r in results:
            if len(r.get("content", "")) > 1000:
                r["content"] = r["content"][:1000] + "... [截断]"
        return results
    
    def _snip_low_priority(self, results: list[dict]) -> list[dict]:
        """按P0-P3优先级丢弃，保P0丢P3"""
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        results.sort(key=lambda x: priority_order.get(x.get("priority", "P3"), 3))
        
        kept = []
        tokens = 0
        for r in results:
            t = len(r.get("content", "")) // 4  # 粗略估token
            if tokens + t < self.token_budget * 0.8:
                kept.append(r)
                tokens += t
            else:
                break
        return kept
    
    def _summarize_batch(self, results: list[dict]) -> list[dict]:
        """最后用LLM做摘要（借鉴auto-compact思想）"""
        # TODO: 调用LLM将剩余结果压缩为结构化摘要
        pass
```

**抄作业要点**：不是抄5层，是抄"**先便宜后贵、逐级递进**"的思想。

---

### 借鉴点2：System Prompt的18层严格组装

**Claude Code的设计**：

System Prompt由18个section按严格顺序拼接：
- 前12层是**静态可缓存的**（身份定义、工具模式、安全策略等）
- 后6层是**每会话变化的**（环境信息、CLAUDE.md、记忆等）
- 两层之间有一个明确的边界标记 `══ __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ ══`

**核心思想**：**顺序不是任意的**。LLM对prompt开头和结尾注意力最强，所以把最重要的身份定义放开头，把用户项目指令（CLAUDE.md）放结尾——那里权重最高。

**对我的项目有没有用？**

非常有用。当前A2架构的方法是"按step_id切片注入"，但没有考虑注入顺序对模型注意力的影响。

**具体怎么抄**：

重新设计System Prompt的组装顺序，把最重要的方法论规则放在开头，当前步骤的具体任务放在结尾：

```python
# prompt_assembler.py — 借鉴Claude Code的分层组装

class SystemPromptAssembler:
    """
    借鉴Claude Code的18层思想，为行业定义Agent设计5层组装：
    
    第1层（静态，所有步骤共享）：身份 + Hard Rules R1-R5
    第2层（静态，步骤相关）：当前步骤的方法论切片
    第3层（动态，任务相关）：行业名称 + 当前任务描述
    第4层（动态，上下文）：前序步骤的摘要（非完整历史）
    第5层（动态，最高权重）：当前步骤的具体指令
    """
    
    def assemble(self, step_id: str, state: ReportState, methodology: str) -> str:
        layers = []
        
        # Layer 1: 静态身份+Hard Rules（始终不变，可缓存）
        layers.append(self._load_static_identity())
        layers.append(self._load_hard_rules())
        
        # Layer 2: 当前步骤的方法论切片
        layers.append(self._slice_methodology(methodology, step_id))
        
        # Layer 3: 任务上下文
        layers.append(f"行业名称：{state.industry_name}")
        layers.append(self._get_step_task_description(step_id))
        
        # Layer 4: 前序步骤摘要（借鉴Claude Code的summary-only return）
        if state.steps:
            layers.append(self._summarize_previous_steps(state.steps))
        
        # Layer 5: 当前步骤最高权重指令（放最后，模型最关注）
        layers.append(self._get_step_directive(step_id))
        
        return "\n\n---\n\n".join(layers)
```

**抄作业要点**：不是抄18层，是抄"**静态放前缓存、动态放后加权、顺序决定注意力**"的思想。

---

### 借鉴点3：子Agent隔离 + 摘要返回（Context Isolation via Subagents）

**Claude Code的设计**：

当主Agent需要执行复杂子任务时，spawn一个子Agent：
- 子Agent获得**隔离的上下文窗口**（独立的200K/1M token空间）
- 子Agent可以执行自己的工具调用、推理、多步操作
- 子Agent完成后，**只返回摘要**给父Agent——中间过程不污染父上下文
- 子Agent有多种类型：Explore（探索）、Plan（规划）、通用

**核心思想**：**委派不是函数调用，是上下文隔离**。子Agent的所有工作都在自己的沙箱里，父Agent只看到结果。

**对我的项目有没有用？**

极其有用。A2架构的Step 1（信息收集）需要3-5轮搜索，每轮搜索都是独立的，可以并行。而且未来升级到多Agent时，这个模式是天然的基础。

**具体怎么抄**：

Step 1的搜索可以改造成"Search SubAgent"模式：

```python
# search_subagent.py — 借鉴Claude Code的subagent隔离思想

import asyncio

class SearchSubAgent:
    """
    每个搜索query spawn一个独立的搜索子任务：
    - 独立的LLM调用上下文
    - 只返回结构化摘要
    - 多个query可并行执行
    """
    
    async def search_parallel(
        self,
        queries: list[str],
        industry_name: str,
        methodology_slice: str,
    ) -> list[SearchResult]:
        """并行执行多个搜索子任务"""
        
        tasks = [
            self._single_search_subagent(q, industry_name, methodology_slice)
            for q in queries
        ]
        
        # 并行执行，每个子任务独立上下文
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果（只保留成功的）
        merged = []
        for r in results:
            if isinstance(r, Exception):
                print(f"⚠️  搜索子任务失败: {r}")
                continue
            merged.extend(r)
        
        return merged
    
    async def _single_search_subagent(
        self,
        query: str,
        industry_name: str,
        methodology_slice: str,
    ) -> list[SearchResult]:
        """
        单个搜索子Agent：
        - 独立上下文（只包含本query相关信息）
        - 执行搜索 + LLM提取
        - 返回结构化结果（中间过程丢弃）
        """
        # 1. 执行搜索
        raw_results = await self.search_tool(query)
        
        # 2. LLM提取关键信息（独立上下文，不受其他query干扰）
        extracted = await self.llm_extract(
            query=query,
            raw_results=raw_results,
            industry=industry_name,
            methodology=methodology_slice,
        )
        
        # 3. 只返回结构化摘要（中间搜索过程不暴露给父Agent）
        return [SearchResult(
            query=query,
            key_findings=extracted.key_findings,
            sources=extracted.sources,
            confidence=extracted.confidence,
        )]
```

**立即收益**：Step 1的延迟从"串行3-5轮搜索"降到"并行3-5轮同时搜"。

**未来收益**：当需要升级多Agent时，只需把某个step的调用换成独立Agent，State Schema和Contracts不变——这正是A2架构预留的扩展路径。

---

### 借鉴点4：Append-Only存储 + 崩溃恢复

**Claude Code的设计**：

- 会话数据采用**追加写入**（append-only）的Markdown文件存储
- 从不修改或删除已写入的内容，只追加新的边界标记和摘要事件
- 配合5层compaction pipeline，实现崩溃后的**状态重建**

**核心思想**：**存储设计决定了恢复能力**。Append-only让崩溃恢复变得简单——不需要事务日志，不需要状态机回放，只需要读文件到崩溃前的最后一条记录。

**对我的项目有没有用？**

非常有用。A2架构目前State全在内存中，进程崩溃后一切重来。改成append-only的JSONL存储，可以实现Checkpoint。

**具体怎么抄**：

```python
# checkpoint.py — 借鉴Claude Code的append-only思想

import json
import os
from datetime import datetime

class AppendOnlyCheckpoint:
    """
    借鉴Claude Code的append-only设计：
    - 每步完成后追加写入JSONL
    - 崩溃后读取到最后一条完整记录即可恢复
    - 不需要事务管理，不需要状态机回放
    """
    
    def __init__(self, industry_name: str):
        self.file_path = f"checkpoints/{industry_name}.jsonl"
        os.makedirs("checkpoints", exist_ok=True)
    
    def save_step(self, step_output: StepOutput):
        """追加写入一步的结果"""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "step_id": step_output.step_id,
            "data": step_output.model_dump(),
        }
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def recover(self) -> ReportState | None:
        """
        崩溃恢复：读取所有完整记录，重建State。
        如果最后一条记录损坏（写入中途崩溃），自动丢弃。
        """
        if not os.path.exists(self.file_path):
            return None
        
        state = ReportState()
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    step = StepOutput.model_validate(record["data"])
                    state.steps.append(step)
                except (json.JSONDecodeError, KeyError):
                    # 最后一条可能不完整（崩溃时正在写入），跳过
                    print(f"⚠️  跳过损坏的记录: {line[:50]}...")
                    continue
        
        return state if state.steps else None
    
    def finalize(self, final_report: str):
        """最终报告生成后，追加标记完成"""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": "finalized",
            "final_report_path": f"reports/{self.industry_name}.md",
        }
        with open(self.file_path, "a") as f:
            f.write(json.dumps(record) + "\n")
```

**抄作业要点**：不是抄Markdown格式，是抄"**append-only = 天然崩溃恢复**"的设计哲学。

---

### 借鉴点5：Circuit Breaker（断路器）+ 错误恢复

**Claude Code的设计**：

每个重试循环都内置circuit breaker：
- `MAX_CONSECUTIVE_FAILURES = 3`
- 连续失败3次后停止重试，防止静默失败导致成本失控
- 多层恢复机制：max output token escalation → reactive compaction → prompt-too-long handling → streaming fallback → fallback model

**核心思想**：**没有circuit breaker的重试不是重试，是自杀**。LLM调用可能因各种原因连续失败，如果没有上限，一个简单的bug就能烧掉大量API费用。

**对我的项目有没有用？**

必须抄。当前A2架构没有任何错误处理，这是一个生产级系统的底线要求。

**具体怎么抄**：

```python
# resilient_llm.py — 借鉴Claude Code的circuit breaker思想

import asyncio
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"      # 正常
    OPEN = "open"          # 断路，拒绝请求
    HALF_OPEN = "half_open"  # 试探恢复

class CircuitBreaker:
    """
    借鉴Claude Code：连续失败3次后断路，防止成本失控
    """
    
    def __init__(self, max_failures: int = 3, recovery_timeout: float = 30.0):
        self.max_failures = max_failures
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
    
    async def call(self, fn, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen("断路器开启，暂时拒绝请求")
        
        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        if self.failure_count >= self.max_failures:
            self.state = CircuitState.OPEN
            print(f"🔴 Circuit Breaker OPEN: 连续失败{self.max_failures}次")
    
    def _should_attempt_reset(self):
        elapsed = asyncio.get_event_loop().time() - self.last_failure_time
        return elapsed > self.recovery_timeout


# 在LLM调用中使用
breaker = CircuitBreaker(max_failures=3)

async def safe_llm_call(system_prompt: str, user_prompt: str):
    return await breaker.call(
        actual_llm_call,
        system_prompt,
        user_prompt,
        timeout=60,  # 同时加超时
        max_tokens=50000,  # 同时加token上限
    )
```

---

### 借鉴点6：工具并发安全声明（`isConcurrencySafe()`）

**Claude Code的设计**：

每个工具声明自己是否支持并发执行：
- 只读操作（如Read、Grep）标记为 `isConcurrencySafe = true`
- 写操作（如Edit、Bash）标记为 `isConcurrencySafe = false`
- StreamingToolExecutor根据标记决定并行还是串行

**核心思想**：**让工具自己声明安全属性，而不是调度器猜测**。

**对我的项目有没有用？**

有。Step 1的多个搜索query是只读的，天然可以并行。

**具体怎么抄**：

```python
# tools.py

class Tool:
    def __init__(self, name: str, is_concurrency_safe: bool = False):
        self.name = name
        self.is_concurrency_safe = is_concurrency_safe

SEARCH_TOOL = Tool("tavily_search", is_concurrency_safe=True)  # 只读，可并行
EDIT_TOOL = Tool("file_edit", is_concurrency_safe=False)        # 写操作，串行
```

---

## 三、OpenClaw —— 最值得学的文件系统设计

OpenClaw是Peter Steinberger创建的开源Agent，~250K GitHub Stars。它的核心哲学是：**文件就是一切，没有数据库，没有黑箱**。

### 借鉴点7：纯Markdown存储 + Git版本控制

**OpenClaw的设计**：

所有记忆、会话、配置都是纯文本文件：
```
~/clawd/
├── SOUL.md              # Agent人格定义
├── AGENTS.md            # Agent配置
├── MEMORY.md            # 长期记忆（精心整理的）
├── memory/
│   └── 2026-06-04.md    # 每日日志（自动的）
├── TOOLS.md             # 工具文档
└── SKILLS.md            # Skill索引
```

- MEMORY.md是**人工 curated**的——Agent不会自动写入，只在用户说"记住这个"时才写
- memory/YYYY-MM-DD.md是**自动的**——每日会话日志
- 所有修改**自动commit到Git**——完整审计链

**核心思想**：**可审计性 > 便利性**。用户可以打开任何文件查看Agent看到了什么、记住了什么。

**对我的项目有没有用？**

非常有用。行业定义Agent产出的行业定义报告需要可审计、可追踪。而且中间产物（每步的输出）本身就是很好的审计材料。

**具体怎么抄**：

```
workspace/
├── methodology.md           # 方法论（对应SOUL.md）
├── checkpoints/
│   └── {industry_name}.jsonl   # 执行日志（append-only，借鉴Claude Code）
├── reports/
│   └── {industry_name}.md      # 最终报告
└── memory/                  # 行业知识积累（借鉴OpenClaw的长期记忆）
    └── 行业分类/
        └── {industry_category}.md   # 同类行业的共性知识
```

**关键设计**：每步的StepOutput不仅写入State，还同时追加到checkpoints的JSONL文件中。最终报告+方法论附注=完整的审计链。

---

### 借鉴点8：Lobster循环（Think→Act→Observe→Reflect）

**OpenClaw的设计**：

Agent循环不是简单的ReAct，而是增加了Reflect阶段：
```
Think（思考）→ Act（行动）→ Observe（观察结果）→ Reflect（反思）
```

Reflect阶段是元认知——Agent回顾刚才的思考过程，评估是否正确、是否需要调整。

**核心思想**：**行动后不反思 = 没有学习**。Reflect是Agent从"执行者"变成"思考者"的关键。

**对我的项目有没有用？**

A2架构已经在做这件事了！Step 5（自检）就是Reflect。但可以做得更系统：

**具体怎么抄**：

把Reflect从"流程末尾的一步"变成"每步之后的微型反思"：

```python
# 当前A2：Reflect只在最后一步
Step 1 → Step 2 → Step 3 → Step 4 → Step 5(Reflect)

# 改进版：每步后加微型Reflect
Step 1 → Reflect → Step 2 → Reflect → Step 3 → Reflect → ...
```

```python
async def run_step_with_mini_reflect(
    step_fn, state, methodology
) -> StepOutput:
    """
    借鉴OpenClaw的Lobster循环：
    每步执行后加一个微型反思：
    - 这步的输出质量如何？
    - confidence是否低于阈值？
    - 是否需要补充信息？
    """
    # 执行步骤
    result = await step_fn(state, methodology)
    
    # 微型反思（借鉴Lobster的Reflect）
    if result.confidence.startswith("low"):
        reflect_prompt = f"""
        上一步 {result.step_id} 的置信度为低。
        推理过程：{result.reasoning}
        
        请反思：
        1. 为什么置信度低？
        2. 是否需要补充搜索/信息？
        3. 是否可以在当前步骤内修正？
        """
        reflect_result = await llm_call(reflect_prompt)
        result.reasoning += f"\n\n[Reflect]: {reflect_result}"
    
    return result
```

---

### 借鉴点9：Workspace引导文件（Bootstrap Files）

**OpenClaw的设计**：

会话启动时，Agent读取一系列引导文件来了解自己的工作环境：
- SOUL.md：我是谁、我的性格、我的能力
- AGENTS.md：我有哪些Agent可以委派
- TOOLS.md：我有哪些工具
- USER.md：用户的偏好
- MEMORY.md：我需要记住什么

**核心思想**：**Agent的环境认知来自文件，不是来自prompt硬编码**。这样用户可以编辑文件来改变Agent行为，不需要改代码。

**对我的项目有没有用？**

极其有用。当前A2架构的方法论是外部Markdown，但只做到了"加载"。可以扩展成"引导文件系统"：

```
workspace/
├── frost_agent.py           # 代码
├── models.py                # Schema
├── methodology.md           # 方法论（核心规则）
├── methodology_v2.md        # 方法论v2（版本演进）
├── heuristics.md            # 启发式规则（H1-H4的详细解释+示例）
├── checklist.md             # 自检清单（C1-C5的检查细则）
├── examples/                # 优秀案例库
│   ├── 低空经济.md
│   └── 新能源汽车.md
└── output_templates/        # 输出模板
    └── 行业定义报告模板.md
```

Agent启动时读取所有这些文件来构建完整的"环境认知"。

---

## 四、Hermes Agent —— 最值得学的记忆系统

Hermes Agent是Nous Research的开源Agent，~143K Stars。核心哲学：**Agent会成长——用越久越聪明**。

### 借鉴点10：三层记忆系统（Session + Persistent + Skill）

**Hermes的设计**：

| 层级 | 存储 | 内容 | 生命周期 |
|---|---|---|---|
| **Session Memory** | 内存 | 当前会话的上下文 | 会话结束清空 |
| **Persistent Memory** | SQLite FTS5 | 跨会话的事实、偏好、历史 | 永久 |
| **Skill Memory** | Markdown文件 | 可复用的程序化知识 | 永久，Agent自主更新 |

**核心思想**：**不是所有记忆都平等**。短期上下文（Session）用于当前任务，长期事实（Persistent）用于跨任务回忆，程序化知识（Skill）用于能力复用。

**对我的项目有没有用？**

极其有用。行业定义Agent目前只有Session Memory（State在内存中）。Persistent Memory可以让Agent记住之前分析过的行业，遇到相似行业时复用知识。

**具体怎么抄**：

```python
# memory_system.py — 借鉴Hermes的三层记忆

import sqlite3
from dataclasses import dataclass

@dataclass
class IndustryMemory:
    """借鉴Hermes的Persistent Memory：行业知识积累"""
    industry_name: str
    category: str           # 行业分类
    key_dimensions: list    # 该行业使用的分析维度
    data_sources: list      # 找到的有效数据源
    lessons_learned: str    # 这次分析的经验教训
    confidence_patterns: dict  # 哪些维度通常高/低置信度

class PersistentMemory:
    """
    借鉴Hermes的SQLite FTS5：
    - 每次行业分析完成后，提取关键知识存入
    - 下次遇到同类行业时，先搜索历史经验
    """
    
    def __init__(self, db_path: str = "workspace/industry_memory.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()
    
    def save_analysis(self, state: ReportState):
        """行业分析完成后，提取知识存入长期记忆"""
        memory = self._extract_memory(state)
        self.conn.execute(
            "INSERT INTO industry_memories VALUES (?, ?, ?, ?, ?, ?)",
            (memory.industry_name, memory.category,
             json.dumps(memory.key_dimensions),
             json.dumps(memory.data_sources),
             memory.lessons_learned,
             json.dumps(memory.confidence_patterns))
        )
        self.conn.commit()
    
    def find_similar(self, industry_name: str) -> list[IndustryMemory]:
        """
        借鉴Hermes的FTS5搜索：
        新行业分析前，搜索历史上相似的行业，
        复用之前找到的有效维度、数据源
        """
        cursor = self.conn.execute(
            "SELECT * FROM industry_memories WHERE industry_name MATCH ?",
            (industry_name,)
        )
        return [self._parse_row(r) for r in cursor.fetchall()]
```

**立即收益**：Step 1搜索前，先查历史记忆——"之前分析低空经济时找到了XX数据源、用了XX维度"，直接复用。

**长期收益**：积累100个行业的分析经验后，Agent的分析质量会系统性提升。

---

### 借鉴点11：Periodic Nudge（定期自省）

**Hermes的设计**：

在会话中定期触发一个"自省"prompt：
- Agent扫描最近的活动
- 评估是否有值得长期记忆的内容
- 如果有，写入MEMORY.md
- **只在内容值得记住时才写**，防止记忆膨胀

**核心思想**：**记忆不是自动的，是选择性持久化**。垃圾信息不应该进长期记忆。

**对我的项目有没有用？**

有。可以在每步完成后加一个微型判断："这步的输出是否有值得长期记忆的内容？"

**具体怎么抄**：

```python
async def maybe_persist_lessons(step_output: StepOutput, memory: PersistentMemory):
    """
    借鉴Hermes的Periodic Nudge：
    每步完成后判断是否有值得记忆的经验
    """
    if step_output.confidence.startswith("low"):
        # 低置信度通常意味着发现了新的经验
        nudge_prompt = f"""
        步骤 {step_output.step_id} 产生了低置信度输出。
        
        是否有以下类型的经验教训值得长期保存？
        - 发现了新的有效数据源？
        - 某个维度在这个行业特别难分析？
        - 方法论在这个场景下需要调整？
        
        如果有，输出1-3条经验。如果没有，输出"无"。
        """
        lessons = await llm_call(nudge_prompt)
        if lessons.strip() != "无":
            memory.save_lessons(step_output.step_id, lessons)
```

---

### 借鉴点12：不同步骤用不同模型（Cost-Optimized Routing）

**Hermes的设计**：

- 简单任务用便宜模型（如Haiku/Flash）
- 复杂推理用高级模型（如Opus/Pro）
- 支持fallback_model：高级模型不可用时自动降级

**核心思想**：**不是所有步骤都需要最强模型**。搜索提取用便宜模型就够了，内容生成才需要高级模型。

**对我的项目有没有用？**

非常有用。成本是生产级系统的核心约束。

**具体怎么抄**：

```python
# model_router.py — 借鉴Hermes的成本优化路由

STEP_MODEL_CONFIG = {
    "1_info_collection": {
        "primary": "deepseek-v4-flash",    # 便宜快速，信息提取
        "fallback": "deepseek-v4-pro",
        "timeout": 60,
    },
    "2_dimension_screening": {
        "primary": "deepseek-v4-pro",      # 需要推理
        "fallback": "deepseek-v4",
        "timeout": 45,
    },
    "3_structure_decision": {
        "primary": "deepseek-v4-pro",
        "fallback": "deepseek-v4",
        "timeout": 45,
    },
    "4_content_generation": {
        "primary": "claude-sonnet-4-5",     # 高质量长文本
        "fallback": "deepseek-v4-pro",
        "timeout": 180,
    },
    "5_self_check": {
        "primary": "claude-sonnet-4-5",     # 需要准确判断
        "fallback": "deepseek-v4-pro",
        "timeout": 60,
    },
}

class ModelRouter:
    """按步骤选择模型，失败自动降级"""
    
    async def call(self, step_id: str, system: str, user: str):
        config = STEP_MODEL_CONFIG[step_id]
        
        try:
            return await self._call_model(config["primary"], system, user, config["timeout"])
        except Exception:
            print(f"⚠️  {config['primary']} 失败，降级到 {config['fallback']}")
            return await self._call_model(config["fallback"], system, user, config["timeout"])
```

**预期成本降低**：30-50%（搜索步骤用便宜模型占大头）

---

## 五、LangGraph —— 最值得学的状态机设计

LangGraph是LangChain团队的Agent编排框架，核心抽象是StateGraph。

### 借鉴点13：StateGraph + Checkpointer = 生产级状态管理

**LangGraph的设计**：

```python
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import InMemorySaver

# 定义State Schema
class AgentState(TypedDict):
    messages: list
    industry: str
    steps_completed: list

# 构建图
builder = StateGraph(AgentState)
builder.add_node("step1", step1_node)
builder.add_node("step2", step2_node)
builder.add_edge("step1", "step2")

# 编译时注入Checkpointer = 自动持久化
checkpointer = InMemorySaver()  # 或 PostgresSaver
graph = builder.compile(checkpointer=checkpointer)

# 每次invoke自动checkpoint
graph.invoke(state, config={"thread_id": "unique-id"})

# 崩溃后恢复：相同thread_id自动从checkpoint恢复
graph.invoke(None, config={"thread_id": "unique-id"})  # 从断点继续
```

**核心思想**：**State + Checkpointer是基础设施，不是业务逻辑**。开发者只需要定义State Schema和节点函数，持久化/恢复是框架自动处理的。

**对我的项目有没有用？**

极其有用。A2架构的State设计（ReportState + StepOutput）与LangGraph的StateGraph天然同构。如果未来考虑使用LangGraph作为编排框架，可以无缝迁移。

**具体怎么抄（两个选择）**：

**选择A：不引入LangGraph，借鉴其设计思想自己实现**

```python
# checkpoint.py — 借鉴LangGraph的Checkpointer思想

class Checkpointer:
    """
    借鉴LangGraph：自动在每一步后保存State
    开发者不需要手动调用save，框架自动处理
    """
    
    def __init__(self, backend: str = "jsonl"):
        self.backend = backend
        self.storage = {}
    
    def wrap_step(self, step_fn):
        """装饰器：自动在步骤前后读写checkpoint"""
        async def wrapped(state: ReportState, *args, **kwargs):
            thread_id = f"{state.industry_name}_{state.methodology_version}"
            
            # 1. 读取checkpoint（如果存在）
            checkpoint = self._load(thread_id)
            if checkpoint and checkpoint.step_id == step_fn.__name__:
                print(f"📋 从checkpoint恢复: {checkpoint.step_id}")
                state = checkpoint.state
            
            # 2. 执行步骤
            result = await step_fn(state, *args, **kwargs)
            
            # 3. 自动保存checkpoint
            self._save(thread_id, {
                "step_id": step_fn.__name__,
                "state": state,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            return result
        
        return wrapped
```

**选择B：引入LangGraph**

如果未来需要更复杂的编排（条件分支、Human-in-the-Loop、子图），可以考虑用LangGraph重构：

```python
# 用LangGraph重写A2架构（未来选项）
from langgraph.graph import StateGraph
from typing import Annotated
from operator import add

class ReportState(TypedDict):
    industry_name: str
    steps: Annotated[list, add]  # reducer：自动追加
    final_report: str | None

builder = StateGraph(ReportState)
builder.add_node("info_collection", step1_node)
builder.add_node("dimension_screening", step2_node)
# ...

# Human-in-the-Loop：Step 5自检失败时暂停等待人工
builder.compile(
    checkpointer=PostgresSaver(),
    interrupt_after=["self_check"],  # Step 5后暂停
)
```

**建议**：Demo阶段用选择A（自己实现，轻量），生产阶段评估选择B（LangGraph，功能完善）。

---

### 借鉴点14：Human-in-the-Loop（人在回路）

**LangGraph的设计**：

在图的特定节点前后插入中断点，暂停执行等待人工输入：

```python
graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["high_risk_step"],  # 高风险步骤前暂停
    interrupt_after=["review_step"],      # 审查步骤后暂停
)

# 人工审查后可以修改state
graph.update_state(thread_id, new_state)

# 然后恢复执行
graph.invoke(None, config={"thread_id": thread_id})
```

**核心思想**：**不是所有决策都应该交给Agent**。高价值/高风险的操作需要人工确认。

**对我的项目有没有用？**

有用。Step 5自检失败后，可以暂停等待人工审查，而不是自动继续或终止。

**具体怎么抄**：

```python
# hitl.py — Human-in-the-Loop 借鉴LangGraph

class HITLController:
    """
    借鉴LangGraph的interrupt机制：
    在关键节点暂停，等待人工输入
    """
    
    async def maybe_pause_for_review(
        self, step_output: StepOutput, state: ReportState
    ) -> StepOutput:
        """
        在Step 5自检失败后暂停，等待人工审查
        """
        if step_output.step_id == "5_self_check" and \
           step_output.result.get("overall") == "fail_with_fixes":
            
            print("\n" + "="*60)
            print("⏸️  Human-in-the-Loop 暂停")
            print(f"行业：{state.industry_name}")
            print(f"自检未通过项：{step_output.result.get('fixes_required', [])}")
            print("\n选项：")
            print("  [1] 继续自动修正")
            print("  [2] 人工修改后恢复")
            print("  [3] 强制输出当前报告")
            
            choice = input("\n请选择 (1/2/3): ").strip()
            
            if choice == "2":
                # 保存checkpoint，等待人工修改
                self._save_for_human_edit(state)
                print(f"💾 State已保存到 checkpoints/{state.industry_name}_human_edit.json")
                print("请修改后重新运行脚本")
                raise SystemExit(0)
            elif choice == "3":
                # 强制输出
                step_output.result["overall"] = "force_output"
        
        return step_output
```

---

## 六、其他值得借鉴的设计模式

### 借鉴点15：Prompt Caching对齐（来自Claude Code的工程优化）

**Claude Code的设计**：

System Prompt的前12层是静态的， Anthropic的API会缓存这部分。Claude Code精心设计了注入顺序，让静态部分前缀完全相同，最大化缓存命中率。

**核心思想**：**上下文组装不仅是功能问题，也是成本问题**。API调用的成本中，cached tokens比uncached tokens便宜得多。

**对我的项目有没有用？**

有。如果使用的LLM API支持prompt caching（如Anthropic、部分OpenAI模型），可以通过固定System Prompt的前半部分来降低40-80%的成本。

**具体怎么抄**：

```python
# caching_optimizer.py

class PromptCacheOptimizer:
    """
    借鉴Claude Code：确保静态部分前缀完全相同，最大化缓存命中
    """
    
    def build_prompt(self, step_id: str, state: ReportState) -> tuple[str, str]:
        """
        返回 (cached_part, uncached_part)
        cached_part: 静态身份+Hard Rules（所有调用完全相同）
        uncached_part: 动态的任务描述+上下文
        """
        cached = self._static_identity + self._hard_rules  # 永远不变
        uncached = self._build_dynamic_part(step_id, state)  # 每步变化
        
        return cached, uncached
```

---

### 借鉴点16：工具Schema的懒加载（Lazy Loading）

**Claude Code的设计**：

工具描述不是一次性全部塞进prompt，而是**按需加载**。当前步骤不需要的工具不注入描述，减少上下文消耗。

**核心思想**：**上下文是有限的，不要浪费在不相关的东西上**。

**对我的项目有没有用？**

有。A2架构只有搜索工具，但如果未来增加更多工具（如数据可视化、报告格式化），应该只在需要时才加载工具描述。

---

### 借鉴点17：StreamingToolExecutor（流式工具执行）

**Claude Code的设计**：

模型还在生成响应时，就开始执行工具调用（不用等响应完成）。多工具并行执行，但结果按请求顺序返回。

**核心思想**：**延迟不是工具执行时间，是等待时间**。如果工具A执行10秒、工具B执行5秒，串行需要15秒，并行只需要10秒。

**对我的项目有没有用？**

有。Step 1的多个搜索query可以并行，这就是StreamingToolExecutor的思想。

---

## 七、综合借鉴方案

### 7.1 按优先级排序的借鉴清单

| 优先级 | 借鉴点 | 来源 | 工作量 | 预期收益 |
|---|---|---|---|---|
| **P0（本周）** | 借鉴点4：Append-Only Checkpoint | Claude Code | 2-4h | 崩溃后可恢复 |
| **P0（本周）** | 借鉴点5：Circuit Breaker | Claude Code | 2-4h | 防止成本失控 |
| **P0（本周）** | 借鉴点2：System Prompt分层组装 | Claude Code | 2-4h | 提升输出质量 |
| **P1（下周）** | 借鉴点3：Search SubAgent并行 | Claude Code | 1-2d | Step 1延迟降低50-70% |
| **P1（下周）** | 借鉴点12：模型分层路由 | Hermes | 4-8h | 成本降低30-50% |
| **P1（下周）** | 借鉴点1：搜索结果渐进压缩 | Claude Code | 4-8h | 防止上下文膨胀 |
| **P2（Demo后）** | 借鉴点10：三层记忆系统 | Hermes | 2-3d | 跨行业知识复用 |
| **P2（Demo后）** | 借鉴点13：LangGraph Checkpointer | LangGraph | 1-2d | 生产级状态管理 |
| **P2（Demo后）** | 借鉴点14：Human-in-the-Loop | LangGraph | 1d | 人工审查支持 |
| **P3（未来）** | 借鉴点8：Lobster每步Reflect | OpenClaw | 1d | 质量提升 |
| **P3（未来）** | 借鉴点10+11：Persistent Memory + Periodic Nudge | Hermes | 2-3d | Agent越用越聪明 |

### 7.2 本周可落地：最小可行借鉴（MVB）

这3个借鉴点加起来约8-12小时工作量，但对系统鲁棒性的提升最大：

**组合方案：Checkpoint + Circuit Breaker + Prompt分层**

```python
# 改进后的frost_agent.py 核心骨架

import asyncio
from datetime import datetime

class FrostAgent:
    """
    借鉴Claude Code + Hermes + LangGraph的A2增强版
    """
    
    def __init__(self):
        self.checkpoint = AppendOnlyCheckpoint()
        self.breaker = CircuitBreaker(max_failures=3)
        self.prompt_asm = SystemPromptAssembler()
        self.model_router = ModelRouter()
    
    async def run(self, industry_name: str) -> str:
        # 1. 尝试恢复（借鉴Claude Code append-only + LangGraph checkpointer）
        state = self.checkpoint.recover(industry_name)
        if state:
            print(f"📋 从checkpoint恢复，已完成 {len(state.steps)} 步")
        else:
            state = ReportState(industry_name=industry_name)
        
        # 2. 执行未完成的步骤
        steps = self._get_remaining_steps(state)
        
        for step_id, step_fn in steps:
            print(f"\n▶️  执行: {step_id}")
            
            # 借鉴Claude Code：分层组装prompt
            system_prompt = self.prompt_asm.assemble(step_id, state, methodology)
            
            # 借鉴Hermes：按步骤选择模型
            model = self.model_router.get_model(step_id)
            
            # 借鉴Claude Code：circuit breaker保护
            result = await self.breaker.call(
                self._execute_step,
                step_fn,
                system_prompt,
                state,
                model,
            )
            
            # 借鉴Claude Code：append-only checkpoint
            state.steps.append(result)
            self.checkpoint.save_step(state, result)
            
            # 借鉴Hermes：低置信度时微型Reflect
            if result.confidence.startswith("low"):
                await self._mini_reflect(result, state)
        
        # 3. 输出最终报告
        return self._assemble_report(state)
```

### 7.3 关键认知：不是抄功能，是抄设计哲学

| 来源 | 设计哲学 | 在我们的项目中如何体现 |
|---|---|---|
| **Claude Code** | "90%的代码在循环周围" | Checkpoint、Circuit Breaker、错误恢复就是"循环周围的系统" |
| **Claude Code** | "Context是绑定约束" | 搜索结果渐进压缩、Prompt缓存对齐 |
| **OpenClaw** | "文件就是一切" | 方法论+Checkpoints+报告全用Markdown/JSONL |
| **Hermes** | "Agent会成长" | Persistent Memory积累行业分析经验 |
| **LangGraph** | "State是基础设施" | Checkpointer自动持久化，开发者无感知 |

### 7.4 不需要借鉴的（明确排除）

| 设计 | 来源 | 排除原因 |
|---|---|---|
| Claude Code的权限系统（7种模式+ML分类器） | Claude Code | 行业定义Agent不执行系统命令，不需要权限控制 |
| Claude Code的Shell Sandbox | Claude Code | 同上，不涉及文件系统操作 |
| OpenClaw的20+通信平台适配 | OpenClaw | 行业定义Agent是CLI工具，不是聊天机器人 |
| Hermes的GEPA自我进化 | Hermes | 行业定义的方法论由专家维护，不需要Agent自主进化 |
| Hermes的语音模式 | Hermes | CLI工具不需要 |
| LangGraph的循环图/分支 | LangGraph | A2架构是线性流程，暂不需要复杂控制流 |

---

## 八、总结

这份调研的核心发现：**好的Agent架构不是设计出来的，是从工程实践中长出来的**。

Claude Code的512K行代码告诉我们，一个可靠的Agent需要的不是更聪明的模型，而是：
- **崩溃后能恢复**（Checkpoint）
- **失败时有保护**（Circuit Breaker）
- **上下文不爆炸**（渐进式压缩）
- **任务能并行**（SubAgent隔离）
- **成本可控**（模型分层）

这些都不是AI算法，是软件工程的基本功。把这些基本功做好，A2架构就能从Demo变成生产级系统。

**下一步行动**：从P0的3个借鉴点开始（Checkpoint + Circuit Breaker + Prompt分层），8-12小时工作量，系统鲁棒性质的飞跃。

---

*文档版本：v1.0 | 调研日期：2026-06-04*
*信息来源：Claude Code arXiv论文(2604.14228v1)、OpenClaw官方文档、Hermes GitHub/Nous Research、LangGraph官方文档*
