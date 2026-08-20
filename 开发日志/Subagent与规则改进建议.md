# Subagent、Rules 与 Hooks 改进建议

> 版本：v1.2 | 日期：2026-06-27
> 来源：阶段二 A 组开发实战经验总结 + Kimi 同行评议 + Trae 官方文档 + IDE 实测验证 + fact-checker/architecture-critic 双审查
> 范围：基于 9 个组件实现 + 3 轮 agent 审查 + 5 行业批量测试中的实际踩坑
> v1.2 变更：第四节 Hooks 可行性分析完全重写——按 Trae 官方文档修正 hooks.json 格式（version + 嵌套 hooks 数组），按 Kimi 评议改用 permissionDecision=ask 模式，补充 Notification 事件（5→6 种），补充沙箱运行决策，修正"非强制阻断"描述。2026-06-27 IDE 实测确认官方格式被正确识别（SessionStart Hook 新会话成功触发注入）
> v1.2 审查后修正：按 architecture-critic P0 级问题修正 ask 模式"符合强制语义"的过强声称；按 P0 级问题补充 Hook 脚本异常处理（崩溃时默认 ask）；按 P1 级问题补充 models.py 修改频率量化（近 30 天 1 次）、deny 方案正面评估、实测范围声明、post-write 提示有效性说明；按 fact-checker 建议补充 file_path 字段待验证声明

---

## 一、Subagent 提示词改进

### 1.1 fact-checker：增加"代码逻辑 side effect"检查维度

**问题背景**：v1.0 修复计划中，fact-checker 核查了行号、category 存在性等**数据事实**，全部通过。但它没有发现"修复 2 用 `severity="medium"` 给 `timeout_retry`（默认 low）会导致 Pydantic validator 抛 ValueError"——这是 architecture-critic 才发现的。

**根因**：fact-checker 的提示词侧重"数字/日期/版本号准确性"，不检查"代码引用的 API 与实际定义的兼容性"。

**建议**：fact-checker 提示词增加一段：

> 除了数据事实，还需检查以下"代码副作用"：
> 1. 代码中引用的函数签名是否与实际定义匹配（参数数量、类型、返回值）
> 2. 代码中引用的 enum/set/常量是否存在于实际代码中
> 3. Pydantic model 的 validator 约束是否被代码逻辑违反（如 severity 不匹配会触发 ValueError）
> 4. 代码中修改的返回契约是否在调用方有对应处理

**优先级**：P2（critic 已覆盖部分，但互补有价值）

---

### 1.2 agent-code-validator：要求结构化输出，禁止截断

**问题背景**：之前验证 77/78 通过，"3 个 P2 小问题详情被截断未捕获"。后来排查问题 7 时不得不重新验证，才发现实际是 5 个 P2 问题。说明关键信息可能被输出长度限制截断。

**根因**：validator 的输出没有结构化格式要求，问题可能混在大段文本中被截断。

**建议**：validator 提示词增加强制输出格式要求：

> 输出必须包含结构化的问题清单表格，格式为：
> ```
> | 编号 | 文件 | 行号 | 严重度 | 问题描述 | 改进建议 | 修复工作量 |
> ```
> 如果问题数量超过 10 个，分批次输出（每批 ≤ 10 条），禁止省略或截断。
> 汇总统计必须包含：总测试数、通过数、失败数、P0/P1/P2 问题数。

**优先级**：P1（实际踩坑，重复工作）

---

### 1.3 architecture-critic：明确与 fact-checker 的职责分工

**问题背景**：critic 发现了 severity validator 冲突（最关键的发现），这是 fact-checker 漏掉的。两者职责有重叠但互补。

**建议**：critic 提示词增加职责说明：

> 重点检查 fact-checker 不会覆盖的维度：
> 1. 代码变更的 side effect（Pydantic validator 约束、类型系统、异常传播路径）
> 2. 调用链完整性（是否遗漏某个调用点，函数签名变更是否所有的调用方都更新）
> 3. 返回契约变更对调用方的影响（返回值格式变化、None/empty 的语义变化）
> 4. 验收标准的统计合理性（样本量是否足够支撑统计判断）

**优先级**：P2（critic 已经做得很好，增量改进）

---

## 二、Rules 改进

### 2.1 规则 10.3：明确">100 行"的定义

**问题背景**：v1.2 修改时我修改了约 115 行（含替换），我不确定是否需要再调用审查。最后自行判断"大部分是替换，不是新增"就没调。这个判断标准不清晰——是净新增还是含替换？

**建议**：规则 10.3 修改为：

> **产出超过 80 行的 Markdown 文档（含替换行，按 Edit/Write 的 `new_str` 行数计算）时**，必须通过以下检查才能交付...

理由：80 行（而非 100 行）更保守，且"含替换行"消除"净新增 vs 替换"的模糊性。

```diff
- 触发条件：产出超过 100 行的 Markdown 文档时
+ 触发条件：用 Write/Edit 产出或修改 MD 文件时，new_str 行数 > 80 行（含替换行）时
```

