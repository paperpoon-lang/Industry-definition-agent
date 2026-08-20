# 行业定义 Agent — 架构评估报告

> 版本：v1.0 | 日期：2026-06-04 | 评估范围：A2架构（结构化分步单Agent + State驱动）

---

## 执行摘要

### 评估结论

行业定义Agent的A2架构（结构化分步单Agent + State驱动）是一个**设计思路正确但尚未经过验证的原型架构**。它在核心设计原则（State驱动、Step Contracts、推理显式化）上与业界主流方向一致，但在工程完整性（错误处理、成本约束、断点恢复）上存在明显差距。

**总体评级：C+（可接受的原型，需补强后进入开发）**

### 关键发现

| 发现 | 优先级 |
|---|---|
| State Schema设计合理，与LangGraph/Claude Code同频 | 无需改动 |
| 六步Contract设计覆盖了行业定义的核心环节 | 无需改动 |
| **缺少Evaluator-Optimizer闭环**——Step 5自检失败后无自动回退 | 🔴 高 |
| **缺少Checkpoint/恢复机制**——进程崩溃后需从头开始 | 🔴 高 |
| **缺少成本与延迟约束**——未定义Token预算和超时机制 | 🟡 中 |
| **方法论版本引用不一致**——v1与v2混用 | 🟡 中 |
| **错误处理策略缺失**——LLM返回格式错误、API限流等场景未覆盖 | 🟡 中 |

### 建议行动

1. **立即**：统一方法论版本（确认v1还是v2），修正架构文档
2. **本周**：为每一步添加Token预算和超时机制
3. **本周**：实现State的JSON持久化（Checkpoint）
4. **下周**：设计Evaluator-Optimizer闭环（自检失败→自动修正→重试）
5. **Demo前**：补充错误处理策略（重试、降级、人工介入）

---

## 一、评估框架

### 1.1 评估维度

我们从以下7个维度评估Agent架构，权重基于行业定义项目的核心需求：

| 维度 | 权重 | 说明 | 为什么重要 |
|---|---|---|---|
| **正确性保证** | 25% | 方法论是否能在执行中不丢失、不被篡改 | 行业定义的质量取决于方法论的正确贯彻 |
| **可观测性** | 20% | 每一步的推理过程是否可追溯、可审查 | 行业定义需要向客户解释判断依据 |
| **可靠性** | 20% | 失败处理、断点恢复、异常处理 | 分析师不能容忍跑到第五步崩溃后从头来 |
| **成本效率** | 15% | API调用次数、Token消耗、运行时间 | 行业定义可能需要批量处理数十个行业 |
| **可扩展性** | 10% | 单Agent→多Agent、新增步骤的容易程度 | 未来可能需要并行搜索、专业子Agent |
| **可维护性** | 10% | 方法论与代码解耦、配置化程度 | 分析师需要频繁调整方法论而不改代码 |

### 1.2 评级标准

| 等级 | 定义 |
|---|---|
| A | 设计完善，可直接进入生产 |
| B | 设计合理，有小缺陷需修正 |
| C | 核心设计正确，但工程完整性不足，需补强 |
| D | 存在设计缺陷，需重新审视 |
| F | 设计不可接受，需重做 |

### 1.3 信息来源与置信度

本报告中的业界数据来自以下渠道，按可信度分级：

| 来源类型 | 可信度 | 说明 |
|---|---|---|
| 学术论文（arXiv） | ★★★★★ | 可验证、可引用 |
| 官方源码分析（GitHub） | ★★★★☆ | 基于 leaked/reverse-engineered 源码 |
| 官方博客/文档 | ★★★★☆ | 一手信息，可能有营销偏差 |
| 权威科技媒体 | ★★★☆☆ | VentureBeat、Reuters等 |
| 技术博客分析 | ★★★☆☆ | 个人/团队分析，可能有解读偏差 |
| 无法独立验证 | ★★☆☆☆ | 仅见于单一来源或报告本身 |

---

## 二、业界Agent架构调研

> 目的：了解2025-2026年Agent架构的主流设计模式，为评估A2架构提供参照系。

### 2.1 调研范围

