# Agent架构调研与借鉴报告 — Harness Engineering 专项

> 主题：Anthropic 2026年Harness Engineering对行业定义Agent的借鉴意义
> 核心发现："模型是引擎，Harness才是整辆车"——这是2026年Agent架构领域最重要的认知升级
> 调研来源：Anthropic Engineering官方博客（2026年3-5月系列文章）、arXiv论文、社区深度分析
> 日期：2026-06-04

---

## 一、我先坦诚承认：之前的两份报告漏掉了什么

在回答你的问题之前，我需要诚实地说：**之前两份报告确实没有涉及Harness Engineering。这是一个重大盲区。**

原因：Harness Engineering是Anthropic在2026年3月才系统提出的概念，此前业界讨论主要集中在Prompt Engineering和Context Engineering层面。我之前的调研虽然触及了Claude Code的具体实现（Checkpoint、Circuit Breaker等），但没有将其上升到"Harness"这个系统性的架构框架层面来理解。

这个盲区的重要性在于：**如果只看Prompt Engineering和Context Engineering，你会以为Agent的竞争力在于"怎么写prompt"；但Harness Engineering告诉你，真正的竞争力在于"怎么设计Agent的运行时"——这是一个根本性的认知升级。**

---

## 二、Harness Engineering是什么：从Prompt到Runtime的范式转移

### 2.1 演化脉络：三个时代的Agent设计

Anthropic明确提出了Agent设计的三个演化阶段：

| 时期 | 核心技能 | 核心问题 | 设计层面 |
|---|---|---|---|
| **Through 2024** | **Prompt Engineering** | "How do you write the instruction?" | 告诉模型做什么 |
| **2024-2025** | **Context Engineering** | "How do you feed background information?" | 给模型提供什么材料 |
| **2026-Now** | **Harness Engineering + Environment Engineering** | "How do you configure the agent runtime?" + "How do you bound the world it acts in?" | 设计模型运行的环境 |

**关键认知升级**：Prompt Engineering和Context Engineering都是"给模型下指令"；Harness Engineering是"给模型搭舞台"——设计一个让模型持续、稳定、可靠工作的运行时环境。

### 2.2 Harness Engineering vs Environment Engineering

Anthropic进一步将2026年的设计拆分为两个并行子学科：

```
┌─────────────────────────────────────────────────────────┐
│                   Agent System                           │
├─────────────────────────┬───────────────────────────────┤
│   Harness Engineering   │   Environment Engineering     │
│   (进程内)               │   (进程外)                     │
│                         │                               │
│ • 权限系统               │ • OS用户权限                   │
│ • Hooks/PreToolUse      │ • Docker容器                  │
│ • MCP服务器配置          │ • 网络隔离                     │
│ • CLAUDE.md引导         │ • 凭证管理                     │
│ • 工具表面配置           │ • 文件系统边界                 │
│ • Agent循环设计          │ • 审计日志管道                 │
│                         │                               │
│ "Runtime inside"        │ "World outside"               │
└─────────────────────────┴───────────────────────────────┘
```

**对行业定义项目的意义**：行业定义Agent目前只有Harness层（六步循环），几乎没有Environment层（没有容器隔离、没有网络限制、没有凭证管理）。这是一个明显的短板。

---

## 三、Anthropic 2026年的核心架构：Managed Agents

### 3.1 整体架构图

Anthropic在2026年5月的博客"Scaling Managed Agents: Decoupling the brain from the hands"中公布了生产级Agent的完整架构：