**优先级**：P1（实际踩坑，不确定是否触发）

---

### 2.2 新增规则 11：采纳 agent 建议前的去偏见化

**问题背景**：我第一次看 Kimi 同行评议时**全盘接受**，没有批判性审视。用户指出"你全盘接受了吗？"后重新分析，发现 Kimi 有 3 条建议需要反驳。说明主 agent 在处理其他 agent 建议时有"顺从权威"的倾向。

**建议**：新增规则 11：

> **规则 11：采纳外部 agent 建议前的去偏见化**
>
> **触发条件**：采纳任何 agent（含外部 agent 如 Kimi、内部 subagent）的建议时。
>
> **规则**：
> 1. 必须验证该建议的技术前提是否成立（不能只凭 agent 的论证——必须用 grep/read 核对代码事实）
> 2. 如果建议包含多方案选择，必须说明为什么选这个方案而不是其他
> 3. 所有未采纳的建议必须在产出文档中记录反驳理由
> 4. 如果发现建议有可反驳之处，明确列出；如果没有，也如实说"经验证无反驳点"
>
> **核心精神**：不要全盘接受，也不要为了反驳而反驳。关键是**验证前提 + 说明选择理由**，不是每一条都得挑刺。
>
> **反面教材**：
> - ❌ "Kimi 的评议很有价值，全部采纳"——没有验证前提，没有说明选择理由
> - ❌ 默默跳过 agent 提出的需要团队反馈的问题（如"测试是否算 A 组交付物"），替用户做了决定

**优先级**：P0（导致"全盘接受 Kimi"的根本原因）

---

### 2.3 新增规则 12：多 agent 意见冲突时的仲裁原则

**问题背景**：Kimi 建议"接受偶发超时"，我反驳了；但如果 Kimi 和 architecture-critic 给出冲突建议怎么办？当前 rules 没有规定仲裁原则。

**建议**：新增规则 12：

> **规则 12：多 agent 意见冲突仲裁**
>
> **触发条件**：两个或以上 agent（含外部）对同一问题给出不一致建议时。
>
> **仲裁原则**（按优先级）：
> 1. **代码事实优先**：以 grep/read 直接验证的结果为准，而非 agent 的论证
> 2. **已确认根因为准**：开发日志记录的已确认根因 > 新 agent 提出的假设
> 3. **工程权衡明确化**：如果无法通过事实仲裁（如两个设计方向各有优劣），列出两种方案的 trade-off，由人类决策，不自行选定
> 4. **保守原则**：当不确定时，选择更简单、更少改动的方案

**优先级**：P2（目前靠人工判断，规则化更好）

---

### 2.4 规则 10.2："最小调用测试"定义明确化

**问题背景**：规则说"新组件实现完成"需满足"能通过最小调用测试"，但用 mock 算不算？用真实 API 算不算？模糊导致有时候用 mock 就算完成，有时候又被要求真实 API。

**建议**：规则 10.2 补充定义：

> **"实现完成"的精确定义（v1.3 补充）**：同时满足以下四点——
> 1. 接口定义明确（类/函数签名稳定，不频繁变更）
> 2. Mock 测试通过（需有持久化的 test 文件，非临时脚本），证明接口稳定
> 3. 真实 API 测试通过（如果组件依赖外部 API），证明功能验证
> 4. 代码已写入文件（不只是想完）
>
> 如果组件依赖尚未实现的其他组件，允许先实现 Mock 版本，但验证时标注 `#[mock]`，等依赖就绪后补做完整验证。

**优先级**：P1（消除 mock vs 真实 API 的模糊性）

---

## 三、Hooks 建议

### 3.1 Pre-Edit Hook：修改 models.py 前用 ask 模式拦截

> **可行性升级（v1.2 官方文档 + IDE 实测后）**：此 Hook 在技术上可行且已升级——从 v1.1 的"无条件提示"升级为 **`permissionDecision: ask` 模式**。Hook 进程仍无法判断"本次会话是否已调用过 architecture-critic"，但用 ask 模式每次弹确认框让用户决定"已调过/未调过"。**注意：ask 非真正强制**——用户可点"允许"绕过，依赖用户自律。完整实现见第四节 hooks.json 配置示例。
>
> v1.1 的"无条件提示"（print 到 stderr + exit 0）已被 Kimi 评议确认**无效**——既不阻止执行也不传给模型。v1.2 改用官方推荐的 `hookSpecificOutput` JSON + `permissionDecision: ask` + `additionalContext`。

**问题背景**：规则 10.2 说"修改 models.py 前必须调用 architecture-critic"，但只是规则，没有技术强制。

---

### 3.2 Pre-Response Hook：汇报前自动检查清单

> **可行性修正（v1.1 联网搜索后，v1.2 维持）**：此 Hook 在 Trae Hooks 真实架构下**不可行**。详见第四节分析——Hook 进程无法访问 agent 内部状态（会话中调用过哪些 subagent）。此 Hook 的建议保留作为平台功能需求（FR），当前阶段只能靠 Rules 文本约束 + 人工检查。