| 类别 | 代表产品/框架 | 调研深度 | 信息来源 |
|---|---|---|---|
| **生产级产品** | Claude Code (Anthropic) | 深度 | 源码分析论文[^1]、官方博客、技术博客 |
| **生产级产品** | OpenClaw (Peter Steinberger) | 深度 | 官方文档、技术博客 |
| **生产级产品** | Hermes Agent (Nous Research) | 深度 | 官方文档、GitHub |
| **框架/平台** | LangGraph, CrewAI, AutoGen, Dify | 中度 | 官方文档、社区 |
| **设计模式** | Anthropic六大架构模式 | 引用 | Anthropic官方指南 |

[^1]: *Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems*, arXiv:2604.14228v1, 2026年4月

### 2.2 第一梯队：生产级产品

#### 2.2.1 Claude Code（Anthropic）

**基本信息**：
- 发布时间：2025年2月（公开版）
- Claude Code ARR：约25亿美元（2026年2月数据，来源：Reuters/Anthropic官方披露）
- 技术基础：TypeScript，~512,000行源码
- 开源状态：源码曾被泄露，社区有大量反向工程分析

**核心架构特征**（来源：arXiv论文 + GitHub源码分析，可信度★★★★★）：

| 维度 | 设计 | 说明 |
|---|---|---|
| **核心循环** | `while(true)` 循环，~1,421行 | 简单循环 + 复杂约束系统 |
| **System Prompt** | 18层section动态组装 | 缓存部分 + 每会话部分，严格按序组装 |
| **上下文压缩** | 5层渐进式流水线 | Budget reduction → Snip → Microcompact → Context collapse → Auto-compact |
| **权限系统** | 7种模式 + ML分类器 | plan/default/acceptEdits/auto/dontAsk/bypassPermissions/bubble |
| **子Agent委派** | Orchestrator-Worker模式 | 隔离上下文，仅返回摘要 |
| **存储** | 追加写入式Markdown文件 | 不是向量数据库 |

**设计哲学**（来源：arXiv论文，可信度★★★★★）：

> "Context is the binding constraint that shapes nearly every other architectural decision."
> ——Claude Code源码分析论文

90%的代码在循环**周围**（上下文管理、权限、存储、错误处理），而非循环本身。

#### 2.2.2 OpenClaw

**基本信息**：
- 发布时间：2025年11月（初名Clawd，后更名Moltbot，最终定名OpenClaw）
- 作者：Peter Steinberger（奥地利开发者）
- GitHub Stars：~250,000（2026年3月初数据，来源：官方历史页面）
- 许可证：MIT

**核心架构特征**（来源：官方文档+CSDN技术分析，可信度★★★☆☆）：

| 维度 | 设计 |
|---|---|
| **架构范式** | Gateway-Node-Channel 三层解耦 |
| **Agent循环** | Lobster循环：Think→Act→Observe→Reflect（ReAct的工程化扩展） |
| **存储** | 纯Markdown文本，无数据库 |
| **通信** | 20+平台适配器 |
| **Skills** | AgentSkills系统，ClawHub社区 |

**核心创新**：Local-first + 聊天即操作系统。Lobster循环相比标准ReAct增加了"Reflect"反思阶段。

#### 2.2.3 Hermes Agent（Nous Research）

**基本信息**：
- 发布时间：2026年2月
- 组织：Nous Research（开源AI实验室，以Hermes模型系列闻名）
- GitHub Stars：~143,000（2026年5月中数据，来源：官方News页面）
- 许可证：MIT

**核心架构特征**（来源：官方文档+技术博客，可信度★★★☆☆）：

| 维度 | 设计 |
|---|---|
| **核心机制** | GEPA（Genetic-Evolution-based Prompt Adaptation）自我改进循环 |
| **记忆系统** | 三层：Session Memory + Persistent Memory(SQLite FTS5) + Skill Memory |
| **Skill系统** | 三级：内置→可选→社区，Agent可自主从经验创建Skill |
| **终端后端** | 6种：local, Docker, SSH, Daytona, Singularity, Modal |

**核心创新**：Agent会"成长"——用越久越聪明。通过将成功经验抽取为可复用Skill实现持续改进。