```
┌──────────────────────────────────────────────────────────────┐
│                        Harness (控制面)                        │
│                     Claude + Harness Logic                     │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Context   │  │  Tool       │  │   Orchestrator      │  │
│  │   Builder   │  │  Router     │  │   (循环调度)         │  │
│  │             │  │             │  │                     │  │
│  │ 从session、  │  │ 分发动作给   │  │ • 决定下一步         │  │
│  │ memory、     │  │ MCP、        │  │ • 管理harness策略    │  │
│  │ skills组装   │  │ sandbox、    │  │ • 模型路由           │  │
│  │ 高信号上下文  │  │ 外部工具     │  │ • 故障恢复           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼ execute(name, input) -> string
┌──────────────────────────────────────────────────────────────┐
│                    Sandbox (执行面)                            │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ 代码执行  │  │ 浏览器    │  │ MCP      │  │ 文件系统    │  │
│  │ 环境      │  │ (Playwright│  │ Servers  │  │ (受限)      │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                                                               │
│  特征：允许失败、允许重建、不保存状态                           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│              Session Event Log (持久状态)                      │
│                                                               │
│  user_input → model_response → tool_call → tool_result        │
│  → file_change → error → retry → approval → checkpoint        │
│                                                               │
│  特征：不跟容器绑定、可查询、可恢复、可审计                      │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│              Credential Proxy / Vault (凭证边界)               │
│                                                               │
│  不可信的执行环境永远不会直接拿到token                          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│              Trace / Eval (贯穿全程)                           │
│                                                               │
│  过程记录 + 结果评估 + 回归测试 + A/B harness改动              │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 三个最关键的设计原则

**原则一：Brain/Hands解耦**

Harness是**相对无状态的控制面**，Sandbox是**可调用、可重建的执行资源**。二者通过简单接口连接：

```
execute(name, input) -> string
```

收益：
- Sandbox挂了，任务不挂
- Brain可以先工作，Sandbox后加载
- 一个Brain可以调多个Hands

**原则二：Session is not Claude's context window**

| | Session Event Log | Context Window |
|---|---|---|
| **本质** | 任务发生过的持久记录（账本） | 模型这次推理能看到的token（工作区） |
| **生命周期** | 跨会话持久 | 单次推理 |
| **操作** | 尽量完整、可查、可恢复 | 可以整理、压缩、裁剪、重组 |
| **类比** | 数据库事务日志 | CPU寄存器 |

```
原始事件长期保存（Session Log）
        ↓
Context Builder 动态选择
        ↓
当前模型调用看到一个高信号上下文（Context Window）
```

**原则三：Harness策略会被模型升级重新定价**

这是Anthropic的原话（*"harness strategies get repriced every time the model upgrades"*）。意思是：

- 今天的planner有用，明天可能因为模型规划能力变强而成为拖慢系统的开销
- 今天的evaluator能救错，明天可能只是增加成本
- 今天的context reset是必要的补丁，明天可能是无用复杂度

**推论**：生产级Harness不能只会加东西，也要能**删除东西**（ablation）。每次模型升级后，都要重新测试每个harness组件是否还值得保留。

---

## 四、Three-Agent Harness：Planner + Generator + Evaluator

### 4.1 为什么需要三个Agent

Anthropic在2026年3月的博客"Harness design for long-running application development"中系统阐述了这个架构。核心问题是**两个失败模式**：

| 失败模式 | 表现 | 根本原因 |
|---|---|---|
| **Context Anxiety（上下文焦虑）** | Agent在上下文快满时草草收尾，不是因为做完了，而是因为"感觉"window快满了 | 模型感知到上下文压力后改变行为 |
| **Self-Evaluation Bias（自我评估偏差）** | Agent审查自己的工作时过度乐观，"自信地夸自己做得好，实际质量一般" | 生成和评估在同一上下文中的系统性偏差 |

**解决方案**：借鉴GAN（Generative Adversarial Network）的思想——**把"干活"和"挑刺"彻底分开**。

### 4.2 三个Agent的分工

```
Planner（规划者）
├── 输入：1-4句话的用户prompt
├── 输出：完整产品规格（JSON格式，功能列表、验收标准、优先级）
├── 约束：不写代码，只管"做什么"和"为什么"
├── 设计：范围要大胆，技术细节不过早指定（避免错误级联）

Generator（生成者）
├── 输入：Planner的产品规格
├── 输出：按sprint实现的代码/内容
├── 约束：每次一个feature，git版本控制，自评但不作数

