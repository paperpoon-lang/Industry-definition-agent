# Agent 团队经验迁移指南 — 通用科研项目

> 版本：v2.0 | 日期：2026-07-07
> 来源：行业定义 agent 项目（v1.3 规则体系，203 行 project_rules.md + 592 行 Subagent 改进建议 + IDE 实测验证）
> 适用范围：所有在 Trae IDE 中搭建多 agent 团队的科研项目（计算机视觉、NLP、强化学习、生物信息等）
> 文档定位：**纯经验总结 + 可迁移模板**。本文档提供经验提炼、Trae 规范速查、填空式模板，由新 agent 根据具体科研项目实际情况定制。
> 规范查证：本地资料为主 + Trae 官网补充。所有官网信息已由 ai-architecture-fact-checker 核查（核查报告见交付汇报），矛盾点在第 7 章明确标注。

---

## 第 1 章 使用说明

### 1.1 本文档能帮你做什么

如果你是科研项目的主 agent（任何领域：CV/NLP/RL/BioInfo 等），本文档帮你完成三件事：

1. **理解一套经过实战验证的 agent 团队协作模式**（规则驱动 + 全局 agent 引用 + hooks 守卫）
2. **掌握 Trae 四类配置（Rules/Hooks/Skills/Agents）的官方规范**，避免踩格式错误
3. **用填空式模板快速定制**目标项目的 rules、hooks、subagent 提示词、方法论文件结构

### 1.2 使用方式

按以下顺序操作：