### 2.3 第二梯队：框架/平台层

| 框架 | 核心思想 | 与A2架构的相关性 |
|---|---|---|
| **LangGraph** | StateGraph状态机驱动 | 直接参考——State作为一等公民的设计与A2的ReportState同构 |
| **CrewAI** | 角色扮演多Agent协作 | 间接参考——若未来扩展到多Agent，可参考其角色分工模式 |
| **AutoGen** | 对话式多Agent编排 | 间接参考——编排器模式可参考 |
| **Dify** | 低代码Agent构建 | 低相关性——行业定义项目需要代码级控制 |

### 2.4 六大通用架构模式

来源：Anthropic官方Agent构建指南（2024年发布，2026年已成为行业共识）

| 模式 | 结构 | 适用场景 | A2的对应 |
|---|---|---|---|
| Prompt Chaining | A→B→C→D | 路径清晰的任务 | **Step 1-6的串行执行** |
| Routing | 输入→分类→路由 | 多类型输入 | 不适用（单一输入类型） |
| Parallelization | 并行扇出→聚合 | 独立子任务 | 未来可扩展（Step 1的多query搜索可并行） |
| Orchestrator-Worker | 编排器→N个Worker | 复杂任务分解 | 未来扩展方向 |
| Evaluator-Optimizer | 生成→评估→反馈→修正 | 需要质量保障 | **Step 5自检是简化版，缺自动修正** |
| Reflection | 行动→观察→反思→改进 | 需要自我改进 | **Step 5是单点反思，非持续反思** |

### 2.5 业界核心共识

1. **State-driven > Prompt-driven**：LangGraph、Claude Code、MetaAgent均采用State Schema作为核心抽象
2. **Start simple, add complexity only when needed**：Anthropic官方指南第一条，A2的"先单Agent"符合此原则
3. **Engineering > Model intelligence**：Claude Code源码分析显示，~99.7%代码在循环周围
4. **Context isolation via sub-agents**：子Agent隔离上下文防止退化
5. **Skills over static prompts**：方法论文档外部加载 = Skill系统思想
6. **Reflection is the meta-pattern of 2026**：自检、自我改进成为标配

---

## 三、A2架构评估

### 3.1 架构回顾

A2架构（结构化分步单Agent + State驱动）的核心设计：

- 一个Orchestrator管理六步串行执行
- 同一个LLM实例贯穿始终
- 每一步有明确的输入/输出Contract（StepOutput）
- State（ReportState）累积传递
- 方法论文档按步切片注入

### 3.2 逐项评估

#### 3.2.1 正确性保证（权重25%）—— 评级：B

| 评估项 | 设计 | 分析 |
|---|---|---|
| State传递 | ReportState累积传递，Schema约束 | ✅ 设计正确。State作为唯一事实来源，避免信息在步骤间丢失 |
| 方法论注入 | 按step_id切片，外部加载 | ✅ 设计正确。每步只接收相关的方法论片段，降低干扰 |
| 同LLM实例 | 同一个模型贯穿六步 | ⚠️ 有 trade-off。好处是方法论理解一致；坏处是前期错误会传递到后期 |
| 升级路径 | 预留了单Agent→多Agent | ✅ 前瞻性设计。State Schema和Contracts不变，只需替换某步的调用方式 |

**风险点**：当前设计依赖LLM对方法论的理解和执行。如果某步LLM输出偏离方法论，后续步骤会在此基础上继续偏离（级联错误）。缺少跨步骤的一致性校验机制。

#### 3.2.2 可观测性（权重20%）—— 评级：A-

| 评估项 | 设计 | 分析 |
|---|---|---|
| reasoning字段 | 每步必须包含推理过程 | ✅ 超越大多数框架。不仅记录结论，还记录为什么 |
| confidence标注 | 高/中/低 + 依据简述 | ✅ 实用。帮助用户快速定位不确定性 |
| abandoned记录 | 放弃的选择 + 原因 | ✅ 优秀。这是区分"专业分析"和"AI生成文本"的关键 |
| methodology_ref | 引用方法论文档章节 | ✅ 可审计。可追溯每一步的判断依据 |