Evaluator（评估者）
├── 输入：Generator的产出 + Sprint Contract
├── 输出：结构化评估报告（通过/失败 + 具体问题）
├── 工具：Playwright MCP（实际点击应用、测试UI/API/数据库）
├── 设计：被故意调得"挑剔"，独立上下文（看不到Generator的推理过程）
```

### 4.3 Sprint Contract：最关键的机制

在Generator开始写代码之前，Generator和Evaluator**先谈判"完成"的定义**：

```
Generator: "我这轮要做X，完成后Y功能应该能工作，测试方式是Z"
Evaluator: "同意，但你还需覆盖A场景的边界情况"
Generator: "好的，修正后的完成标准是X+A，测试方式是Z+W"
Evaluator: "确认，这是本轮的Sprint Contract"
```

**为什么这个机制重要**：
- 避免"我觉得做完了你觉得没做完"的争议
- 把产品规格的high-level意图翻译成testable的验收标准
- 作为上下文重置时的交接物（新Agent可以从Contract开始，不需要继承完整历史）

### 4.4 实测效果

Anthropic用"2D Retro Game Maker"做了对比实验：

| 方案 | 运行时间 | 成本 | 质量 |
|---|---|---|---|
| **Solo Agent** (Opus 4.5) | 20分钟 | $9 | "能启动但核心功能断开"（代码层面有bug） |
| **Three-Agent Harness** | 6小时 | $200 | "生产级可用"（功能完整、可测试通过） |

**成本增加了22倍，但产出从"不可用"变成了"可用"。这就是Harness Engineering的核心trade-off：用结构性开销换可靠性。**

---

## 五、对行业定义Agent的直接借鉴

### 5.1 最重要的借鉴：Evaluator独立化（解决Self-Evaluation Bias）

**当前A2架构的问题**：

A2的Step 5（自检）用的是**同一个LLM实例**——模型自己生成报告，然后自己检查。这正是Anthropic发现的"self-evaluation bias"场景。

```
当前A2：同一个LLM贯穿Step 1-6
Step 1-4: 生成报告 ← 同一个模型
Step 5: 自检 ← 还是同一个模型检查自己的工作

问题：模型倾向于对自己生成的内容过度宽容
```

**借鉴Three-Agent Harness的解决方案**：

```
改进版A2：Generator和Evaluator分离
Step 1-4: Generator Agent（生成报告）
Step 5: Evaluator Agent（独立LLM调用，不同system prompt，甚至不同模型）

关键：Evaluator看不到Generator的推理过程，只看最终产出
```

**具体实现**：

```python
# evaluator.py — 借鉴Anthropic Three-Agent Harness的Evaluator设计

class IndependentEvaluator:
    """
    借鉴Anthropic的Generator-Evaluator分离：
    - 独立的LLM调用（不同的system prompt）
    - 独立的上下文（看不到生成过程的推理）
    - 被故意调得"挑剔"
    """
    
    SYSTEM_PROMPT = """你是一个严格的行业定义报告审查员。
    
    你的工作是审查报告质量，标准非常严格。
    你倾向于发现问题，而不是确认一切正常。
    你不对生成过程负责，你只对最终质量负责。
    
    审查维度（C1-C5）：
    C1. 区分度测试：报告是否清楚区分了"行业定义"和"维基百科第一段"？
    C2. 废话过滤：是否有大量通用描述而非行业特有分析？
    C3. 结构性测试：维度是否覆盖供给侧/需求侧/成本侧/技术侧/制度侧？
    C4. 边界清晰度：行业边界是否明确？相邻行业如何区分？
    C5. 推理可见：每个判断是否包含"为什么"？
    
    输出格式：
    - 每个维度：PASS/FAIL + 具体问题描述
    - 如果FAIL，给出"可执行"的修改建议（具体到章节、段落）
    - 总体判断：PASS / FAIL_WITH_FIXES
    """
    
    async def evaluate(self, report: str, state: ReportState) -> dict:
        """
        独立评估：只接收最终报告，不接收生成过程的推理
        这避免了Anthropic发现的self-evaluation bias
        """
        # 构建评估上下文（不暴露生成过程的reasoning）
        eval_context = {
            "industry": state.industry_name,
            "methodology_version": state.methodology_version,
            "report": report,  # 只看最终报告
            # 注意：不包含step 1-4的reasoning字段
        }
        
        result = await llm_call(
            system=self.SYSTEM_PROMPT,
            user=json.dumps(eval_context, ensure_ascii=False),
            model="claude-sonnet-4-5",  # 可以用不同模型
        )
        
        return {
            "checks": result.checks,
            "overall": result.overall,
            "fixes_required": result.fixes,
            "evaluator_model": "claude-sonnet-4-5",  # 记录评估者身份
        }