**问题背景**：规则 10.3 的检查清单需要人工过，容易遗漏。v1.2 修改了约 115 行 .md 但没调 fact-checker，就是因为人工判断失误。

~~**建议**：增加 pre-response hook：~~

~~```
Hook 名称：pre-response-quality-gate
触发条件：agent 即将发送回复给用户
拦截条件：
  - 本次会话用 Write/Edit 产出或修改了 >80 行的 .md 文件，且未调用 fact-checker + architecture-critic
  - 本次会话修改了 models.py，且未调用 architecture-critic
  - 本次会话有"新组件实现完成"，且未调用 agent-code-validator
拦截行为：提示 agent 补充调用对应审查 agent 后再回复
可绕过：是（用户确认后可继续，但记录 warning）
```~~

**当前替代方案**：在 Rules 10.3 中强化人工检查清单，并增加"复查后仍未调则记录到开发日志"的问责机制。

---

### 3.3 Post-Write Hook：新功能对应测试提示

> **可行性确认（v1.1 联网搜索后，v1.2 维持 + 审查后修正）**：此 Hook **技术可行**——PostToolUse 可拦截 Write 操作，只需检查文件路径即可，不需要访问 agent 内部状态。完整实现见第四节 hooks.json 配置示例（v1.2 已改用 `additionalContext` 注入提示，比 v1.1 的纯打印更有效）。**注意（architecture-critic P1 级问题修正）**：提示有效性依赖模型行为——additionalContext 注入给模型，非直接显示给用户，模型可能静默吸收不转达。已在脚本中明确写"请在下一步回复中告知用户"引导转达。

**问题背景**：demo2/ 之前根本没有测试文件，开发过程中没有强制测试。修复计划新增的 test_fm_review.py 是事后补的。

~~**建议**：增加 post-write hook：~~

~~```
Hook 名称：post-write-test-suggestion
触发条件：demo2/ 下新增或修改 .py 文件（非 test_*.py 文件）
检查逻辑：demo2/tests/ 下是否存在对应的 test_*.py
提示行为："建议在 demo2/tests/ 创建对应测试文件"（非强制拦截，仅提示）
可绕过：是（提示性质）
```~~

**具体实现**：见第四节 hooks.json 中 `post-write-test-suggestion` 配置 + 对应的 Python Hook 脚本。

---

### 3.4 Pre-Agent-Call Hook：去偏见化检查

> **可行性修正（v1.1 联网搜索后，v1.2 维持）**：此 Hook 在 Trae Hooks 真实架构下**不可行**。详见第四节分析——Hook 无法读取 agent 的回复文本内容，回复是 PreToolUse/PostToolUse 之外的概念。此 Hook 的建议保留作为平台功能需求（FR），当前阶段只能靠新增规则 11 文本约束。

**问题背景**：对应新增规则 11。当我调用外部 agent（如 Kimi 评议）后准备采纳建议时，需要一个检查。

~~**建议**：增加 pre-agent-adoption hook：~~

~~```
Hook 名称：pre-agent-adoption-check
触发条件：agent 在回复中表示"采纳 XX agent 的建议"
拦截条件：回复中未包含对建议的批判性分析（无反驳点、无替代方案对比）
拦截行为：提示 agent "请按规则 11 进行去偏见化检查：列出至少 1 个反驳点"
可绕过：是
```~~

**当前替代方案**：靠规则 11 的文本约束（列出反驳点 + 验证前提 + 记录未采纳理由），无法技术拦截。

---

## 四、Hooks 可行性分析（官方文档 + IDE 实测验证）