**改进空间**：当前可观测性是"被动记录"——出了问题后去查日志。可以考虑增加"主动预警"——当confidence连续多步为"low"时主动提示用户。

#### 3.2.3 可靠性（权重20%）—— 评级：C

| 评估项 | 设计 | 分析 |
|---|---|---|
| Step 5自检 | C1-C5清单检查 | ✅ 有自检机制 |
| 自检失败处理 | 标记fixes_required，打印警告 | ⚠️ **不完整**。只有标记没有自动修正 |
| Checkpoint | 无 | ❌ **缺失**。进程崩溃后从头开始 |
| 错误处理 | 未定义 | ❌ **缺失**。LLM返回格式错误、API超时、限流等场景未覆盖 |
| 重试机制 | 未定义 | ❌ **缺失**。某步失败后怎么办？ |

**这是A2架构最大的薄弱环节**。一个Demo可以容忍这些问题，但如果行业定义分析师需要批量处理数十个行业，"跑到第五步崩溃从头来"是不可接受的。

#### 3.2.4 成本效率（权重15%）—— 评级：D

| 评估项 | 设计 | 分析 |
|---|---|---|
| Token预算 | 未定义 | ❌ 每一步没有Token上限 |
| 超时机制 | 未定义 | ❌ 每一步没有超时限制 |
| 搜索轮数 | "至少3轮" | ⚠️ 硬性下限但没有上限。一个复杂行业可能需要5-8轮搜索，Token消耗可能很高 |
| 模型选择 | 单一模型 | ⚠️ 搜索可用便宜模型（如DeepSeek V4 Flash），推理用高级模型（如Opus），可大幅降低成本 |

**成本估算（假设使用DeepSeek V4 + Tavily搜索）**：

| 步骤 | 预计API调用 | 预计Token消耗 | 备注 |
|---|---|---|---|
| Step 1（搜索） | 3-5次搜索 + 1次LLM | ~50K-100K | 搜索费用 + LLM总结 |
| Step 2（维度筛选） | 1次LLM | ~10K-20K | 纯推理 |
| Step 3（结构决策） | 1次LLM | ~10K-15K | 纯推理 |
| Step 4（内容生成） | 1次LLM（长输出） | ~50K-100K | 报告正文生成 |
| Step 5（自检） | 1次LLM | ~20K-30K | 检查清单 |
| **总计** | **约8-12次调用** | **~140K-265K Tokens** | **单次运行成本约$0.5-2** |

对于Demo来说可以接受。但如果行业定义每天处理20个行业，月成本约$300-1200。建议：
1. Step 1搜索使用最便宜可用的模型
2. 为每一步设置Token上限（如Step 4不超过100K Tokens）
3. 记录实际消耗以便后续优化

#### 3.2.5 可扩展性（权重10%）—— 评级：B+

| 评估项 | 设计 | 分析 |
|---|---|---|
| 单→多Agent升级 | State Schema不变，替换调用方式 | ✅ 设计前瞻 |
| 新增步骤 | Step Contracts模式可复制 | ✅ 新增步骤只需定义新Contract |
| 并行化 | 当前串行 | ⚠️ Step 1的多query搜索可并行化，降低延迟 |

#### 3.2.6 可维护性（权重10%）—— 评级：B+

| 评估项 | 设计 | 分析 |
|---|---|---|
| 方法论外部加载 | Markdown文件，按step_id切片 | ✅ 修改方法论不需改代码 |
| Schema约束 | Pydantic模型 | ✅ 类型安全 |
| 版本校验 | 无 | ⚠️ methodology_version字段存在但未与实际文件校验 |

### 3.3 综合评分

| 维度 | 权重 | 评级 | 加权得分 |
|---|---|---|---|
| 正确性保证 | 25% | B | 0.25 × 3.0 = 0.75 |
| 可观测性 | 20% | A- | 0.20 × 3.7 = 0.74 |
| 可靠性 | 20% | C | 0.20 × 2.0 = 0.40 |
| 成本效率 | 15% | D | 0.15 × 1.3 = 0.20 |
| 可扩展性 | 10% | B+ | 0.10 × 3.3 = 0.33 |
| 可维护性 | 10% | B+ | 0.10 × 3.3 = 0.33 |
| **加权总分** | **100%** | | **2.75 / 4.0 ≈ C+** |