```

**预期收益**：自检的严格程度提升，减少"我觉得没问题但实际有问题"的情况。

---

### 5.2 借鉴Sprint Contract：每步之前先定义"完成"标准

**当前A2架构的问题**：

每步的Contract定义了输出Schema，但没有明确定义"什么样的输出算通过"。Step 5的自检标准（C1-C5）是在最后才检查，发现问题时已经太晚了。

**借鉴方案**：在**每步开始之前**，Generator和Evaluator（或Orchestrator）先达成Contract：

```python
# sprint_contract.py — 借鉴Anthropic的Sprint Contract

class SprintContract:
    """
    借鉴Anthropic：每步开始前先定义"完成"标准
    不是事后检查，而是事前约定
    """
    
    @staticmethod
    async def negotiate(step_id: str, step_context: dict) -> dict:
        """
        在步骤执行前，协商完成标准
        """
        negotiation_prompt = f"""
        步骤：{step_id}
        上下文：{json.dumps(step_context, ensure_ascii=False)}
        
        请输出该步骤的Sprint Contract：
        1. 本步骤要完成什么？
        2. 完成的验收标准是什么？（可testable的条件）
        3. 常见失败模式是什么？
        4. 如何验证输出质量？
        
        格式：
        {{
            "deliverable": "交付物描述",
            "acceptance_criteria": ["条件1", "条件2", ...],
            "common_failures": ["失败模式1", ...],
            "verification_method": "验证方式"
        }}
        """
        
        contract = await llm_call(negotiation_prompt)
        return contract

# 在Orchestrator中使用
async def run_step_with_contract(step_id, state, methodology):
    # 1. 协商Contract（借鉴Sprint Contract）
    contract = await SprintContract.negotiate(step_id, {
        "industry": state.industry_name,
        "previous_steps": [s.step_id for s in state.steps],
    })
    
    print(f"📋 Sprint Contract for {step_id}:")
    print(f"   交付物：{contract['deliverable']}")
    print(f"   验收标准：{contract['acceptance_criteria']}")
    
    # 2. 执行步骤
    result = await step_fn(state, methodology)
    
    # 3. 按Contract验证
    verification = await verify_against_contract(result, contract)
    
    return result, verification
```

---

### 5.3 借鉴Session as Event Log：重新设计State管理

**当前A2架构的问题**：

ReportState在内存中累积，只保存每步的完整StepOutput。没有事件日志的语义，崩溃后无法恢复。

**借鉴Anthropic的Session Event Log设计**：

```python
# event_log.py — 借鉴Anthropic的Session Event Log

class SessionEventLog:
    """
    借鉴Anthropic：Session是事件日志，不是State对象
    
    事件类型：
    - step_start: 步骤开始
    - llm_call: LLM调用（记录input/output/token消耗）
    - tool_call: 工具调用
    - tool_result: 工具返回
    - step_complete: 步骤完成
    - error: 错误
    - retry: 重试
    - checkpoint: 检查点
    - evaluation: 评估结果
    
    设计原则：
    - 只追加，不修改
    - 每条记录有时间戳
    - 可查询、可恢复、可审计
    """
    
    def __init__(self, industry_name: str):
        self.log_path = f"logs/{industry_name}_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        os.makedirs("logs", exist_ok=True)
    
    def log(self, event_type: str, data: dict):
        """追加写入事件"""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "data": data,
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    
    def query(self, event_type: str | None = None, step_id: str | None = None) -> list[dict]:
        """查询事件日志"""
        results = []
        with open(self.log_path) as f:
            for line in f:
                event = json.loads(line)
                if event_type and event["event_type"] != event_type:
                    continue
                if step_id and event["data"].get("step_id") != step_id:
                    continue
                results.append(event)
        return results
    
    def recover_state(self) -> ReportState:
        """
        从事件日志恢复State
        不需要复杂的状态机回放，只需要读取到最后一条完整记录
        """
        state = ReportState()
        for event in self.query():
            if event["event_type"] == "step_complete":
                state.steps.append(StepOutput.model_validate(event["data"]["output"]))
            elif event["event_type"] == "industry_set":
                state.industry_name = event["data"]["industry_name"]
        return state