> **格式验证声明**：本节的 hooks.json 格式基于 Trae 官方文档（[Hook 配置详解](https://docs.trae.cn/ide_hook-configuration-reference)，2026-06-26，★★★★★ [可信]）+ IDE 实测验证。
>
> **实测记录**：
> - 2026-06-27 SessionStart：官方格式被识别，`[Hook 测试]` 注入文字 + 标记文件写入磁盘 ✅
> - 2026-06-27 PreToolUse（本会话）：修改 demo2/models.py 触发 Hook，python3 沙箱执行成功，additionalContext 注入到 AI 上下文，permissionDecision=ask 弹确认框（用户看到"运行/跳过"选项）✅
> - **完整链路已验证**：4 项原先标注"未实测"的假设全部通过——(1) PreToolUse 事件触发 (2) python3 沙箱可用 (3) hookSpecificOutput JSON 正确解析为 permissionDecision+additionalContext (4) tool_input.file_path 字段正确识别 models.py
>
> 本文档中所有"可行性"判断均基于官方文档 + IDE 实测，标注方式：（已实测）= 在 IDE 中验证过；（官方文档）= 官方文档明确说明但未实测；（推测）= 基于文档推理。

### 4.1 Trae Hooks 的真实能力

> 来源：[Trae 官方文档 - Hook 配置详解](https://docs.trae.cn/ide_hook-configuration-reference)（2026-06-26，★★★★★ [可信]）+ IDE 实测（2026-06-27）

**6 种事件类型**（官方文档，SessionStart 已实测）：

| 事件 | 触发时机 | 典型用途 | 阻断能力 |
|------|---------|---------|---------|
| `SessionStart` | 会话创建后、第一轮对话前 | 自动注入项目上下文、设置环境变量 | 不可阻断（exit 2 不影响流程） |
| `UserPromptSubmit` | 用户提交消息时 | 意图识别、敏感词过滤 | 可阻断（`decision: block` 或 exit 2 禁止执行 Prompt） |
| `PreToolUse` | 工具调用**前** | 校验/拦截工具调用、修改工具参数、要求用户确认 | 可阻断（`permissionDecision: deny` 或 exit 2 拒绝执行） |
| `PostToolUse` | 工具调用**后** | 验证执行结果、附加上下文 | 可阻断（`decision: block` 向模型传递阻断信息） |
| `Stop` | Agent 完成输出、准备结束时 | 闭环验证、阻止结束并要求继续 | 可阻断（`decision: block` 或 exit 2 阻断停止） |
| `Notification` | 工具调用等待用户确认时、或智能体完成任务时 | 发送通知、记录日志、推送消息 | 异步执行，不阻断主流程 |

**配置格式**：`.trae/hooks.json`（官方格式，已实测）：

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

**字段说明**（官方 schema）：
- 顶层：`version`（默认 1，当前仅支持 1）、`hooks`（事件名到 Hook 组的映射）
- Hook 组层：`matcher`（正则，仅对 PreToolUse/PostToolUse/Notification 有效）、`loop_limit`（仅对 Stop 有效，默认 5）、`hooks`（Hook 列表，必填）
- Hook 定义层：`type`（默认 `command`，当前仅支持 command）、`command`（Shell 命令，必填）、`timeout`（默认 30 秒）

> **v1.1 格式错误说明**（已修正）：v1.1 草稿的 hooks.json 混入了 `name`/`enabled`/`description` 字段（非官方字段），且缺少 `version` 顶层声明和嵌套 `hooks` 数组——这是 Claude Code 语法 + 臆测字段的混合。v1.2 已按官方格式重写，2026-06-27 IDE 实测确认官方格式被正确识别。

**关键能力**（官方文档）：
1. **stdin 通用字段**：`session_id`、`cwd`、`hook_event_name`、`workspace_roots`——Hook 进程通过 stdin 接收
2. **stdout 两种格式**：JSON（结构化控制流程）或纯文本（仅 SessionStart/UserPromptSubmit 支持，作为附加上下文给模型）
3. **退出码**：0=正常、2=阻断性错误（stderr 传给模型）、其他=非阻断性错误
4. **additionalContext 能力**：PreToolUse/PostToolUse/SessionStart/UserPromptSubmit 的 hookSpecificOutput 可返回 `additionalContext` 字段，直接给模型注入行为指导（比纯打印文字更有力）
5. **环境变量注入**：SessionStart 可向 `$TRAE_ENV_FILE` 写入环境变量，供后续 Hook 使用
6. **运行方式**：沙箱运行（限制文件访问）或本地自动运行（更高安全风险）——本项目选**沙箱运行**

**重要限制**（官方文档，已实测 SessionStart 确认）：
1. Hooks **不能直接访问 agent 会话历史**——stdin 只提供 session_id/cwd/hook_event_name/workspace_roots，没有 transcript 或 conversation_history 字段
2. Hook 脚本是独立进程，无法访问 agent 内部状态（调过哪些 subagent、回复文本内容）

### 4.2 针对本项目改进的 hooks.json 配置

基于官方格式 + IDE 实测验证，本项目推荐的 hooks.json 配置：

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
            "command": "python3 .trae/hooks/pre_edit_models_py_guard.py",
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
            "command": "python3 .trae/hooks/post_write_test_suggestion.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

> 注：v1.1 草稿中的 `name`/`enabled`/`description` 字段已删除（非官方字段）；v1.1 的 `pre-response-quality-gate`（Stop 事件）和 `project-context-injection`（SessionStart 事件）因不可行或价值不高，暂不配置。

**Hook 脚本示例 1：pre_edit_models_py_guard.py**（PreToolUse，ask 模式）

设计决策：用 `"permissionDecision": "ask"` 而非 `"deny"` 或纯提示。

**语义偏差风险声明（architecture-critic P0 级问题修正）**：ask 模式**并非真正强制**——用户每次都可以点"允许"绕过，Hook 不会阻止。这与规则 10.2 的"必须"存在本质偏差。如果用户形成"肌肉记忆"每次点"允许"，Hook 就退化成 v1.1 的"无效提示"。真正的强制需要 Hook 能感知 agent 状态（是否调过 critic），这超出 Trae Hooks 当前能力。当前 ask 模式是"提醒用户自律"的折中方案，**规则 10.2 的强制力度仍需靠 Rules 文本 + 人工检查保证，Hook 只是辅助提醒**。

**三种方案权衡**：

| 方案 | 语义对齐 | UX | 风险 | 选/不选理由 |
|------|---------|-----|------|-----------|
| `ask`（每次弹确认框） | 部分对齐（用户可绕过） | 中（每次确认约 5 秒） | 用户肌肉记忆绕过 | **选**——当前架构下最接近规则 10.2 的折中 |
| `deny`（无条件阻断） | 完全对齐（不审查就不允许 Edit） | 差（已调过 critic 也要重新 Edit） | 阻断正常工作流 | **不选**——更接近强制语义，但 UX 代价高；用户调完 critic 后需重新发起 Edit，累积成本可能反超 ask。若未来发现 ask 绕过率高，可切换到 deny |
| 纯提示（exit 0 + stderr） | 不对齐（不阻止也不传给模型） | 好（无干扰） | 完全无效 | **不选**——已被 Kimi 评议确认无效 |

**models.py 修改频率量化（architecture-critic P1 级问题修正）**：
- git log 验证（2026-06-27）：近 30 天 models.py 修改 **1 次**（commit bb641a5 "行业定义 Agent 第一阶段 Demo MVP 交付"），历史总共 1 次
- 按 ask 模式每次确认约 5 秒计，月成本约 5 秒，远低于一次 critic 遗漏的返工成本（估 30+ 分钟）
- 该量化数据为 ★★★★☆ [可信]（git log 直接验证），但样本量小（仅 1 次修改），迭代期可能升高

**无状态 vs 有状态豁免（architecture-critic P2 级问题修正）**：
- 选 A（无状态，每次弹）而非 B（session 内豁免）
- v1.2 原反驳"环境变量复杂度"是稻草人——状态文件方案（如 `.trae/hooks/.critic_called.flag`）比环境变量简单
- **真正的反驳理由**是**状态过期**：agent 调了 critic 但 flag 没清理，下次 models.py 修改就跳过提醒，这比"每次 ask"更危险。无状态设计在可靠性上确实更优
- 不用纯提示（exit 0 + stderr 无效，已被 Kimi 评议确认）

```python
#!/usr/bin/env python3
"""PreToolUse hook：修改 models.py 前用 ask 模式让用户确认是否已调用 architecture-critic。

设计：permissionDecision=ask + additionalContext 注入行为指导
来源：Trae 官方文档 https://docs.trae.cn/ide_hook-configuration-reference（2026-06-26）

字段待验证声明（fact-checker 建议）：
- tool_input.file_path 字段路径基于 Trae 与 Claude Code Hook 兼容性约定
  （官方文档显式声明支持读取 Claude Code Hook 配置），未在 Trae 官方文档
  显式列出 Edit/Write 工具的 tool_input 内部字段，待 IDE 实测确认
- exit 0 + 无 stdout 输出 等同于 allow 的默认行为，官方文档未显式说明，
  从 schema 推断（permissionDecision 缺省时默认 allow），待 IDE 实测确认
"""
import sys
import json


def _emit_ask(reason: str, additional_context: str = "") -> None:
    """统一输出 ask 决策（含异常路径复用）。"""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main():
    # PreToolUse 的 stdin 含：session_id, cwd, hook_event_name, tool_use_id, tool_name, llm_tool_name, tool_input
    # 异常处理策略（architecture-critic P0 级问题修正）：
    # 崩溃时默认 ask（保守），而非静默放行——避免 Hook bug 导致 models.py 修改无防护执行
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
    except Exception as e:
        # JSON 解析失败或字段缺失：保守 ask，而非 data={} 静默放行
        _emit_ask(
            f"[Hook 异常] stdin 解析失败：{e}。出于安全考虑，仍需确认是否已调用 architecture-critic。",
            "规则提醒：Hook 脚本解析 stdin 异常，无法判断目标文件。请人工确认本次修改是否涉及 models.py，若涉及则需先调 architecture-critic。"
        )
        return

    # 检测是否在修改 models.py
    if "models.py" in file_path and file_path.endswith("models.py"):
        # 官方推荐方式：返回 hookSpecificOutput JSON
        # permissionDecision=ask：弹出确认框，由用户决定是否执行
        # additionalContext：给模型注入行为指导（比纯打印文字更有力）
        _emit_ask(
            "[规则 10.2] 即将修改 models.py。请确认是否已调用 architecture-critic 审查设计。\n"
            "  - 若已调用 → 点击允许继续\n"
            "  - 若未调用 → 点击拒绝，先完成审查再修改",
            "规则提醒：修改 models.py 前必须调用 architecture-critic 审查字段变更对 State 传递的影响。"
            "这是规则 10.2 的强制要求。如果本次修改是紧急修复且无法先审查，请在 detail 中说明理由。"
            "请在下一步回复中告知用户此确认已触发，避免静默放行。"
        )
        # exit 0 正常退出（hookSpecificOutput 会被 Trae 解析）
        return

    # 非 models.py 文件，正常放行（不输出 = allow，基于 permissionDecision 缺省推断，待 IDE 实测确认）


if __name__ == "__main__":
    main()
```

**Hook 脚本示例 2：post_write_test_suggestion.py**（PostToolUse，提示模式）

```python
#!/usr/bin/env python3
"""PostToolUse hook：新增 .py 文件时提示建议创建对应 test 文件。

设计：additionalContext 注入提示（非阻断，工具已执行完）
来源：Trae 官方文档 https://docs.trae.cn/ide_hook-configuration-reference（2026-06-26）

提示有效性说明（architecture-critic P1 级问题修正）：
- additionalContext 注入给模型，非直接显示给用户
- 模型可能静默吸收不转达，导致用户看不到提示
- 已在提示文本中明确写"请在下一步回复中告知用户"，引导模型转达
"""
import sys
import json


def main():
    # PostToolUse 的 stdin 含：session_id, cwd, hook_event_name, tool_use_id, tool_name, tool_input, tool_response
    # 异常处理：PostToolUse 是提示性质（非防护），崩溃时静默放行可接受（与 pre_edit 不同）
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
    except Exception:
        return  # 解析失败时静默退出（提示性质，无防护义务）

    # 检测是否在 demo2/ 下新增 .py 文件（非 test_*.py）
    if (file_path.startswith("demo2/") and
        file_path.endswith(".py") and
        "/test_" not in file_path and
        not file_path.endswith("test_.py")):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"[提示] 已创建 {file_path}。建议在 demo2/tests/ 下创建对应的 test_*.py 文件。"
                    f"demo2/ 之前因缺少测试文件导致问题排查困难（见开发日志）。"
                    f"请在下一步回复中告知用户此提示，避免静默吸收。"
                )
            }
        }
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

**运行方式决策**：选**沙箱运行**
- 理由：本项目 Hook 脚本只读 `.trae/hooks/` 下的 Python 脚本和 stdin JSON，不需要访问项目外文件
- 沙箱更安全，避免 Hook 脚本意外访问系统文件
- 如未来 Hook 需要访问全局日志目录等，再评估是否切换到本地自动运行

**沙箱未验证假设声明（architecture-critic P1 级问题修正）**：
- **python3 可用性未实测**：command 用 `python3 .trae/hooks/...`，但沙箱是否允许执行 python3、是否限制可执行文件白名单，未在 IDE 中实测。部署前需验证沙箱下 python3 是否可执行
- **cwd 路径未实测**：command 用相对路径 `.trae/hooks/pre_edit_models_py_guard.py`，沙箱的 cwd 是否是项目根目录未验证。若沙箱 cwd 不是项目根目录，相对路径会解析失败，Hook 静默不执行。**建议改进**：Hook 脚本应从 stdin 的 `workspace_roots` 字段解析项目根目录，用绝对路径加载脚本（当前脚本未做此处理，部署前需补）
- 上述两点是部署前的必测项，不补测可能导致 Hook 静默失效（表面已配置，实际不工作）

### 4.3 结论：哪些 Hook 可行、哪些不可行

基于官方文档 + IDE 实测，重新评估 4 个 Hook 建议的可行性：

| Hook | 原建议触发条件 | 可行性 | 阻断方式 | 替代方案 | 说明 |
|------|-------------|--------|---------|---------|------|
| pre-edit-models-py-guard | 修改 models.py 且未调过 architecture-critic | ✅ **可行**（ask 模式） | `permissionDecision: ask` | — | Hook 无法判断"是否调过 critic"，用 ask 模式让用户每次确认。**注意：ask 非真正强制**——用户可点"允许"绕过，依赖用户自律。deny 模式更接近强制语义但 UX 较差（见 4.2 节权衡） |
| pre-response-quality-gate | 汇报前检查已调用的审查 agent | ❌ **无法实现** | — | Rules 10.3 人工检查清单 | Hook 无法读取"本次会话调用过哪些 subagent"——stdin 无 conversation_history 字段。Stop + 状态文件组合方案理论可行（PostToolUse 匹配 Task 工具时写状态文件，Stop 读取检查），但 Task 工具的 tool_input 是否含 subagent 标识未实测，暂不采纳 |
| post-write-test-suggestion | 新增 .py 文件时提示创建 test | ✅ **技术可行** | `additionalContext` 提示 | — | PostToolUse 检查文件路径即可，无需访问 agent 内部状态。**注意：提示有效性依赖模型行为**——additionalContext 注入给模型，非直接显示给用户，模型可能静默吸收不转达。已在脚本中明确写"请在下一步回复中告知用户此提示"引导转达 |
| pre-agent-adoption-check | 回复含"采纳 XX agent 建议"且无批判分析 | ❌ **无法实现** | — | 规则 11 文本约束 | Hook 无法读取 agent 的回复文本——回复不是工具调用，不在 PreToolUse/PostToolUse 范围内 |

> **关键修正（v1.2，基于 Kimi 同行评议 + 官方文档验证 + architecture-critic 审查）**：
> 1. 原 v1.1 草稿说"hooks 是提示+记录机制，非强制阻断"——这是**过度简化**。官方文档确认 PreToolUse 可通过 `permissionDecision: deny` 或 exit 2 **强制阻断**工具执行；Stop 可通过 `decision: block` **强制阻断**智能体停止。只有 SessionStart 和 Notification 是真正"非阻断"的。
> 2. 原 v1.1 草稿的 hooks.json 格式有**结构性错误**（混入 name/enabled/description 字段，缺少 version 和嵌套 hooks 数组）——已按官方格式重写。2026-06-27 IDE 实测确认官方格式被正确识别。
> 3. 原 v1.1 草稿的 pre_edit_models_py_guard.py 脚本**无效**（只 print 到 stderr + exit 0，不阻止执行也不传给模型）——已改用 `permissionDecision: ask` + `additionalContext`。
> 4. 原 v1.1 草稿遗漏 `Notification` 事件——已补充（共 6 种事件，非 5 种）。
> 5. 原 v1.1 草稿未提及"沙箱运行 vs 本地自动运行"——已补充决策：选沙箱。
> 6. Kimi 评议中"Bash → RunCommand 更正"建议已**反驳**——草稿全文无 Bash 引用（Grep 验证）。Kimi 已撤回此建议。
> 7. Kimi 评议中"scene: git_message"建议已**验证存在但不需要**——官方文档确认此字段存在，但当前项目无 commit message 规范需求。

> **关键发现**：pre-response-quality-gate 和 pre-agent-adoption-check 两个 Hook **在 Trae Hooks 当前架构下不可行**，因为它们需要访问 agent 内部状态（调过哪些 subagent、回复文本内容）。Trae Hooks 只能拦截**工具调用**（PreToolUse/PostToolUse），不能拦截**agent 的文本回复**。这两个需求仍然只能靠 Rules 文本约束 + 人工检查清单。
>
> pre-edit-models-py-guard 从 v1.1 的"盲目提示"升级为 v1.2 的"ask 模式"——力度更强，是当前架构下最接近规则 10.2 的方案（非真正强制，依赖用户自律）。

---

## 五、Agent 选用分析：为什么总是只调用那几个？(v1.1 新增)

### 5.1 本项目实际调用过的 agent

| Agent | 调用频率 | 触发原因 |
|-------|---------|---------|
| `architecture-critic` | 最高 | 规则 10.2 强制——修改 models.py 前、产出 >100 行评估文档后 |
| `ai-architecture-fact-checker` | 高 | 规则 10.1 强制——产出包含技术数据的文档后 |
| `agent-code-validator` | 高 | 规则 10.2 强制——新组件实现完成后 |
| `frost-test-runner` | 低 | 仅阶段一用于跑测试套件 |
| `search`（通用搜索） | 中 | 探索代码时偶尔使用 |

### 5.2 从未调用但实际相关且能胜任的 agent（3 个）

| Agent | 描述 | 何时应调但没调 | 为什么没调 |
|-------|------|--------------|-----------|
| `methodology-expert` | "审查和改进基于  标准的行业分析方法论" | Step 5 自检失败时分析是否源于方法论应用问题；方法论 v2→v5 升级后检查新规则生效情况 | **完全忘了它存在**。名字含"品牌前缀"和"methodology"，与项目高度相关，但 16 个 agent 列表太长，在具体任务中想不起来 |
| `definition-quality-checker` | "验证行业定义 Agent 的输出质量" | 5 行业批量测试后验证输出语义质量（非代码正确性） | 同上。有 agent-code-validator 验证代码质量后，没想到还有专门的"输出质量" validator |
| `python-backend-implementer` | "将 Agent 架构设计规范转换为可运行的 Python 代码" | 从零实现新模块（如 token_audit.py、output_safety.py）时 | 描述说它实现固定四个文件，我们是增量升级不是从零实现，感觉不匹配 |

### 5.3 根因分析

**原因 1：规则驱动的思维惯性**（主要）

规则 10 的"强制检查清单"点名了 architecture-critic、fact-checker、code-validator 三个。每次想到"要审查了"，下意识就是这三个。不在清单里的 agent 不在思维路径上。

**原因 2：发现性问题**

16 个 subagent 只以一行描述呈现。做具体任务时，倾向于从"上一轮用过什么"延伸，而不是重新扫描全部 16 个。

**原因 3：缺少"可选推荐路由表"**

当前规则只定义了"什么时候**必须**调某个 agent"，没有"什么场景下**可以尝试**某个 agent"。缺少推荐性指引。

### 5.4 改进建议：规则 10 增加推荐路由表

在 `project_rules.md` 规则 10 中增加以下表格（非强制，仅供选用参考）：

| 场景 | 推荐 agent | 用途 |
|------|-----------|------|
| Step 5 自检持续 fail | `methodology-expert` | 分析自检失败是否源于方法论应用问题 |
| 方法论版本升级后 | `methodology-expert` | 检查新方法论规则是否在报告中生效 |
| 批量测试后质量检查 | `definition-quality-checker` | 验证多个行业的输出语义质量一致性 |
| 需要从零实现新模块 | `python-backend-implementer` | 生成 models.py/frost_agent.py 等骨架代码 |
| 代码变更完成后 | `frost-test-runner` | 回归测试，防止已有功能被破坏 |
| 产出 >100 行 .md 后 | `ai-architecture-fact-checker` | 交叉验证技术数据准确性 |
| 修改 models.py 前 | `architecture-critic` | 审查字段变更对 State 传递的影响 |
| 新组件实现完成后 | `agent-code-validator` | 运行时验证代码正确性 |

底线：**不是每个场景都要调，但 agent 选型时应过一遍此表，确认是否需要**。

---

## 六、优先级排序（v1.2 更新）

> v1.2 修正：基于 Kimi 同行评议 + IDE 实测 + fact-checker/architecture-critic 双审查，pre-edit-models-py-guard 从"降级为无条件提示"升级为"ask 模式"，优先级从 P1 提升到 P0（实际有效了，价值提高）。原 v1.1 的"pre-response-quality-gate"和"pre-agent-adoption-check"维持 P2（暂不可实现，靠 Rules 文本约束替代）。
>
> **v1.2 审查后修正声明（architecture-critic P0 级问题）**：ask 模式并非真正"强制"——用户可点"允许"绕过。本表 pre-edit-models-py-guard 行已从"符合规则 10.2 强制语义"修正为"当前架构下最接近规则 10.2 的方案，依赖用户自律"。

| 优先级 | 改进项 | 类型 | 理由 |
|--------|--------|------|------|
| **P0** | 规则 11：去偏见化规则 | Rules | 导致"全盘接受 Kimi"的根本原因。Hooks 无法强制，只能靠 Rules |
| **P0** | Hook：pre-edit-models-py-guard（ask 模式 + additionalContext） | Hooks | v1.2 升级：从无效的"无条件提示"改为官方推荐的 ask 模式，是当前架构下最接近规则 10.2 的方案（非真正强制，依赖用户自律；deny 模式更接近强制语义但 UX 较差，见 4.2 节权衡）。仅 IDE 实测了 SessionStart 事件被识别，PreToolUse + python3 实际执行未实测 |
| **P1** | 规则 10.3 行数定义明确 | Rules | 实际踩坑，不确定是否触发审查 |
| **P1** | 规则 10.2 最小调用测试定义 | Rules | 消除 mock vs 真实 API 模糊性 |
| **P1** | agent-code-validator 输出结构化 | Prompts | P2 问题被截断导致重复工作 |
| **P1** | 规则 10 增加 agent 推荐路由表 | Rules | 解决 agent 发现性不足问题（第五节） |
| **P2** | fact-checker 增加 side effect 检查 | Prompts | critic 已覆盖部分，互补有价值 |
| **P2** | architecture-critic 职责分工 | Prompts | 增量改进，当前表现已很好 |
| **P2** | 规则 12：多 agent 仲裁原则 | Rules | 目前靠人工判断，规则化更好 |
| **P2** | Hook：post-write-test-suggestion | Hooks | 技术可行，但提示有效性依赖模型是否转达给用户（additionalContext 注入给模型，非直接显示给用户） |
| **P2** | Hook：SessionStart 项目上下文注入 | Hooks | 技术上可行，价值中等（当前 project_rules.md 已覆盖大部分上下文） |
| **P2** | Hook：pre-response-quality-gate（暂不可行） | Hooks | 需要访问 agent 会话历史，Trae Hooks 当前架构不支持。替代方案：Rules 10.3 人工检查清单 |
| **P2** | Hook：pre-agent-adoption-check（暂不可行） | Hooks | 需要读取 agent 回复文本，Trae Hooks 当前架构不支持。替代方案：规则 11 文本约束 |

---

*建议版本：v1.2 | 日期：2026-06-27 | 来源：阶段二 A 组开发实战 + Kimi 同行评议 + Trae 官方文档 + IDE 实测验证 + fact-checker/architecture-critic 双审查*
*v1.2 变更：第四节完全重写（官方格式 + ask 模式 + Notification + 沙箱决策 + 阻断能力修正），第三节 3.1 同步升级，第六节优先级更新*
*v1.2 审查后修正：按 architecture-critic P0 级问题修正 ask 模式"符合强制语义"的过强声称；按 P0 级问题补充 Hook 脚本异常处理（崩溃时默认 ask）；按 P1 级问题补充 models.py 修改频率量化（近 30 天 1 次）、deny 方案正面评估、实测范围声明、post-write 提示有效性说明；按 fact-checker 建议补充 file_path 字段待验证声明*