### 3.4 与三大产品的对标

| 维度 | Claude Code | A2 | 差距分析 |
|---|---|---|---|
| State管理 | 对话累积 + Checkpoint | ReportState累积 | A2缺Checkpoint，但Schema更规范 |
| 上下文压缩 | 5层渐进式 | 方法论文档按步切片 | Claude Code更精细，但A2的场景更简单（一次性任务vs长时间会话） |
| 自检机制 | 内置权限+安全多层检查 | Step 5 C1-C5清单 | Claude Code是防御性自检（防危险操作），A2是质量自检（防低质输出）——目标不同 |
| 子Agent委派 | Orchestrator-Worker内置 | 预留升级路径 | A2的设计思路一致 |
| 错误处理 | 多层防御 + Circuit breaker | 未定义 | **A2需补强** |

**核心启示**：Claude Code源码分析论文的结论——"系统核心是一个简单的while循环，但大部分代码在循环周围的系统中"——A2的六步串行设计是正确的起点，但需要在"循环周围的系统"（错误处理、Checkpoint、成本约束）上投入更多工程。

---

## 四、差距分析

### 4.1 关键差距排序

| 排名 | 差距 | 影响 | 修复难度 |
|---|---|---|---|
| 1 | **缺少Evaluator-Optimizer闭环** | Step 5自检失败只能人工介入，无法自动修正 | 中 |
| 2 | **缺少Checkpoint/恢复** | 进程崩溃后丢失全部进度 | 低 |
| 3 | **缺少成本/延迟约束** | 可能导致单次运行成本过高或超时不返回 | 低 |
| 4 | **错误处理策略缺失** | LLM格式错误、API失败等场景未定义行为 | 中 |
| 5 | **方法论版本校验缺失** | methodology_version字段未与实际文件校验 | 低 |
| 6 | **缺少并行化** | Step 1的多query搜索串行执行，延迟较高 | 中 |

### 4.2 风险矩阵

```
影响高 │  ① Evaluator闭环      ④ 错误处理
       │       ●                   ●
       │
影响中 │  ② Checkpoint         ⑥ 并行化
       │       ●                   ●
       │
影响低 │  ③ 成本约束           ⑤ 版本校验
       │       ●                   ●
       └────────────────────────────────
              难度低    难度中    难度高
```

**建议优先修复②③⑤（低难度高/中影响，快速见效），然后处理①④⑥。**

---

## 五、改进建议

### 5.1 立即行动（本周内）

#### 建议1：统一方法论版本

```python
# models.py — 添加版本校验
class ReportState(BaseModel):
    methodology_version: str = "v2"  # 已确认为v2
    industry_name: str
    steps: list[StepOutput] = []
    final_report: str | None = None
    
    def validate_methodology_version(self, actual_file_path: str) -> bool:
        """校验State中的版本与实际加载的文件一致"""
        # TODO: 读取文件头中的版本声明，与methodology_version比对
        pass
```

**工作量**：< 1小时

#### 建议2：添加State持久化（Checkpoint）

```python
# frost_agent.py — 每步完成后保存State
import json

def save_checkpoint(state: ReportState, step_id: str):
    """每步完成后保存State到磁盘"""
    checkpoint_path = f"checkpoints/{state.industry_name}_{step_id}.json"
    with open(checkpoint_path, 'w') as f:
        f.write(state.model_dump_json(indent=2))

def load_checkpoint(industry_name: str, step_id: str) -> ReportState | None:
    """从磁盘恢复State"""
    checkpoint_path = f"checkpoints/{industry_name}_{step_id}.json"
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            return ReportState.model_validate_json(f.read())
    return None

# run()函数中添加
for step_id, step_fn in STEPS:
    # 检查是否有Checkpoint
    checkpoint = load_checkpoint(state.industry_name, step_id)
    if checkpoint:
        state = checkpoint
        continue
    
    result = step_fn(state, methodology)
    state.steps.append(result)
    save_checkpoint(state, step_id)  # 保存进度
```