```

**关键区别**：原来的State是"对象"，新的Session是"事件流"。对象视角下，崩溃后需要复杂的序列化/反序列化；事件流视角下，崩溃后只需要读日志到最后一行。

---

### 5.4 借鉴Context Builder：动态组装高信号上下文

**当前A2架构的问题**：

每步的上下文是"方法论文档切片 + 前序步骤完整输出"。随着步骤推进，上下文会线性增长。

**借鉴Anthropic的Context Builder设计**：

```python
# context_builder.py — 借鉴Anthropic的Context Builder

class ContextBuilder:
    """
    借鉴Anthropic：从Session Event Log中动态选择高信号上下文
    
    不是简单地把所有历史塞进prompt，而是：
    1. 按相关性选择（当前步骤需要哪些前序信息）
    2. 按重要性加权（关键决策保留，次要信息摘要）
    3. 按时效性过滤（过期的工具结果丢弃）
    """
    
    def __init__(self, event_log: SessionEventLog):
        self.event_log = event_log
        self.max_context_tokens = 30000  # 上下文token上限
    
    async def build(self, step_id: str, state: ReportState) -> str:
        """
        为当前步骤构建高信号上下文
        """
        context_parts = []
        
        # Layer 1: 静态身份+Hard Rules（始终保留，借鉴Claude Code的18层思想）
        context_parts.append(self._load_static_identity())
        
        # Layer 2: 当前步骤的方法论切片
        context_parts.append(self._slice_methodology(step_id))
        
        # Layer 3: Session摘要（不是完整历史，而是动态生成的摘要）
        # 借鉴Anthropic的Context Builder：从event log中选择相关事件
        session_summary = await self._generate_session_summary(step_id, state)
        context_parts.append(session_summary)
        
        # Layer 4: 当前任务指令（最高权重，放最后）
        context_parts.append(self._get_step_directive(step_id, state))
        
        full_context = "\n\n---\n\n".join(context_parts)
        
        # 如果超出预算，渐进压缩（借鉴Claude Code的compaction pipeline）
        if self._estimate_tokens(full_context) > self.max_context_tokens:
            full_context = await self._compact_context(full_context, step_id)
        
        return full_context
    
    async def _generate_session_summary(self, current_step_id: str, state: ReportState) -> str:
        """
        借鉴Anthropic Context Builder：
        不是简单地拼接前序步骤，而是动态生成摘要
        """
        # 获取与当前步骤最相关的前序步骤
        relevant_steps = self._select_relevant_steps(current_step_id, state.steps)
        
        # 生成结构化摘要
        summary = "## 前序步骤摘要\n\n"
        for step in relevant_steps:
            summary += f"### {step.step_label}\n"
            summary += f"- 关键结论：{step.result.get('summary', 'N/A')}\n"
            summary += f"- 置信度：{step.confidence}\n"
            summary += f"- 关键决策：{step.reasoning[:200]}...\n\n"
        
        return summary
    
    def _select_relevant_steps(self, current_step_id: str, all_steps: list) -> list:
        """
        根据当前步骤选择最相关的前序步骤
        不是所有步骤都需要，只选相关的
        """
        # Step 4（内容生成）需要Step 2（维度筛选）和Step 3（结构决策）
        # 但不需要Step 1的原始搜索结果（已经提炼过了）
        relevance_map = {
            "4_content_generation": ["2_dimension_screening", "3_structure_decision"],
            "5_self_check": ["2_dimension_screening", "4_content_generation"],
        }
        
        relevant_ids = relevance_map.get(current_step_id, [s.step_id for s in all_steps])
        return [s for s in all_steps if s.step_id in relevant_ids]
```

---

### 5.5 借鉴Harness/Environment分层：为行业定义Agent设计最小Environment

行业定义Agent目前完全没有Environment层。借鉴Anthropic的分层思想，可以设计一个最小可行的Environment：

```python
# environment.py — 借鉴Anthropic的Environment Engineering