**步骤 0（P0 级前置，必须确认）**：确认你的项目使用 **SOLO Agent 模式**。普通 Builder Agent **不支持调用自定义智能体/Subagent**（见 [3.4 节](#34-agents智能体)限制说明），若使用 Builder 模式则以下所有 subagent 均无法被调用，agent 团队结构名存实亡。如不确定，先创建 SOLO Agent 会话后再开始。

1. 读本章 + 第 2 章（理解成功经验）
2. 读第 3 章（掌握 Trae 规范）+ 第 7 章（核查矛盾点）
3. 探索目标项目结构（识别核心代码文件、配置文件、实验日志、论文草稿）
4. 按第 6 章执行步骤，用第 4 章模板定制配置
5. 用一个小任务（如"复现 baseline"或"验证数据管道"）验证 agent 团队协作

### 1.3 重要声明

- 本文档是**经验总结 + 模板**，不是具体项目的最终方案。所有模板含 `<定制指引>` 占位符，必须根据项目实际填空。
- 本文档中的 Trae 规范数据来自官方文档（已标注来源 URL + 日期 + 可信度）。但 Trae 迭代很快，第 7 章列出的 5 个矛盾点必须由你核查后再使用。
- 本文档不使用 emoji（遵循当前项目约定）。

---

## 第 2 章 成功经验核心总结

来源项目采用 **"规则驱动 + 全局 agent 引用"** 模式：项目仓库内只存 rules + hooks + documents，subagent 定义在全局用户级，通过 rules 中的"推荐路由表"按名称引用。以下是 7 条可迁移的核心机制。

### 2.1 规则驱动模式

**机制**：项目仓库内只存三类配置——`.trae/rules/project_rules.md`（行为规则）、`.trae/hooks.json` + `.trae/hooks/*.py`（技术守卫）、`.trae/documents/`（实施计划）。subagent 定义不在项目内，避免不同项目间的 agent 定义冲突。

**为什么有效**：规则是每次会话自动注入的 System Prompt，承载编码规范、工作流、架构边界。subagent 全局引用则避免项目间重复定义。

**迁移要点**：目标项目应在 `.trae/rules/project_rules.md` 写科研场景规则（实验可复现性、数据来源标注、统计显著性），subagent 通过 Trae 全局账户创建后按名称引用。

### 2.2 12 条规则的设计哲学

来源项目的 `project_rules.md`（v1.3，203 行）含 12 条规则，每条解决一个具体痛点。以下是 12 条规则的精髓 + 科研场景迁移指引：

| 规则 | 精髓 | 科研场景迁移指引 |
|------|------|----------------|
| 1 事实性数据带来源 | 每个数字标注 URL+日期+可信度（5 级） | `<定制指引>` 实验数据/超参数/性能指标必须标注来源（论文引用+数据集版本+实验日期） |
| 2 不确定就说不知道 | 来源矛盾时写"需人工确认"比编数字好 | `<定制指引>` 实验结果不可复现时明确声明，不编造数据 |
| 3 架构评估先定义框架 | 评估维度+权重+评级标准+信息来源 | `<定制指引>` 模型对比评估时先定义框架（精度/速度/内存/泛化性） |
| 4 工程视角强制覆盖 | 成本/延迟/错误处理/恢复/并发五问 | `<定制指引>` 实验方案需回答：训练时间/显存占用/失败恢复/并发实验 |
| 5 代码建议必须具体 | 文件名+伪代码+工作量+优先级 | 直接迁移，需验证适配性 |
| 6 文件修改前必须先读 | 修改已有文件先 Read 完整读取 | 直接迁移，需验证适配性 |
| 7 术语和版本统一 | 同一概念全文同一术语 | `<定制指引>` 模型名称、数据集版本、超参符号全文统一 |
| 8 批判性思维门槛 | 能否跑通/第一个故障/放弃失去什么 | `<定制指引>` 实验方案能否通过最基础测试+第一个失败点+trade-off |
| 9 质量门 | >80 行 .md 触发审查清单 | `<定制指引>` 触发条件改为"产出 >80 行 .md 或新实验报告时" |
| 10 审查 agent 调用 | 文档类/代码类审查 agent 调用时机 | 直接迁移，按第 4 章 subagent 模板调整 agent 名称 |
| 11 采纳建议前去偏见化 | 验证技术前提+说明选择理由+记录反驳 | 直接迁移，需验证适配性（科研场景同样适用） |
| 12 多 agent 意见冲突仲裁 | 代码事实>已确认根因>trade-off 表>保守 | 直接迁移，需验证适配性 |

### 2.3 Hooks 守卫机制

**机制**：用 PreToolUse 的 `permissionDecision: ask` 模式拦截关键文件修改。来源项目拦截 `models.py` 修改前未调 architecture-critic 的情况。

**为什么有效**：rules 是文本约束（依赖 agent 自律），hooks 是技术守卫（每次必弹确认框）。两者互补：rules 定义"应该做什么"，hooks 提醒"别忘了做什么"。

**关键限制**：ask 模式**非真正强制**——用户可点"允许"绕过。真正的强制需要 hooks 能感知 agent 状态（是否调过 critic），这超出 Trae Hooks 当前能力。

**迁移要点**：目标场景应拦截核心模型/配置文件（如 `model.py`/`train.py`/`config.yaml`）的修改，提醒先调 architecture-critic 审查模型架构变更影响。

### 2.4 Agent 推荐路由表

**机制**：在 rules 规则 10 中增加"非强制推荐路由表"，列出"什么场景下可以尝试哪个 agent"。缓解 agent 发现性不足问题——16 个 subagent 只以一行描述呈现，做具体任务时容易想不起来。

**为什么有效**：rules 的"强制检查清单"点名了必须调的 agent，但不在清单里的 agent 容易被遗忘。推荐路由表覆盖"可以尝试"的场景，让 agent 选型时过一遍此表确认是否需要。

**迁移要点**：目标项目应建立科研场景路由表（如"实验设计阶段→experiment-design-agent"、"论文撰写阶段→paper-fact-checker"等）。

### 2.5 "实现完成"的精确定义

**机制**：规则 10.2 定义"实现完成"为同时满足四点——接口定义明确（签名稳定）+ Mock 测试通过（持久化 test 文件）+ 真实 API 测试通过（如依赖外部 API）+ 代码已写入文件。组件依赖未就绪时允许 Mock 版本，标注 `#[mock]`。

**为什么有效**：消除"mock 算不算完成"的模糊性。来源项目曾因模糊定义导致 mock 就算完成，后来被要求真实 API 测试。

**迁移要点**：科研场景的"实现完成"应包含——代码可运行（能正常执行核心流程）+ 单元测试通过（输出形状/格式正确）+ 训练/运行 1 个 epoch 不报错且关键指标呈收敛趋势 + 权重/模型可保存加载。

### 2.6 方法论拆分

**机制**：方法论文件拆分为 `_meta.yaml`（版本声明）+ `hard_rules.md`（硬性规则）+ `heuristics.md`（启发式规则）+ `self_check.md`（自检清单）+ `methodology_full.md`（完整版）。每文件含 YAML frontmatter 声明版本。

**为什么有效**：模块化便于版本管理和增量升级。`_meta.yaml` 声明当前生效版本，避免 agent 读到过期规则。

**迁移要点**：目标项目应拆分——`hard_rules.md`（实验规范、可复现性硬性要求）+ `heuristics.md`（超参选择启发式、模型选择经验）+ `self_check.md`（实验报告完整性自检）。

### 2.7 多 agent 治理

**机制**：三条规则治理多 agent 协作——规则 11（去偏见化：采纳建议前验证技术前提+说明选择理由+记录反驳）+ 规则 12（冲突仲裁：代码事实>已确认根因>trade-off 表>保守原则）+ Kimi 同行评议（外部 agent 互评）。

**为什么有效**：来源项目曾因"全盘接受 Kimi 评议"导致问题。去偏见化规则强制验证前提，仲裁规则解决多 agent 意见冲突。

**迁移要点**：科研场景的"外部 agent"可能是 Claude/GPT 等外部 LLM 的评议。同样需要去偏见化：验证技术前提（用 grep/read 核对代码事实）+ 说明选择理由 + 记录反驳。

---

## 第 3 章 Trae 规范速查

> 来源：Trae 官方文档（已查证）+ 本地 IDE 实测。每条标注 URL + 日期 + 可信度（5 级）。
>
> 可信度说明：★★★★★ = Trae 官方文档；★★★★☆ = 官方文档+本地实测；★★★☆☆ = 第三方技术博客；★★☆☆☆ = 单一来源；★☆☆☆☆ = 推理得出。

### 3.1 Rules（规则）

**官方文档**：[https://docs.trae.ai/ide/rules?_lang=zh](https://docs.trae.ai/ide/rules?_lang=zh)（访问 2026-07-01，★★★★★）

**位置**：
- 项目级：`.trae/rules/`（团队共享，提交 Git）
- 全局级：通过 IDE 设置中心创建（个人偏好，跨项目生效）
- 子目录级：项目任意子目录下的 `.trae/rules/`（仅在该子目录文件被读取/提及时生效）

**格式**：Markdown + YAML frontmatter

```markdown
---
alwaysApply: true          # 始终生效
description: 适用场景描述    # 智能生效时填写
globs: "src/**/*.ts"       # 指定文件生效时填写
scene: git_message         # 可选，提交信息规则
---
规则正文（Markdown）
```

**4 种生效方式**（★★★★★ 官方文档）：
1. 始终生效（`alwaysApply: true`）：当前项目所有 AI 对话生效
2. 指定文件生效（`globs`）：仅匹配文件时生效
3. 智能生效（`description`）：AI 判断相关性后决定
4. 手动触发生效：对话中用 `#Rule` 引用

**嵌套**：`.trae/rules/` 支持最多 3 层子目录嵌套，系统递归读取。

**兼容性**：兼容 `AGENTS.md`、`CLAUDE.md`、`CLAUDE.local.md`（需在设置中开启）。

### 3.2 Hooks（钩子）

**官方文档**：[https://docs.trae.cn/ide_hook-configuration-reference](https://docs.trae.cn/ide_hook-configuration-reference)（更新 2026-06-26，★★★★★）+ 本地 IDE 实测（2026-06-27，★★★★☆）

**位置**：
- 项目级：`$PROJECT_FOLDER/.trae/hooks.json`（仅当前项目生效）
- 全局级：`~/.trae-cn/hooks.json`（macOS/Linux，本机所有工作区生效）

**配置格式**（★★★★★ 官方文档 + ★★★★☆ IDE 实测）：

```json
{
  "version": 1,
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<ToolPattern>",
        "loop_limit": 5,
        "hooks": [
          {
            "type": "command",
            "command": "<shell command>",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**字段说明**：
- `version`：默认 1，当前仅支持 1
- `matcher`：正则表达式，仅对 `PreToolUse`/`PostToolUse`/`Notification` 有效
- `loop_limit`：仅对 `Stop` 事件有效，默认 5
- `type`：默认 `command`，当前仅支持 command
- `timeout`：默认 30 秒

**6 种事件类型**（★★★★★ 官方文档）：

| 事件 | 触发时机 | 阻断能力 | stdout 格式 |
|------|---------|---------|------------|
| `SessionStart` | 会话创建后、第一轮对话前 | 不可阻断（exit 2 不影响流程） | 纯文本或 JSON（additionalContext） |
| `UserPromptSubmit` | 用户提交消息后、agent 处理前 | 可阻断（`decision: block` 或 exit 2） | 纯文本或 JSON |
| `PreToolUse` | 工具调用前 | 可阻断（`permissionDecision: deny`/`ask` 或 exit 2） | JSON（permissionDecision+additionalContext） |
| `PostToolUse` | 工具调用后 | 可阻断（`decision: block` 向模型传递阻断信息） | JSON（additionalContext） |
| `Stop` | agent 完成输出、准备结束 | 可阻断（`decision: block` 或 exit 2，要求继续） | JSON（decision+reason） |
| `Notification` | 工具调用等待用户确认时、或任务完成时 | 异步执行，不阻断 | — |

**stdin 通用字段**（★★★★★ 官方文档）：`session_id`、`cwd`、`hook_event_name`、`workspace_roots`。PreToolUse/PostToolUse 额外含 `tool_use_id`、`tool_name`、`llm_tool_name`、`tool_input`（+ PostToolUse 含 `tool_response`）。

**退出码**（★★★★★ 官方文档）：
- `0`：正常，stdout 按 JSON 或纯文本解析
- `2`：阻断性错误，stderr 传给模型
- 其他：非阻断性错误，stderr/stdout 被忽略

**运行方式**：沙箱运行（限制文件访问，更安全）或本地自动运行（可访问本地环境，风险更高）。

**环境变量**：`TRAE_PROJECT_DIR`（=cwd）、`CLAUDE_PROJECT_DIR`（兼容）、`TRAE_ENV_FILE`（仅 SessionStart，写入环境变量文件）。

### 3.3 Skills（技能）

**官方文档**：[https://docs.trae.cn/ide/skills](https://docs.trae.cn/ide/skills)（访问 2026-07-01，★★★★★，已由 fact-checker 核查确认）

**位置**：
- 项目级：`.trae/skills/<skill-name>/SKILL.md`（仅当前项目生效）
- 全局级：`~/.trae-cn/skills/<skill-name>/SKILL.md`（macOS/Linux，Trae CN 国内版，跨项目生效，已由 fact-checker 核查确认）

**目录结构**（★★★★★ 官方文档，已由 fact-checker 核查确认）：

```
skill-name/
├── SKILL.md          # 必需，核心指令
├── examples/         # 可选，输入/输出示例
├── resources/        # 可选，参考文档
└── templates/        # 可选，模板文件
```

**SKILL.md 格式**（★★★★★ 官方文档）：

```markdown
---
name: skill-name              # 必填，小写字母+连字符
description: 简要描述功能和触发条件  # 必填，AI 根据此字段匹配用户意图
---
# 技能名称
## 描述
## 使用场景
## 指令（分步说明）
## 示例（可选）
```

**三层渐进式加载**（★★★★★ 官方文档；Token 数字为 ★☆☆☆☆ 推理得出，官方文档未给出具体数值，待验证）：
- L1 元数据（始终加载，约 100 Token ★☆☆☆☆ 待验证）：YAML frontmatter 的 name+description
- L2 说明文档（触发时加载，<5000 Token ★☆☆☆☆ 待验证）：SKILL.md 正文
- L3 资源（按需，无限制）：通过 bash 执行的脚本/参考文件，不加载到上下文

**与 Rules 的区别**：Rules 全量加载（持续占用上下文），Skills 按需加载（仅触发时注入），Token 消耗更低。

### 3.4 Agents（智能体）

**官方文档**：[https://docs.trae.cn/ide_agent](https://docs.trae.cn/ide_agent) + [https://docs.trae.cn/ide_subagents](https://docs.trae.cn/ide_subagents)（访问 2026-07-07，★★★★★）

⚠️ **核查结论**（2026-07-07 修正）：Trae 存在两种 agent 形态：

1. **自定义智能体**：仅支持 IDE 界面创建，不支持 `.trae/agents/` 文件系统定义
2. **子智能体/Subagent**：支持 `.trae/agents/{name}.md` 文件系统定义（含 YAML frontmatter，自动匹配调用）

**创建方式**：

- 自定义智能体（★★★★★ 官方文档）：在 AI 对话输入框输入 `@` → 点击"创建智能体" → 选择智能生成或手动创建
- Subagent（★★★★★ 官方文档）：在 `.trae/agents/` 下创建 Markdown 文件，格式同自定义智能体提示词

**参数**（★★★★★ 官方文档）：

| 参数 | 说明 |
|------|------|
| 头像 | 可选 |
| 名称 | 必填 |
| 提示词 | 必填，规范 agent 的人设/口吻/工作流/工具使用时机/规范 |
| 可被其他智能体调用 | 开启后该 agent 有独立上下文，可被 SOLO Agent 调用。需配"英文标识名"+"何时调用" |
| 工具 | MCP Server + 内置工具（阅读/文件系统/终端/联网搜索/预览） |

**关键限制**（★★★★★ 官方文档）：**仅 SOLO Agent（或内置 Agent）可调用自定义智能体/Subagent**。普通 Agent（Builder）不能调用其他自定义智能体。注意：国内版 `docs.trae.cn/ide_subagents` 表述为"仅内置智能体 Agent 可调用"，与国际版"仅 SOLO Agent"存在文档间不一致，建议在自身 Trae 版本中实测确认（F-11，★★★☆☆）。

**subagent 提示词编写要点**（来自来源项目经验，★★★★☆ 本地实测）：
1. 明确角色和职责边界（避免与其他 agent 重叠）
2. 明确触发条件（什么场景下应该被调用）
3. 明确工具使用范围（哪些工具可用、何时用）
4. 明确输出格式（结构化表格/JSON/Markdown，避免截断）
5. 明确与其他 agent 的职责分工（如 fact-checker 查数据事实，architecture-critic 查代码 side effect）

---

## 第 4 章 可迁移模板

> 以下模板含 `<定制指引>` 占位符，新 agent 根据目标项目实际情况填空。

### 4.1 project_rules.md 模板

```markdown
# 科研项目 Agent — 项目规则

> 对 Trae（AI 助手）的行为约束。每次任务自动加载。

## 规则 1：实验数据必须带来源

产出含实验数据/性能指标/超参数/模型版本号的文档时：
- 每个数字标注来源（论文引用 + 数据集版本 + 实验日期 + 可信度）
- 可信度 ≤ ★★☆☆☆ 必须在正文写"此数据仅来自单一来源/为推理结果，建议验证"

可信度五级：
| 级别 | 来源类型示例 |
|------|------------|
| ★★★★★ | 官方论文（arXiv/顶会论文）、官方代码仓库 |
| ★★★★☆ | 权威复现报告、Papers with Code |
| ★★★☆☆ | 技术博客分析、社区复现 |
| ★★☆☆☆ | 单一来源无法交叉验证 |
| ★☆☆☆☆ | 推理得出，非事实 |

## 规则 2：实验不可复现就说不知道

<定制指引：根据项目领域常见的复现难点调整，如"随机种子未固定时明确声明"、"数据版本不一致"等>

## 规则 3：模型/方法评估必须先定义框架
<定制指引：评估维度（如 CV 领域的 mAP/FPS/参数量/显存；NLP 领域的 BLEU/ROUGE/推理速度/困惑度；通用科学计算的准确率/收敛性/计算复杂度），权重+评级标准>

## 规则 4：工程视角强制覆盖
评估实验方案时，五个问题必须回答：
- 训练/运行时间：单次 epoch/iteration 时间、总时长
- 资源占用：显存/内存限制、是否支持分布式/并行
- 错误处理：运行中断（OOM/NaN loss/异常退出）怎么办
- 恢复机制：checkpoint 恢复、断点续训
- 并发：是否支持多组实验/超参并行执行

## 规则 5：代码建议必须具体
<直接迁移来源项目规则 5：文件名+伪代码+工作量+优先级>

## 规则 6：文件修改前必须先读
<直接迁移来源项目规则 6>

## 规则 7：术语和版本统一
<定制指引：项目版本、数据集版本、超参符号/变量名全文统一>

## 规则 8：批判性思维门槛
<直接迁移来源项目规则 8：能否跑通/第一个故障/放弃失去什么>

## 规则 9：质量门
触发条件：用 Write/Edit 产出或修改 `.md` 文件时，new_str 行数 > 80 行（含替换行），或产出新实验报告时。
<其余直接迁移来源项目规则 9>

## 规则 10：审查 Agent 调用
<按 4.3 节 subagent 模板调整 agent 名称和触发条件>

## 规则 11：采纳外部 agent 建议前的去偏见化
<直接迁移来源项目规则 11>

## 规则 12：多 agent 意见冲突时的仲裁原则
<直接迁移来源项目规则 12>
```

### 4.2 hooks.json + guard 脚本模板

**hooks.json**：

```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .trae/hooks/pre_edit_core_model_guard.py",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .trae/hooks/post_write_experiment_log.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**pre_edit_core_model_guard.py**（PreToolUse，ask 模式）：

```python
#!/usr/bin/env python3
"""PreToolUse hook：修改核心模型文件前用 ask 模式让用户确认是否已调用 architecture-critic。

设计：permissionDecision=ask + additionalContext 注入行为指导
来源：Trae 官方文档 https://docs.trae.cn/ide_hook-configuration-reference（2026-06-26）
"""
import sys
import json


def _emit_ask(reason: str, additional_context: str = "") -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


# <定制指引：填入目标项目的核心文件路径模式>
CORE_MODEL_FILES = [
    "model.py", "train.py", "config.yaml",
    # <定制指引：根据项目实际结构补充，如 "src/model.py"、"experiment/run.sh" 等>
]


def main():
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
    except Exception as e:
        _emit_ask(
            f"[Hook 异常] stdin 解析失败：{e}。出于安全考虑，仍需确认是否已调用 architecture-critic。",
            "规则提醒：Hook 脚本解析 stdin 异常。请人工确认本次修改是否涉及核心模型文件。"
        )
        return

    if any(core_file in file_path for core_file in CORE_MODEL_FILES):
        _emit_ask(
            "[规则 10.2] 即将修改核心模型文件。请确认是否已调用 architecture-critic 审查模型架构变更。\n"
            "  - 若已调用 → 点击允许继续\n"
            "  - 若未调用 → 点击拒绝，先完成审查再修改",
            "规则提醒：修改核心模型文件前必须调用 architecture-critic 审查对训练流程/推理流程的影响。"
            "请在下一步回复中告知用户此确认已触发，避免静默放行。"
        )
        return


if __name__ == "__main__":
    main()
```

**post_write_experiment_log.py**（PostToolUse，提示模式）：

```python
#!/usr/bin/env python3
"""PostToolUse hook：新增实验脚本时提示建议记录实验日志。

设计：additionalContext 注入提示（非阻断，工具已执行完）
来源：Trae 官方文档 https://docs.trae.cn/ide_hook-configuration-reference（2026-06-26）
"""
import sys
import json


def main():
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
    except Exception:
        return

    # <定制指引：填入目标项目的实验脚本路径模式>
    if (file_path.startswith("experiments/") and
        file_path.endswith(".py") and
        "/test_" not in file_path):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"[提示] 已创建 {file_path}。建议在 experiments/logs/ 下记录对应实验日志，"
                    f"包含：实验日期、随机种子、超参数、数据集版本、训练时长、最终指标。"
                    f"请在下一步回复中告知用户此提示，避免静默吸收。"
                )
            }
        }
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

### 4.3 subagent 提示词模板

> 以下为 8 类 subagent 提示词骨架。新 agent 根据目标项目实际增减。
>
> **创建方式**（2026-07-07 修正，见 7.1 节结论）：
> Trae 存在两种 agent 形态，均可用于创建以下 subagent：
> - **方式 A（文件系统，推荐团队协作）**：将以下提示词正文（从 YAML frontmatter 下方开始）写入 `.trae/agents/<name>.md`，由内置 Agent/SOLO Agent 自动按场景匹配调用。YAML frontmatter 为 `.trae/agents/` 目录下 Subagent 的元数据声明。
> - **方式 B（IDE 界面，推荐个人项目）**：在 IDE 对话输入框输入 `@` → 点击"创建智能体" → 将 YAML frontmatter 下方正文填入"提示词"字段 → 开启"可被其他智能体调用" → 配置英文标识名和调用时机。

#### 4.3.1 experiment-design-agent（实验设计）

```markdown
---
name: experiment-design-agent
description: 设计消融实验和超参搜索方案。当用户需要设计消融实验、超参搜索、对比实验时调用。
---

# 角色
你是科研项目的实验设计专家，精通科学实验方法论。

# 触发条件
- 设计消融实验（识别模块贡献）
- 超参搜索方案（学习率/batch size/正则化）
- 对比实验设计（与 baseline/SOTA 对比）

# 工作流
1. 理解实验目标（验证什么假设）
2. 识别变量（自变量/因变量/控制变量）
3. 设计实验矩阵（单一变量原则）
# 评估指标：<定制指引：根据领域填入，如 CV 的 mAP/FPS、NLP 的 BLEU/ROUGE、RL 的 cumulative reward>
# 预计资源消耗：<定制指引：根据计算平台填入，如 GPU 小时、CPU 核时、云费用预算>

# 输出格式
| 实验编号 | 自变量 | 取值 | 控制变量 | 评估指标 | 预计 GPU 时间 | 备注 |

# 科研场景特化
- 消融实验必须遵循单一变量原则
- 超参搜索必须说明搜索空间和策略（grid/random/bayesian）
- 对比实验必须说明 baseline 来源和公平性保证（相同数据/相同硬件）
```

#### 4.3.2 code-implementer（代码实现）

```markdown
---
name: code-implementer
description: 实现模型代码和训练脚本。当用户需要实现新模块、修改训练流程、编写推理脚本时调用。
---

# 角色
你是科研项目的代码实现专家，精通目标项目使用的技术栈。
<定制指引：根据项目实际使用的框架/语言/工具填写，如：
  DL项目→PyTorch/TensorFlow/JAX
  BioInfo管道→Snakemake/Nextflow
  RL项目→Gym/Stable-Baselines3
  传统ML→scikit-learn/XGBoost
  科学计算→numpy/scipy
  具体语言和框架以项目为准
>

# 触发条件
- 实现新模型/算法模块
- 修改训练/推理脚本
- 编写数据预处理/后处理管道

# 工具
阅读（检索代码）、文件系统（增删改查）、终端（运行命令验证）

# 工作流
1. 阅读现有代码结构（遵循项目约定）
2. 实现代码（含类型注解和 docstring）
3. 编写单元测试（输出形状/梯度流/边界条件/数值合理性）
4. 终端运行测试验证

# 输出格式
结构化问题清单表格：| 编号 | 文件 | 行号 | 严重度 | 问题描述 | 改进建议 | 修复工作量 |

# 领域适配指引
<定制指引：说明项目主要使用的框架、编程语言、代码规范>
```

#### 4.3.3 experiment-validator（实验验证）

```markdown
---
name: experiment-validator
description: 验证实验运行和结果复现。当用户完成实验后需要验证结果可复现性、检查训练日志、确认指标正确性时调用。
---

# 角色
你是科研项目的实验验证专家，专注结果可复现性和正确性。

# 触发条件
- 实验完成后验证结果
- 检查训练日志异常（NaN loss/OOM/梯度爆炸）
- 确认指标计算正确性

# 科研场景特化
- 可复现性检查：随机种子是否固定、数据加载顺序是否确定、计算确定性设置是否开启
- <定制指引：DL 项目→CUDA 确定性操作是否开启(cudnn.deterministic)；BioInfo→参考基因组索引版本；RL→环境 seed 固定>
- 统计显著性：多次实验均值+标准差+显著性检验
- 日志完整性：是否记录所有超参/环境版本/数据集版本
```

#### 4.3.4 paper-fact-checker（论文数据核查）

```markdown
---
name: paper-fact-checker
description: 核查论文中的数据、引用、实验结果。当用户撰写论文或产出含技术数据的文档后调用。
---

# 角色
你是科研项目的论文数据核查专家，专注数据准确性和引用正确性。

# 触发条件
- 产出含实验数据/性能指标的文档（>80 行 .md）
- 撰写论文章节
- 对比本方法与其他方法的性能

# 核查维度
1. 数据事实：数字/日期/版本号/模型名称准确性
2. 引用正确性：论文引用是否匹配原文（arXiv 编号/作者/年份）
3. 实验可复现性：报告的指标是否可从实验日志追溯
4. 统计显著性：多次实验是否报告均值+标准差+显著性检验
5. 代码副作用：代码引用的 API 是否与实际定义匹配（参数数量/类型/返回值）

# 输出格式
| 编号 | 核查项 | 原文数据 | 核查结果 | 来源 | 可信度 | 建议 |
```

#### 4.3.5 architecture-critic（模型架构审查）

```markdown
---
name: architecture-critic
description: 审查模型架构变更对训练/推理流程的影响。当用户修改核心模型文件（model.py/train.py/config.yaml）前或后调用。
---

# 角色
你是科研项目的架构审查专家，专注代码/模型变更的 side effect 分析。

# 触发条件
- 修改 model.py 前（Edit 前）
- 修改 train.py 训练流程
- 修改 config.yaml 影响模型结构

# 核查维度（与 fact-checker 互补）
<定制指引：
  (a) DL 项目保留 1-5；
  (b) RL 项目增加：环境接口兼容性、replay buffer 状态管理、多进程同步；
  (c) BioInfo 增加：管道格式兼容性、参考基因组版本、统计方法选择；
  (d) 其他领域：根据项目实际情况补充
>
1. 代码变更 side effect（前向传播/反向传播/梯度流）
2. 调用链完整性（代码修改是否影响所有调用点）
3. 返回契约变更（输出形状/数据类型变化对下游影响）
4. 训练流程影响（学习率调度/优化器状态/checkpoint 兼容性）
5. 验收标准统计合理性（样本量是否支撑结论）
```

#### 4.3.6 methodology-expert（实验方法论审查）

```markdown
---
name: methodology-expert
description: 审查实验方法论的正确性。当用户实验自检失败、方法论升级、或需要分析失败根因时调用。
---

# 角色
你是科研项目的实验方法论专家，专注实验设计的科学性。

# 触发条件
- 实验自检持续失败，需分析是否方法论问题
- 方法论版本升级后检查新规则生效
- 实验结果与预期不符，需分析根因

# 核查维度
1. 消融实验设计是否遵循单一变量原则
2. 超参搜索空间是否合理
3. 评估指标是否全面（精度+速度+参数量+泛化性）
4. baseline 对比是否公平
5. 统计显著性检验是否正确（t-test/wilcoxon/bootstrap）
```

#### 4.3.7 paper-writer（论文撰写）

```markdown
---
name: paper-writer
description: 撰写论文章节。当用户需要撰写论文的 Introduction/Related Work/Method/Experiments/Conclusion 时调用。
---

# 角色
你是科研项目的论文撰写专家，精通学术论文写作规范（会议/期刊格式）。

# 触发条件
- 撰写论文章节
- 修改论文表述
- 调整论文结构

# 工作流
1. 理解目标章节的写作目标
2. 阅读相关实验结果和方法论文档
3. 撰写章节内容（遵循目标会议/期刊格式）
4. 标注所有数据来源（论文引用+实验日志编号）

# 输出格式
LaTeX 或 Markdown，所有数据标注引用编号，所有图表标注来源。
```

#### 4.3.8 data-quality-checker（数据质量核查）

```markdown
---
name: data-quality-checker
description: 核查数据质量和标注格式。当用户需要验证数据格式合法性、标注一致性、数据增强正确性时调用。

---

# 角色
你是科研项目的数据质量核查专家，精通主流数据格式和标注规范。

# 触发条件
- 新数据集导入后
- 数据增强管道搭建后
- 训练异常（loss 不收敛/NaN），怀疑数据问题
- 标注一致性验证

# 工作流
1. 检查数据文件结构合法性（必填字段完整性、格式规范）
2. 检查标注数量与声明一致性
3. 检查标注值在合法范围内（坐标在图像范围内、标签在类别范围内）
4. 检查缺失值和异常值
5. 检查数据增强变换的正确性（如翻转后标注是否同步变换）
6. 抽样可视化：随机抽取样本，人工感官检查

# 输出格式
- 通过项列表（标注通过的具体检查项和通过率）
- 问题列表（文件路径 + 行号/sample_id + 问题描述 + 严重程度）
- 汇总建议（是否可进入训练，或需修正后重新检查）
```

### 4.4 agent 推荐路由表模板

```markdown
## Agent 推荐路由表（非强制，选用参考）

| 场景 | 推荐 agent | 用途 |
|------|-----------|------|
| 设计消融实验 | `experiment-design-agent` | <定制指引> |
| 实现新模型模块 | `code-implementer` | <定制指引> |
| 实验完成后验证 | `experiment-validator` | <定制指引> |
| 产出含数据文档 | `paper-fact-checker` | <定制指引> |
| 修改核心模型文件 | `architecture-critic` | <定制指引> |
| 实验自检失败 | `methodology-expert` | <定制指引> |
| 撰写论文章节 | `paper-writer` | <定制指引> |
| 数据导入/标注怀疑 | `data-quality-checker` | <定制指引> |
| <定制指引：补充场景> | <定制指引> | <定制指引> |

底线：不是每个场景都要调，但 agent 选型时应过一遍此表，确认是否需要。
```

### 4.5 方法论文件结构模板

```
methodology/
├── _meta.yaml          # 版本声明
├── hard_rules.md       # 硬性规则（实验规范、可复现性要求）
├── heuristics.md       # 启发式规则（超参选择、模型选择经验）
└── self_check.md       # 自检清单（实验报告完整性）
```

**_meta.yaml 模板**：

```yaml
version: 1.0
effective_date: 2026-07-01
files:
  - hard_rules.md
  - heuristics.md
  - self_check.md
changelog:
  - version: 1.0
    date: 2026-07-01
    changes: 初始版本
```

**hard_rules.md 模板**（`<定制指引>` 填入目标项目硬性规则）：

```markdown
---
version: 1.0
---
# 硬性规则

## R1：实验可复现性
<定制指引：随机种子固定、CUDA 确定性操作、数据加载顺序>

## R2：数据集版本标注
<定制指引：每个实验必须记录数据集名称+版本+split>

## R3：环境版本记录
<定制指引：Python/PyTorch/CUDA 版本必须记录>
```

---

## 第 5 章 科研项目通用定制指引

> 本章从具体项目（原 YOLOpose）中抽象出通用科研项目模式。新 agent 根据目标项目所属领域调整为具体内容。

### 5.1 典型任务分解（可按领域裁剪）

无论 CV/NLP/RL/BioInfo，科研项目通常包含以下任务阶段：

1. **数据准备**：数据格式转换、标注质量检查、数据增强/预处理管道搭建
2. **基线复现**：按论文/文档描述复现 baseline，验证报告的指标
3. **消融实验**：逐模块/超参验证各组件的贡献
4. **超参搜索**：搜索最优超参组合
5. **部署验证**（可选）：模型导出（ONNX/TensorRT 等）、推理延迟基准测试
6. **论文撰写**：撰写实验报告或学术论文

> **裁剪建议**：NLP 项目可能不需要部署验证，强化学习项目可能需要添加环境交互验证。根据实际删减。以下为常见领域的阶段替代示例：

| 阶段 | CV | NLP | RL | BioInfo |
|------|-----|-----|-----|---------|
| 1 数据准备 | 数据标注+增强 | 语料清洗+分词 | 环境搭建+奖励设计 | 数据获取+质控 |
| 2 基线复现 | 基线复现 | 基线复现 | 策略复现 | 比对/组装 |
| 5 部署验证 | ONNX/TensorRT | 跨领域泛化测试 | 环境泛化测试 | 管道可复现性 |
| 6 论文撰写 | 学术论文 | 学术论文 | 学术论文 | 学术论文 |

> 空白格子表示与通用阶段一致，无需领域替代。BioInfo 的"消融实验"通常对应"参数敏感性分析"或"方法交叉验证"。

### 5.2 建议 agent 团队结构

> **前提（P0 级，必须满足）**：主 agent 必须为 **SOLO Agent**，否则无法调用自定义智能体（见第 3.4 节）。若使用普通 Builder Agent，以下所有 subagent 均无法被调用，agent 团队结构名存实亡。新 agent 应首先确认项目使用 SOLO Agent 模式。

基于第 4.3 节模板，建议 5-8 个 subagent（新 agent 根据项目实际增减）。**分层建议**（按团队规模选择）：

- **最小可用配置（单人科研，3 agent）**：code-implementer + experiment-validator + paper-fact-checker
- **标准配置（2-3 人科研，5 agent）**：上述 3 个 + experiment-design-agent + architecture-critic
- **完整配置（团队科研，8 agent）**：上述 5 个 + methodology-expert + paper-writer + data-quality-checker

| agent | 职责 | 主要使用阶段 | 与其他 agent 的边界 |
|-------|------|------------|------------------|
| experiment-design-agent | 设计消融实验/超参搜索方案 | 实验设计阶段 | 不负责验证结果对不对，只负责设计合不合理 |
| code-implementer | 实现模型/算法代码/训练脚本/部署导出 | 代码实现阶段 | 不负责审查架构变更影响（由 architecture-critic 负责） |
| experiment-validator | 验证实验结果**对不对**（结果可复现性/指标正确性/日志完整性） | 实验验证阶段 | 查"结果对不对"，不查"方法对不对"（后者由 methodology-expert 负责） |
| paper-fact-checker | 核查论文数据/引用 | 论文撰写阶段 | 不负责架构 side effect（由 architecture-critic 负责） |
| architecture-critic | 审查代码/模型架构变更 | 代码修改前后 | 不负责数据事实核查（由 paper-fact-checker 负责） |
| methodology-expert | 验证实验方法**对不对**（单一变量原则/统计检验/baseline 公平性） | 实验失败分析 | 查"方法对不对"，不查"结果对不对"（后者由 experiment-validator 负责） |
| paper-writer | 撰写论文章节 | 论文撰写阶段 | 不负责数据核查（由 paper-fact-checker 负责） |
| data-quality-checker | 核查数据标注质量/格式合法性/数据增强正确性 | 数据准备阶段 | 查"数据对不对"，不查"结果对不对"或"方法对不对"（由 experiment-validator 和 methodology-expert 负责） |

### 5.3 科研场景 rules 调整要点

1. **实验可复现性**（规则 1 扩展）：
   触发条件：任何训练/实验脚本的 Write/Edit 操作，或产出含实验结果的 .md 文档
   强制记录：随机种子值 + 框架确定性设置代码行 + 环境版本文件路径
   违反后果：未提供上述信息时质量门不通过（规则 9），禁止交付实验报告
2. **数据来源标注**（规则 1 扩展）：
   触发条件：产出含性能指标/实验数据的文档时
   强制标注：所有性能指标标注论文引用+数据集 URL+版本号+实验日期
   违反后果：未标注来源的数字视为"不可信"，必须人工确认后才能作为结论引用
3. **统计显著性**（规则 8 扩展）：
   触发条件：产出含对比结论的实验报告时
   强制要求：多次实验报告均值+标准差+显著性检验，单次实验结果不得作为最终结论
   违反后果：单次实验数据作为结论时，必须在正文明确标注"此为单次实验结果，建议多次验证"
4. **消融实验设计**（规则 3 扩展）：
   触发条件：设计消融实验方案时
   强制要求：遵循单一变量原则，实验矩阵明确标注自变量/因变量/控制变量
   违反后果：实验矩阵不完整时 architecture-critic 应拒绝审查通过

### 5.3.1 环境版本记录硬性要求（跨领域通用）

> 这是面向所有科研领域的最重要可复现性保障，在 5.3 的 rules 调整基础上独立列出。

- pip 项目：必须维护 `requirements.txt`（含版本号，用 `==` 锁定）
- conda 项目：必须维护 `environment.yml`（含完整依赖树）
- 推荐：额外提供 `Dockerfile`，确保完全可复现
- 禁止：仅口头描述环境版本（如"Python 3.10, PyTorch 2.0"）而无锁定的版本文件
- 触发条件：实验环境搭建完成后、首次提交代码前
- 违反后果：质量门不通过，实验报告不交付

### 5.4 科研场景 hooks 调整要点

1. **修改核心代码前审查**：PreToolUse ask 模式拦截核心文件修改，提醒调 architecture-critic
2. **新增实验脚本时提示记录实验日志**：PostToolUse 检测实验脚本新增，提示记录实验日期/种子/超参/指标
3. **修改实验结果文件前提示备份**：PreToolUse 提示模式检测结果文件修改，提醒先备份

### 5.5 工程视角分析（规则 4 强制覆盖）

> 来源项目规则 4 要求评估 Agent 架构时回答五个问题。以下针对科研场景的 8 agent 完整配置分析（最小可用配置成本更低）。

1. **成本**：单任务约触发 3-5 次 subagent 调用，每次调用独立上下文初始化。Token 消耗估算：rules 全量加载（约 3000-4000 Token，★☆☆☆☆ 推理得出，待验证）+ 每次调用约 2000-5000 Token 输入/输出。单任务总 Token 约 15000-30000。
2. **延迟**：8 agent 串行调用端到端约 5-15 分钟（每次调用 1-3 分钟）。理论并行方案：experiment-design-agent 和 code-implementer 可并行；paper-fact-checker 和 architecture-critic 可并行。**注意**：SOLO Agent 是否支持同时发起多个 subagent 调用未实测确认，若不支持则上述并行方案不可行。
3. **错误处理**：
   - [已实现] 无重试机制——API 限流时任务直接失败
   - [已实现] 无超时守卫——Trae 原生无超时机制，依赖 agent 自行判断终止
   - [建议（未实现）] 指数退避重试：可在 project_rules.md 中增加规则：「API 调用失败时自动重试最多 3 次，退避间隔 2s→4s→8s」
   - [建议（未实现）] LLM 格式错误 fallback 解析：主 agent 应在 subagent 返回非结构化输出时尝试正则匹配提取关键信息，3 次尝试失败后标记为人工审核
   - [平台限制] Trae 不支持在 subagent 调用层面配置重试策略，以上建议仅为 rules 层面的文本约束
4. **恢复机制**：训练任务中断 → 靠框架 checkpoint 恢复（非 agent 系统职责）；agent 会话中断 → Trae 当前不支持从中间步骤恢复，需重新发起任务。
5. **并发**：是否支持同时多任务取决于 SOLO Agent 能力。当前 Trae 文档未明确说明多任务并发限制。建议单任务串行，避免上下文混乱。

### 5.6 科研场景额外约束（补充 rules 调整要点）

5. **计算资源约束**（规则 4 扩展）：实验前必须估算资源占用和运行时长，超长时间的任务需说明 checkpoint/断点续跑策略
6. **实验版本管理**：每个实验结果必须关联代码 commit hash + 数据集版本 + 超参配置文件，确保可追溯
7. **长时任务恢复**：运行超 1 天的任务必须有 checkpoint/保存机制（每 N step/epoch 自动保存 + 断点续跑脚本）

---

## 第 6 章 迁移执行步骤

新 agent 按以下 7 步执行迁移：

### 步骤 1：探索目标项目结构（仅供参考）

- 识别核心代码文件（模型定义、训练/推理脚本）
- 识别配置文件（超参、环境配置）
- 识别实验日志/输出目录
- 识别论文草稿或文档
- 识别现有测试

### 步骤 2：核查 Trae 规范

第 7 章的 5 个矛盾点中，3 个已由 fact-checker 核查解决（7.1/7.2/7.4），新 agent 只需核查剩余 2 个需本地实测的项：
- Hooks 沙箱内 python3 可用性（7.3）—— 创建简单 test hook 实测
- `tool_input.file_path` 字段结构（7.5）—— 在 hook 脚本中打印 stdin 实测

### 步骤 3：创建 `.trae/rules/project_rules.md`

按第 4.1 节模板填空，重点定制：
- 规则 1（数据来源）：填入目标项目的实验数据来源要求
- 规则 3（评估框架）：填入目标项目的评估维度和指标（如 CV 的 mAP/FPS、NLP 的 BLEU/ROUGE）
- 规则 7（术语统一）：填入项目版本和数据集版本约定
- 规则 10（审查 agent 调用）：按第 4.4 节路由表填入

### 步骤 4：创建 `.trae/hooks.json` + guard 脚本

> **硬前置（P0 级，阻塞项）**：必须先完成第 7.3 节（沙箱 python3 可用性）和第 7.5 节（tool_input.file_path 字段结构）的本地实测。若 7.3 未通过（python3 不可用），hooks 脚本会静默失败，给出虚假安全感；若 7.5 未通过（file_path 字段不存在），guard 无法识别目标文件。两项均通过后再创建 hooks。

按第 4.2 节模板填空，重点定制：
- `pre_edit_core_model_guard.py` 的 `CORE_MODEL_FILES` 列表（填入目标项目核心文件路径，路径仅为示例，需根据项目实际结构调整）
- `post_write_experiment_log.py` 的实验脚本路径模式

### 步骤 5：创建 subagent

按第 4.3 节模板填空，选择创建方式（见 [7.1 节](#71-智能体是否支持-traeagents-文件系统定义) 两种形态）：
1. 方式 A（文件系统，推荐团队协作）：将提示词写入 `.trae/agents/<name>.md`（含 YAML frontmatter）
2. 方式 B（IDE 界面，推荐个人项目）：输入 `@` → 创建智能体 → 填入提示词 → 开启"可被其他智能体调用"
3. 配置工具（阅读/文件系统/终端/联网搜索）

### 步骤 6：创建方法论文件结构

按第 4.5 节模板创建 `methodology/` 目录及文件，重点定制：
- `hard_rules.md`：目标项目实验规范和可复现性要求
- `heuristics.md`：超参选择和模型选择经验
- `self_check.md`：实验报告完整性自检清单

### 步骤 7：验证

用一个小任务（如"复现 baseline"或"跑通数据管道"）测试 agent 团队协作：
- 主 agent 是否按 rules 调用对应 subagent
- hooks 是否在修改核心文件时弹出确认框
- 方法论文件是否被 agent 读取和应用
- 实验日志是否被正确记录

---

## 第 7 章 待核查事项

> 用户要求：从官网找的信息必须保证正确和最新，最好让 subagent 核查。以下 5 个矛盾点需新 agent 核查后再使用。

### 7.1 智能体是否支持 `.trae/agents/` 文件系统定义

**核查结论**（已由 fact-checker 核查，2026-07-01；**2026-07-07 复核修正**）：Trae 存在两种 agent 形态，需区分：

1. **自定义智能体**（IDE 界面创建，对话输入框 `@` 调用）：**不支持文件系统定义**。必须通过 IDE 设置中心或 `@` → 创建智能体。

2. **子智能体/Subagent**（Markdown 文件定义）：**支持 `.trae/agents/{my_agent}.md` 文件系统定义**。由内置 Agent（或 SOLO Agent）自动按场景匹配调用。

**修正依据**（2026-07-07，★★★★★ 官方文档）：
- [docs.trae.cn/ide_subagents](https://docs.trae.cn/ide_subagents)：明确支持项目级 `.trae/agents/{my_agent}.md` 和全局级 `~/.trae-cn/agents/{my_agent}.md` 文件系统定义
- [docs.trae.cn/ide_agent](https://docs.trae.cn/ide_agent)：自定义智能体页面只描述 IDE UI 创建流程，未提及文件系统路径
- [volcengine Subagent 文档](https://www.volcengine.com/docs/86677/2557280?lang=zh)：火山引擎版同样支持 Subagent Markdown 文件定义

**v1.2 核查时（2026-07-01）为何遗漏**：当时仅核查了 `ide_agent` 页面（自定义智能体），未访问 `ide_subagents` 页面（子智能体），导致将"自定义智能体不支持文件系统"错误扩展为"所有智能体都不支持文件系统"。

**juejin 文章评价修正**：[juejin.cn/post/7619769543519780890](https://juejin.cn/post/7619769543519780890)（2026-03-23，★★★☆☆）提到的 `.trae/agents/<agent-name>.md` 路径与当前 Subagent 功能一致，并非"不准确"——该文章描述的是 Subagent 的文件系统定义方式。

**对新 agent 的指引**：
- 本文档第 4.3 节的 subagent 提示词模板**两种创建方式均可**：
  - 方式 A（文件系统）：写入 `.trae/agents/<name>.md`（含 YAML frontmatter + Markdown 正文），由内置 Agent/SOLO Agent 自动匹配
  - 方式 B（IDE 界面）：通过 `@` → 创建智能体 → 填入提示词 → 开启"可被其他智能体调用"
- 建议：团队协作场景用方式 A（可提交 Git），个人项目用方式 B（无需文件管理）

### 7.2 Skills 全局路径

**核查结论**（已由 fact-checker 核查，2026-07-01）：**`~/.trae-cn/skills/` 准确**（针对 Trae CN 国内版），矛盾已解。

**核查依据**：
- 国内版官方文档（★★★★★ [docs.trae.cn/ide/skills](https://docs.trae.cn/ide/skills)，访问 2026-07-01）：明确写 `~/.trae-cn/skills`
- 本地实测：`~/.trae-cn/skills/` 存在（含 7 个技能），`~/.trae/skills/`（国际版路径）和 `~/.traecli/skills/` 均不存在
- 来源 A（国际版文档 `~/.trae/skills/`）适用于国际版，来源 B（`~/.traecli/skills/`）错误，来源 C（`~/.trae-cn/skills/`）准确

**对新 agent 的指引**：若使用 Trae CN 国内版，全局 skills 放在 `~/.trae-cn/skills/<skill-name>/SKILL.md`。

### 7.3 Hooks 沙箱内 python3 可用性

**矛盾描述**：
- 来源（★★★★☆ 本地 Subagent 改进建议.md v1.2）：hooks.json 用 `python3 .trae/hooks/...`，但沙箱是否允许执行 python3 未实测

**核查方法**：
1. 创建一个简单的 test hook（如 `python3 -c "print('hello')"`），看沙箱是否执行
2. 若不可用，改用 `bash .trae/hooks/...` 或绝对路径 python3

### 7.4 Hooks 沙箱 cwd 是否项目根目录

**核查结论**（已由 fact-checker 核查，2026-07-01）：**官方文档已明确——项目 Hook 的 cwd = Hook 配置文件所在项目的根目录**，矛盾已解。

**核查依据**：
- 官方文档（★★★★★ [docs.trae.cn/ide_hook-configuration-reference](https://docs.trae.cn/ide_hook-configuration-reference)，更新 2026-06-26）"工作目录"章节明确：
  - 项目 Hook 命令：cwd = 该 Hook 配置文件所在项目的根目录
  - 全局 Hook 命令：cwd = 工作区根目录（多工作区取第一个）

**对新 agent 的指引**：项目 Hook 用相对路径 `.trae/hooks/...` 是安全的（cwd 是项目根目录）。全局 Hook 需注意多工作区情况。

### 7.5 `tool_input.file_path` 字段结构

**矛盾描述**：
- 来源（★★★★☆ 本地 Subagent 改进建议.md v1.2）：基于 Trae 与 Claude Code Hook 兼容性约定，未在 Trae 官方文档显式列出 Edit/Write 工具的 `tool_input` 内部字段

**核查方法**：
1. 在 hook 脚本中打印 `sys.stdin.read()` 到 stderr，看实际 stdin JSON
2. 确认 `tool_input.file_path` 字段是否存在、是否为完整路径

---

## 第 8 章 附录 — 当前项目资料索引

> 新 agent 可参考以下来源项目的具体文件（路径为相对路径，需在来源项目根目录下访问）。

### 8.1 规则与守卫

| 文件 | 行数 | 作用 |
|------|------|------|
| `.trae/rules/project_rules.md` | 203 | v1.3 完整 12 条规则文本，可直接参考科研场景改写 |
| `.trae/hooks.json` | 17 | hooks.json 格式范例（PreToolUse ask 模式） |
| `.trae/hooks/pre_edit_models_py_guard.py` | 67 | ask 模式 hook 脚本完整实现（含异常处理） |

### 8.2 经验总结

| 文件 | 行数 | 作用 |
|------|------|------|
| `开发日志/Subagent与规则改进建议.md` | 592 | v1.2 subagent 提示词改进 + hooks 可行性分析 + 官方文档核查记录 |
| `开发日志/阶段一-Demo-MVP开发日志.md` | — | v4 MVP 交付经验 |
| `开发日志/阶段二-A组修复实现日志.md` | 551 | v1.3 修复+测试基础设施经验 |

### 8.3 架构设计

| 文件 | 作用 |
|------|------|
| `架构设计/架构设计-Agent架构-v5.md` | v5.2 6 步编排 + 9 组件设计（quality_flags/SessionEventLog/TokenAudit/CheckpointManager） |
| `架构设计/架构演进路线图-v3.1.md` | Demo→生产级演进路径，分阶段闸门 |

### 8.4 方法论拆分范例

| 文件 | 作用 |
|------|------|
| `demo2/方法论/_meta.yaml` | 版本声明范例 |
| `demo2/方法论/hard_rules.md` | 硬性规则模块化范例 |
| `demo2/方法论/heuristics.md` | 启发式规则模块化范例 |
| `demo2/方法论/self_check.md` | 自检清单模块化范例 |
| `demo2/方法论/methodology_full.md` | 完整版方法论 |

### 8.5 6 步编排主文件

| 文件 | 行数 | 作用 |
|------|------|------|
| `demo2/frost_agent.py` | 1410 | v5.2 6 步编排主文件（trace_id 注入 + quality_flags + CheckpointManager），科研项目可参考编排模式 |

### 8.6 fact-checker 核查记录

> 以下为 ai-architecture-fact-checker 对第 3 章和第 7 章的核查结果，供新 agent 了解哪些数据已交叉验证。

**v2.1 修正（2026-07-07）**：

1. **F-12（关键修正）**：7.1 节原结论"智能体不支持 `.trae/agents/` 文件系统定义"有误。Trae 存在 Subagent 类型，支持 `.trae/agents/{name}.md` 文件系统定义。已区分"自定义智能体"与"Subagent"两种形态，并更新 3.4 节、7.1 节、4.3 节 intro、6.5 节。
2. **F-11**：SOLO Agent 独占 subagent 调用在国际版和国内版文档间存在不一致，已在 3.4 节加脚注

**v1.2 修正（2026-07-01）**：

1. Skills 目录结构：`references/`→`resources/`、`assets/`→`templates/`（官方文档为准）
2. Skills URL：`docs.trae.ai/ide/skills`→`docs.trae.cn/ide/skills`（国内版地址）

**部分准确（已标注待验证）**：
1. Skills 三层加载 Token 数：官方文档未给出具体数值，已标 ★☆☆☆☆ 待验证（截至 2026-07-07 仍未找到官方数据）
2. `tool_input.file_path` 字段路径：基于 Trae 与 Claude Code Hook 兼容性推断，待 IDE 实测
3. exit 0 + 无 stdout 等同 allow：从 schema 推断，待 IDE 实测

---

## 参考来源

1. Trae 官方文档 - 规则：[https://docs.trae.ai/ide/rules?_lang=zh](https://docs.trae.ai/ide/rules?_lang=zh)（访问 2026-07-01，★★★★★）
2. Trae 官方文档 - Hook 配置详解：[https://docs.trae.cn/ide_hook-configuration-reference](https://docs.trae.cn/ide_hook-configuration-reference)（更新 2026-06-26，★★★★★）
3. Trae 官方文档 - Skills（国内版）：[https://docs.trae.cn/ide/skills](https://docs.trae.cn/ide/skills)（访问 2026-07-01，★★★★★，已由 fact-checker 核查确认）
4. Trae 官方文档 - 创建并管理智能体：[https://docs.trae.cn/ide_agent](https://docs.trae.cn/ide_agent)（访问 2026-07-01，★★★★★）
5. Trae 官方文档 - 智能体概述：[https://docs.trae.ai/ide/agent-overview?_lang=zh](https://docs.trae.ai/ide/agent-overview?_lang=zh)（访问 2026-07-01，★★★★★）
6. 本地 Subagent 改进建议.md：`开发日志/Subagent与规则改进建议.md`（v1.2，2026-06-27，★★★★☆ IDE 实测验证）
7. 本地 project_rules.md：`.trae/rules/project_rules.md`（v1.3，2026-06-27，★★★★★）
8. juejin 文章 - 一文讲透 .trae 文件夹：[https://juejin.cn/post/7619769543519780890](https://juejin.cn/post/7619769543519780890)（2026-03-23，★★★☆☆，提到 `.trae/agents/` 目录但已被 fact-checker 确认不准确）
9. ai-architecture-fact-checker 核查报告（2026-07-01，★★★★★，核查了第 3 章和第 7 章的所有 Trae 规范数据）

---

*文档版本：v2.1 | 日期：2026-07-07 | 核查状态：v2.0 已通过 fact-checker（发现 1 项关键修正 F-12）+ architecture-critic（P0×4 + P1×7 已全部处理）*