**工作量**：2-4小时

#### 建议3：为每一步添加Token预算和超时

```python
# models.py — 添加预算配置
class StepBudget(BaseModel):
    max_tokens: int        # 该步最大Token消耗
    timeout_seconds: int   # 该步超时时间
    max_retries: int = 2   # 失败重试次数

STEP_BUDGETS = {
    "1_info_collection": StepBudget(max_tokens=100000, timeout_seconds=120),
    "2_dimension_screening": StepBudget(max_tokens=20000, timeout_seconds=60),
    "3_structure_decision": StepBudget(max_tokens=20000, timeout_seconds=60),
    "4_content_generation": StepBudget(max_tokens=150000, timeout_seconds=180),
    "5_self_check": StepBudget(max_tokens=50000, timeout_seconds=60),
}

# 在call_llm中添加预算检查
def call_llm(system_prompt: str, user_prompt: str, budget: StepBudget) -> dict:
    # TODO: 实现超时机制和Token计数
    pass
```

**工作量**：4-8小时

### 5.2 短期行动（下周内）

#### 建议4：实现Evaluator-Optimizer闭环

当前流程：Step 4生成 → Step 5检查 → 标记fixes_required → **结束**

改进流程：Step 4生成 → Step 5检查 → fixes_required? → **自动修正 → 重新检查**（最多3轮）

```python
# frost_agent.py — Step 5后添加修正循环
MAX_FIX_ROUNDS = 3

def run_with_fix_loop(state: ReportState, methodology: str) -> ReportState:
    for attempt in range(MAX_FIX_ROUNDS):
        # Step 4: 生成内容
        step4 = step4_content_generation(state, methodology)
        state.steps.append(step4)
        
        # Step 5: 自检
        step5 = step5_self_check(state, methodology)
        state.steps.append(step5)
        
        if step5.result["overall"] == "pass":
            break
        
        # 自动修正：将fixes_required注入下一步
        state.steps[-1].result["fix_instructions"] = step5.result["fixes_required"]
        print(f"⚠️  自检未通过，进入修正轮次 {attempt + 1}/3")
    
    return state
```

**工作量**：1-2天

#### 建议5：添加错误处理策略

```python
# 定义错误类型和应对策略
class StepError(Exception):
    pass

class LLMFormatError(StepError):
    """LLM返回不符合Schema"""
    recovery: str = "retry_with_stricter_prompt"

class APITimeoutError(StepError):
    """API调用超时"""
    recovery: str = "retry_with_longer_timeout"

class APIRateLimitError(StepError):
    """API限流"""
    recovery: str = "exponential_backoff"

# 在Orchestrator中添加错误处理
def run_step_with_retry(step_fn, state, methodology, budget: StepBudget):
    for attempt in range(budget.max_retries):
        try:
            return step_fn(state, methodology)
        except LLMFormatError:
            # 重试，使用更严格的prompt
            continue
        except APITimeoutError:
            # 增加超时时间重试
            continue
        except APIRateLimitError:
            # 指数退避
            time.sleep(2 ** attempt)
            continue
    
    # 所有重试失败，返回低confidence结果
    return StepOutput(
        step_id="error",
        confidence="low: 所有重试均失败",
        reasoning="错误处理机制触发",
        result={"error": "Step failed after all retries"}
    )
```

**工作量**：1-2天

### 5.3 中期行动（Demo后）

#### 建议6：搜索步骤并行化

Step 1的多个query可以并行搜索，降低延迟：

```python
import asyncio

async def search_parallel(queries: list[str]) -> list[dict]:
    """并行执行多个搜索query"""
    tasks = [search(q) for q in queries]
    return await asyncio.gather(*tasks)
```

**工作量**：1天

#### 建议7：不同步骤使用不同模型

| 步骤 | 建议模型 | 原因 |
|---|---|---|
| Step 1（搜索总结） | 便宜快速模型（DeepSeek V4 Flash） | 主要做信息提取，不需要深度推理 |
| Step 2-3（推理决策） | 中等模型（DeepSeek V4 Pro） | 需要推理但不需要超长上下文 |
| Step 4（内容生成） | 高级模型（Claude Opus/DeepSeek V4 Pro） | 需要高质量长文本输出 |
| Step 5（自检） | 与Step 4同级模型 | 需要准确判断质量 |