class MinimalEnvironment:
    """
    行业定义Agent的最小Environment层：
    
    行业定义Agent不执行系统命令、不操作文件系统、不访问网络（除了搜索API），
    所以Environment层比Claude Code简单得多。
    
    但仍然需要：
    1. 搜索API的凭证管理（不要硬编码在代码中）
    2. LLM API的凭证管理
    3. 输出文件的权限控制（防止覆盖已有报告）
    4. Token消耗的审计日志
    """
    
    def __init__(self):
        self.credential_vault = CredentialVault()
        self.audit_logger = AuditLogger()
    
    def get_search_api_key(self) -> str:
        """从凭证库获取搜索API key，不直接暴露在代码中"""
        return self.credential_vault.get("TAVILY_API_KEY")
    
    def get_llm_api_key(self, provider: str) -> str:
        """从凭证库获取LLM API key"""
        return self.credential_vault.get(f"{provider.upper()}_API_KEY")
    
    def check_output_safety(self, file_path: str) -> bool:
        """检查输出路径是否安全（不会覆盖重要文件）"""
        # 禁止写入到非workspace目录
        abs_path = os.path.abspath(file_path)
        workspace = os.path.abspath("workspace")
        if not abs_path.startswith(workspace):
            raise EnvironmentError(f"禁止写入到workspace外：{file_path}")
        return True
    
    def log_token_usage(self, step_id: str, model: str, input_tokens: int, output_tokens: int):
        """记录token消耗（成本审计）"""
        self.audit_logger.log({
            "event": "token_usage",
            "step_id": step_id,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": self._calculate_cost(model, input_tokens, output_tokens),
        })
```

---

## 六、综合借鉴方案：A2+Harness架构

### 6.1 改进后的架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      Orchestrator (Harness)                   │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Context   │  │  Contract   │  │  Evaluator          │  │
│  │   Builder   │  │  Negotiator │  │  (独立LLM)           │  │
│  │   (动态     │  │  (Sprint    │  │                     │  │
│  │    组装)    │  │   Contract) │  │ • 独立system prompt │  │
│  └─────────────┘  └─────────────┘  │ • 看不到生成推理    │  │
│                                     │ • 被调得"挑剔"     │  │
│  ┌─────────────┐  ┌─────────────┐  └─────────────────────┘  │
│  │  Session    │  │  Circuit    │  ┌─────────────────────┐  │
│  │  Event Log  │  │  Breaker    │  │  Model Router       │  │
│  │  (持久)      │  │  (3次失败   │  │  (按步骤选模型)      │  │
│  │             │  │   断开)     │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌──────────┐        ┌──────────┐          ┌──────────┐
   │ Step 1   │        │ Step 2   │   ...    │ Step 5   │
   │ Search   │        │ Screen   │          │ Evaluate │
   │ (并行)    │        │          │          │ (独立)   │
   └──────────┘        └──────────┘          └──────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                    ┌──────────────────────┐
                    │   Session Event Log   │
                    │   (JSONL, append-only)│
                    └──────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
           ┌──────────────┐    ┌──────────────┐
           │ Checkpoint   │    │ Audit Log    │
           │ (崩溃恢复)    │    │ (成本审计)    │
           └──────────────┘    └──────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   Minimal Environment                         │
│                                                               │
│  • Credential Vault (API密钥管理)                             │
│  • Output Safety Check (防止覆盖)                             │
│  • Token Usage Audit (成本追踪)                               │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 借鉴优先级排序（新增Harness视角后重新排序）

| 优先级 | 借鉴点 | 来源 | 工作量 | 解决什么问题 |
|---|---|---|---|---|
| **🔴 P0** | **Evaluator独立化** | Three-Agent Harness | 4-8h | Self-evaluation bias |
| **🔴 P0** | **Session Event Log** | Managed Agents | 4-8h | 崩溃恢复+可审计 |
| **🔴 P0** | **Context Builder** | Managed Agents | 4-8h | 上下文质量 |
| **🟡 P1** | **Sprint Contract** | Three-Agent Harness | 4-8h | 每步完成标准前置 |
| **🟡 P1** | **Circuit Breaker** | Claude Code | 2-4h | 成本失控 |
| **🟡 P1** | **Brain/Hands解耦** | Managed Agents | 1-2d | 架构可扩展性 |
| **🟢 P2** | **Harness Ablation** | Managed Agents | 持续 | 删除过时策略 |
| **🟢 P2** | **Minimal Environment** | Environment Eng | 4-8h | 安全+凭证管理 |

### 6.3 本周最小可行改进（MVB）

基于Harness Engineering视角，本周应该优先做这3件事：

**改进1：Evaluator独立化（最重要）**

把Step 5从"同一个LLM自检"改成"独立Evaluator审查"：

```python
# 当前（有问题）
result = await call_llm_same_instance(
    system="你是行业定义Agent，请检查刚才生成的报告",
    user=report,
)
# 问题：同一个模型生成+检查，存在self-evaluation bias

# 改进后（借鉴Three-Agent Harness）
result = await independent_evaluator.evaluate(
    report=report,
    state=state,
    # Evaluator看不到生成过程的reasoning
    # 独立的system prompt，被调得"挑剔"
)
```

**改进2：Session Event Log（基础设施）**

把State从"内存对象"改成"事件日志"：

```python
# 当前
def run_step(state, step_fn):
    result = step_fn(state)
    state.steps.append(result)  # 只在内存中

# 改进后
def run_step(state, step_fn, event_log):
    event_log.log("step_start", {"step_id": step_fn.__name__})
    result = step_fn(state)
    state.steps.append(result)
    event_log.log("step_complete", {"step_id": step_fn.__name__, "output": result.model_dump()})
    # 自动持久化
```

**改进3：Context Builder（上下文质量）**

把"简单拼接历史"改成"动态选择高信号上下文"：

```python
# 当前
context = methodology_slice + "\n".join([str(s) for s in state.steps])

# 改进后
context = await context_builder.build(
    step_id=current_step,
    state=state,
    # 动态选择相关步骤、生成摘要、控制长度
)
```

---

## 七、关键认知升级

### 7.1 从"Prompt驱动"到"Harness驱动"

| 思维方式 | Prompt Engineering | Harness Engineering |
|---|---|---|
| **核心问题** | "这个prompt怎么写？" | "这个Agent怎么运行？" |
| **关注对象** | 单次LLM调用 | 整个任务生命周期 |
| **优化目标** | 输出质量 | 可靠性、成本、延迟、可恢复性 |
| **关键组件** | System prompt、 few-shot | Harness策略、Session管理、工具路由、错误恢复 |
| **失败处理** | 重试prompt | Circuit breaker、checkpoint、降级策略 |

### 7.2 最重要的三条设计哲学

1. **"模型是引擎，Harness才是整辆车"**
   - 好的Agent不是prompt写得好，而是运行时设计得好
   - Claude Code 512K行代码中，~99.7%在循环周围（Harness），不是循环本身

2. **"Session是账本，Context是工作区"**
   - 持久状态（Session Event Log）和推理上下文（Context Window）必须分离
   - 账本要尽量完整，工作区要精选高信号

3. **"Harness策略会被模型升级重新定价"**
   - 每次模型升级后要重新评估每个harness组件的价值
   - 能删除过时策略的能力，和能添加新策略的能力一样重要

---

## 八、参考来源

| 来源 | 日期 | 可信度 | 关键内容 |
|---|---|---|---|
| Anthropic, "Harness design for long-running application development" | 2026-03-24 | ★★★★★ | Three-Agent Harness原始论文，Planner+Generator+Evaluator |
| Anthropic, "Scaling Managed Agents: Decoupling the brain from the hands" | 2026-05 | ★★★★★ | Managed Agents完整架构，Brain/Hands解耦 |
| Anthropic, "Effective harnesses for long-running agents" | 2026-01 | ★★★★★ | Context resets、Initializer+Coding Agent模式 |
| Anthropic, "Effective context engineering for AI agents" | 2026 | ★★★★★ | Context Builder设计 |
| Anthropic, "Making Claude Code more secure and autonomous with sandboxing" | 2026 | ★★★★★ | Sandbox设计 |
| Claude Code Harness and Environment Engineering Guide (hidekazu-konishi.com) | 2026-04-28 | ★★★★☆ | Harness vs Environment分层详解，三种参考模式 |
| Anthropic's 3-Agent Architecture for AI Harnesses (ruh.ai) | 2026-06-01 | ★★★☆☆ | Three-Agent Harness技术细节分析 |
| Agent Engineering in 2026: The Harness Is the Product (markdown.engineering) | 2026-04-12 | ★★★★☆ | "Most teams should delete half their agents" |
| Harness Engineering介绍 (javaguide.cn) | 2026-05-21 | ★★★☆☆ | 六层架构、上下文管理、实战案例 |

---

*文档版本：v1.0 | 日期：2026-06-04*
*这份报告专门填补了前两份报告中Harness Engineering的盲区*