**预期成本降低**：30-50%

**工作量**：1天

---

## 六、总结

### 6.1 评估结论

A2架构的**核心设计是正确的**——State驱动、Step Contracts、推理显式化、方法论外部加载，这些选择与业界最优实践一致。但**工程完整性不足**，主要问题集中在：

1. **可靠性**（C）：缺Checkpoint、缺错误处理、缺重试
2. **成本效率**（D）：缺Token预算、缺超时、缺模型分层

对于一个Demo来说，当前架构可以跑通。但如果目标是**生产级交付**，需要在"循环周围的系统"上投入更多工程——这正是Claude Code源码分析论文的核心启示。

### 6.2 修正后的行动清单

| 优先级 | 行动 | 工作量 | 预期收益 |
|---|---|---|---|
| 🔴 P0 | 统一方法论版本 | < 1h | 消除版本不一致 |
| 🔴 P0 | State持久化（Checkpoint） | 2-4h | 进程崩溃后可恢复 |
| 🔴 P0 | Token预算+超时 | 4-8h | 防止成本和延迟失控 |
| 🟡 P1 | Evaluator-Optimizer闭环 | 1-2d | 自检失败可自动修正 |
| 🟡 P1 | 错误处理策略 | 1-2d | 提升鲁棒性 |
| 🟢 P2 | 搜索并行化 | 1d | 降低延迟 |
| 🟢 P2 | 模型分层 | 1d | 降低成本30-50% |

### 6.3 关键认知

> **不是"90分的架构差5分到95分"，而是"一个正确的原型需要补强工程完整性才能进入生产"。**

A2架构的价值在于它选择了正确的起点（简单、State驱动、预留扩展路径）。下一步不是追求更复杂的架构，而是**把这个简单的架构做得足够 robust**——这正是Anthropic "start simple"哲学的实践方式。

---

## 附录A：术语表

| 术语 | 解释 |
|---|---|
| **State-driven** | 以状态对象为核心抽象，每一步的操作围绕State的读写展开 |
| **Step Contract** | 每一步的输入/输出规范，包括Schema、方法论引用、自检条件 |
| **Checkpoint** | 执行过程中的持久化快照，用于崩溃恢复 |
| **Evaluator-Optimizer** | 生成→评估→优化→再评估的闭环 |
| **Compaction** | 上下文压缩，在Token受限时保留关键信息 |
| **GEPA** | Genetic-Evolution-based Prompt Adaptation，Hermes Agent的自我改进机制 |
| **Lobster循环** | OpenClaw的Agent循环：Think→Act→Observe→Reflect |

## 附录B：参考来源

| 编号 | 来源 | 可信度 | 说明 |
|---|---|---|---|
| [^1] | *Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems*, arXiv:2604.14228v1 | ★★★★★ | Claude Code架构分析论文 |
| [^2] | OpenClaw Official History Page (openclawroadmap.com) | ★★★★☆ | OpenClaw项目历史 |
| [^3] | Hermes Agent Official News (hermes-ai.net/news) | ★★★★☆ | Hermes官方更新 |
| [^4] | VentureBeat "Anthropic says it hit a $30 billion revenue run rate" (2026-05-08) | ★★★☆☆ | Anthropic收入数据 |
| [^5] | CSDN技术分析 "智能体Agent常见框架实现机制与架构差异分析" | ★★★☆☆ | OpenClaw Lobster循环分析 |
| [^6] | Claude Code System Prompt Reverse Engineering (codex.cadences.app) | ★★★☆☆ | 18层System Prompt分析 |
| [^7] | Anthropic Agent Building Guide (anthropic.com) | ★★★★☆ | 六大架构模式 |
| [^8] | "Claude AI Statistics 2026" (getpanto.ai) | ★★☆☆☆ | 综合统计数据 |

---

*文档版本：v1.0 | 评估日期：2026-06-04*
