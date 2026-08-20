# Trae Rules & Hooks 草稿同行评议意见

> **角色**：行业定义 Agent 项目同行评议专家
> **评议对象**：`project_rules_v1.3_草稿.md` 及 `草稿_rules/` 目录下的三个拆分文件（`project_rules.md`、`agent_review_rules.md`、`multi_agent_rules.md`）中关于 Trae Hooks 的部分，以及 `开发日志/Subagent与规则改进建议.md` 第四节 Hooks 可行性分析
> **评议日期**：2026-06-27
> **评议依据**：Trae IDE 官方文档（2026-06-11/12/14）+ 社区实测报告 + 子代理交叉验证

---

## 一、总体判断

**该草稿对 Trae Hooks 的描述存在"结构性失真"——不是细节偏差，而是配置格式层面的根本错误。**

草稿中的 `hooks.json` 示例混合了 Claude Code 的语法（如 `name`、`enabled`、`description` 字段直接放在事件层）和臆测字段，与 Trae 官方格式（2026-06-14 发布的《Hook 配置参考》）存在不可忽略的不兼容。如果按草稿格式直接写入 `.trae/hooks.json`，Hook 将大概率无法被 Trae 识别。

Rules 部分相对安全，但错失了 Trae 最新版（2026-06-11）提供的多项可用特性（`globs` 文件匹配、`description` 智能生效、`scene: git_message`、多层嵌套），相当于用 2025 年的写法适配 2026 年的平台。

---

## 二、分维度评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **Rules 语法准确性** | ⚠️ 基本可用，但落后一个版本 | 核心规则内容（alwaysApply、Markdown 正文）正确，但未利用 `globs`、`description`、子目录规则、多层嵌套、`scene: git_message` 等新特性 |
| **Hooks 配置格式准确性** | ❌ 存在结构性错误 | `hooks.json` 格式与官方文档不符，关键字段（`name`/`enabled`/`description`）不存在于官方格式中；缺少 `version` 字段；Hook 定义未嵌套在正确的 `hooks` 数组内 |
| **Hooks 事件覆盖完整性** | ⚠️ 遗漏 1 个事件 | 草稿写 5 种，官方是 6 种（缺 `Notification`） |
| **Hooks 脚本示例正确性** | ❌ 拦截逻辑错误 | 草稿使用 `print(..., file=sys.stderr)` 作为拦截方式，但官方正确方式是 `exit code 2` 或 `stdout` 返回 `hookSpecificOutput` JSON |
| **Hooks 能力边界判断** | ✅ 基本准确 | 草稿关于"Hook 无法访问 agent 会话历史""无法读取 agent 回复文本"的判断是正确的，但低估了新版本 `additionalContext` 的能力 |
| **来源可信度** | ⚠️ 来源过时 | 草稿引用掘金文章（2026-06-15），但官方文档（2026-06-14）已发布更权威的格式规范。掘金文章更多是"经验分享"而非"格式规范" |

---

## 三、关键问题列表（Q 级）

### Q1：草稿中的 `hooks.json` 格式是否会被 Trae 识别？

**草稿中的格式（第 4.2 节）**：

```json
{
  "hooks": {
    "PreToolUse": [{
      "name": "pre-edit-models-py-guard",
      "enabled": true,
      "matcher": "Edit|Write",
      "command": "python3 .trae/hooks/pre_edit_models_py_guard.py",
      "description": "修改 models.py 前检查..."
    }]
  }
}
```

**官方实际格式**（来源：`https://docs.trae.cn/ide_hook-configuration-reference`，2026-06-14）：

```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "python3 .trae/hooks/pre_edit_models_py_guard.py",
        "timeout": 30
      }]
    }]
  }
}
```

**差异分析**：

| 字段 | 草稿 | 官方 | 后果 |
|------|------|------|------|
| `version` | 无 | `1`（默认值） | 草稿缺少顶层版本声明，可能触发解析警告 |
| `name` | 存在 | **不存在** | 未知字段，可能被忽略，无功能影响但误导读者 |
| `enabled` | 存在 | **不存在** | 启停通过 IDE 设置界面控制，非配置文件字段。此字段无功能 |
| `description` | 存在 | **不存在** | 同上，纯误导 |
| 内层 `hooks` 数组 | 无 | 必须有 | **这是最关键的结构性错误**。草稿把 `command` 直接放在 Hook 组层，但官方要求 `command` 必须嵌套在 `"hooks": [{"type": "command", "command": "..."}]` 中。如果按草稿格式写入，Trae 大概率无法识别该 Hook |
| `type` | 无 | 默认 `"command"` | 草稿未声明 `type`。虽然默认值恰好是 `command`，但缺少显式声明不利于维护 |
| `timeout` | 无 | 默认 30 秒 | 草稿的 Hook 脚本可能因超时而被 kill |

**建议**：立即按官方格式重写 `hooks.json` 示例。同时建议用 Trae IDE 实际创建一个测试 Hook，验证格式是否被正确识别（GUI 中有"已配置的 Hooks"列表，可直观确认）。

---

### Q2：PreToolUse 的拦截脚本示例是否真的能起到"提示"作用？

**草稿中的脚本示例**（第 4.2 节）：

```python
if "models.py" in file_path and file_path.endswith("models.py"):
    print("⚠️ [规则 10.2]...", file=sys.stderr)
    print("[Hook] models.py 修改警告...")
```

**问题**：

1. **未调用 `sys.exit(2)`**：官方文档明确说明，`exit code 2` 在 `PreToolUse` 中等价于 `"permissionDecision": "deny"`。草稿只打印到 stderr 就正常退出（exit 0），这不会阻止工具执行，也不会把 stderr 内容传递给模型——**这个 Hook 实际上是无效的**。

2. **未返回 `hookSpecificOutput` JSON**：官方支持的正确方式有两种：
   - 方式 A：`stdout` 返回 `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "..."}}`——弹出确认框让用户决定
   - 方式 B：`sys.exit(2)` + `stderr` 输出——拒绝执行并把 stderr 作为原因传递给模型

3. **草稿的注释说"输出附加上下文给模型（可选）"**：但 `print("[Hook]...")` 到 stdout 在不返回正确 JSON 格式时，不会被解析为 `additionalContext`。

**建议**：将脚本示例改为官方推荐的模式。如果目的是"提示而非强制拦截"，应返回 `"permissionDecision": "ask"`（弹出确认框）；如果目的是"强制拦截"，应 `sys.exit(2)`。

---

### Q3：`Notification` 事件被遗漏意味着什么？

草稿（以及引用的掘金 OODER 文章）只列出了 5 种事件，缺了 `Notification`。这是 2026-06-12 官方文档新增的事件（虽然掘金文章发表于 2026-06-15，但可能基于更早的测试版本）。

`Notification` 的特点是：
- **异步触发**，不阻塞主流程
- 在"工具调用等待用户确认时"或"智能体完成任务时"触发
- 适合发送通知、记录日志、推送消息（如飞书/钉钉）

**对项目的影响**：如果未来想用 Hook 在任务完成后自动推送通知（如"报告已生成，请查收"），`Notification` 是最合适的事件。草稿的遗漏意味着这个选项不在团队的知识库中。

---

### Q4：Rules 的多层嵌套和子目录特性是否值得利用？

Trae 2026-06-11 官方文档确认：
- `.trae/rules/` 支持最多 **3 层嵌套**（子文件夹归类）
- 支持在**项目任意子目录**下创建 `.trae/rules/`（如 `frontend-module/.trae/rules/`），仅在相关文件被读取/提及时生效
- 支持 `globs`（指定文件生效）、`description`（智能生效）、`scene: git_message`（提交信息规则）

**当前项目的状态**：草稿把规则拆分为 3 个文件（`project_rules.md`、`agent_review_rules.md`、`multi_agent_rules.md`），但全部平铺在 `.trae/rules/` 根目录下。如果规则继续增长，可以考虑：
- 用子文件夹归类（如 `core/`、`review/`、`collaboration/`）
- 用 `globs` 让代码规范只作用于 `.py` 文件
- 用 `scene: git_message` 规范 AI 生成的 commit message

**这不是紧急问题**，但属于"可用但未用"的设计机会。

---

### Q5：草稿关于"Hook 无法访问 agent 会话历史"的判断是否仍然成立？

**草稿中的判断**（第 4.3 节）："Hook 无法访问 agent 会话历史——无法判断'本次会话是否调用过 architecture-critic'"

**验证结果**：这个判断**仍然成立**。官方文档确认：
- `stdin` 只提供 `session_id`、`cwd`、`hook_event_name`、`workspace_roots` 等通用字段
- 没有 `transcript` 或 `conversation_history` 字段
- 虽然 `SessionStart` 支持向 `$TRAE_ENV_FILE` 写入环境变量，但环境变量是**跨进程持久化**的，不是跨 Hook 调用的"状态机"

**但是**，草稿低估了 `PreToolUse` 的 `additionalContext` 能力。官方文档确认 `PreToolUse` 可以返回 `additionalContext` 给模型——这意味着 Hook 虽然不能"记住"之前调过什么，但可以在**当前拦截点**给模型注入即时上下文。例如：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "additionalContext": "规则提醒：修改 models.py 前，请确认已调用 architecture-critic。如果已调用，请继续；如果未调用，请先在回复中说明理由。"
  }
}
```

这比草稿中设想的"无条件提示"更有力——它直接给模型注入了行为指导，而不是简单地打印一行文字。

---

## 四、风险矩阵（P 级）

| 风险 | 等级 | 说明 | 建议应对 |
|------|------|------|----------|
| 按草稿格式写入 `hooks.json` 后 Hook 不被识别 | **P1** | 配置格式结构性错误，最直接的后果是 Hook 不工作 | 立即按官方格式重写示例；在 IDE 中实际创建测试 Hook 验证 |
| PreToolUse 脚本示例无效（不阻止、不提示） | **P1** | 脚本缺少 `exit 2` 或正确 JSON 输出，Hook 形同虚设 | 重写脚本示例，明确区分"ask"（弹确认）和"deny"（拒绝）两种模式 |
| 团队基于错误格式编写后续 Hook | **P2** | 如果团队成员把草稿当模板，后续所有 Hook 都可能继承错误格式 | 在草稿中明确标注"Hooks 格式待验证"，并在验证后更新所有引用 |
| 未利用 Rules 新特性导致规则可维护性下降 | **P2** | 规则文件增多后无分类、无文件级作用域 | 评估是否需要引入 `globs` 和子目录规则来管理增长 |
| 未考虑 `Notification` 事件导致通知自动化缺失 | **P3** | 如果未来想实现"任务完成自动通知"，缺少最合适的事件选项 | 在团队知识库中补充 `Notification` 事件，暂不实施 |

---

## 五、建议与行动清单（P0-P3）

| 优先级 | 行动项 | 改动范围 | 估计工作量 | 验证方式 |
|--------|--------|----------|-----------|----------|
| **P0** | 重写 `hooks.json` 配置示例，严格按官方格式（`version` + 嵌套 `hooks` 数组） | `开发日志/Subagent与规则改进建议.md` 第 4.2 节 | < 1h | 在 Trae IDE 中创建测试项目，写入官方格式，检查"已配置的 Hooks"列表是否识别 |
| **P0** | 重写 `pre_edit_models_py_guard.py` 脚本示例，使用官方 `hookSpecificOutput` JSON 或 `exit 2` | 同上 | < 1h | 手动运行脚本测试 stdin/stdout 行为 |
| **P1** | 在草稿的 Hook 章节开头增加"格式验证声明"："本节的 hooks.json 格式基于 Trae 官方文档（2026-06-14），如发现与 IDE 实际行为不一致，以 IDE 为准" | 文档注释 | < 10min | — |
| **P1** | 补充 `Notification` 事件到事件类型表中 | `开发日志/Subagent与规则改进建议.md` 第 4.1 节 | < 10min | 对照官方文档确认 |
| **P1** | 将工具名 `Bash` 更正为 `RunCommand`（官方标准化名称） | 草稿中所有提到 `Bash` 的位置 | < 10min | 对照官方工具名列表 |
| **P2** | 评估是否需要用 `globs` 或子目录规则来组织 growing 的 rules 文件 | `.trae/rules/` 目录结构 | 讨论后决定 | 规则数量 > 5 个时建议实施 |
| **P2** | 考虑用 `additionalContext` 增强 `pre-edit-models-py-guard` 的提示力度（从"打印文字"升级为"给模型注入行为指导"） | Hook 脚本设计 | < 1h | 实测对比两种方式的模型响应差异 |
| **P3** | 调研 `scene: git_message` 是否可用于规范 AI 生成的 commit message | `.trae/rules/` 新增文件 | 1-2h | 在 git 提交时观察 AI 行为变化 |
| **P3** | 关注 Trae 官方文档更新，特别是 `type` 字段未来是否支持 `http`/`mcp_tool` 等扩展 | 长期跟踪 | 持续 | 定期检查 docs.trae.cn |

---

## 六、已确认的事实与已修正的判断

| 原判断（草稿） | 实际情况 | 修正 |
|--------------|----------|------|
| Trae Hooks 支持 5 种事件 | 支持 **6 种**（新增 `Notification`） | 补充 `Notification` 事件 |
| `hooks.json` 格式包含 `name`/`enabled`/`description` | **不存在**这些字段，启停通过 IDE 界面控制 | 删除这些字段，按官方格式重写 |
| PreToolUse 拦截通过 `stderr` 打印 + `exit 0` | 正确方式是 `exit 2` 或 `stdout` 返回 `hookSpecificOutput` JSON | 重写脚本示例 |
| Hook 是"提示+记录"机制，非强制阻断 | 部分正确。`PreToolUse` 可以通过 `"permissionDecision": "deny"` 或 `exit 2` **强制阻断**工具执行；`Stop` 可以通过 `"decision": "block"` 强制继续执行。说"非强制"是过度简化 | 修正描述，区分不同事件的阻断能力 |
| `Bash` 是工具名 | 官方标准化名称是 `RunCommand` | 更正工具名 |
| 草稿未提及 `version` 字段 | 官方格式有 `version: 1`（默认值） | 补充 |
| 草稿未提及 `timeout` 字段 | 官方默认 30 秒 | 补充 |
| 草稿未提及 `type` 字段 | 官方默认 `"command"`，当前仅支持 `command` | 补充 |
| Hook 无法给模型注入上下文 | **可以**。`PreToolUse` 支持 `additionalContext` 返回给模型 | 修正判断，更新脚本设计 |
| 草稿引用掘金文章（2026-06-15）作为主要来源 | 官方文档（2026-06-14）更权威。掘金文章是社区经验，在官方文档发布后应以官方为准 | 优先引用官方文档 |

---

## 七、留给团队的核心提问

1. **Hook 实际测试了吗？** 草稿中所有 Hook 建议都标注了"可行性"，但没有提到是否已在实际 Trae 环境中写入 `hooks.json` 并观察行为。如果还没测试，P0 行动项的验证方式就是首次实测。

2. **`pre-edit-models-py-guard` 的意图是"提示"还是"拦截"？** 草稿的描述在两者之间摇摆：说"无条件提示"但又放在 `PreToolUse`（拦截能力最强的事件）中。如果意图是"提示不拦截"，也许 `PostToolUse`（事后检查）更合适；如果意图是"拦截"，则应使用 `"permissionDecision": "ask"` 或 `"deny"`。

3. **Rules 的拆分策略是否对标了 Trae 的多层嵌套？** 当前拆成 3 个文件（`project_rules`、`agent_review_rules`、`multi_agent_rules`）是基于内容主题的拆分，但 Trae 的 `.trae/rules/` 支持子文件夹。如果未来规则继续增长（如新增 `commit_rules`、`security_rules`），是否考虑过用子文件夹归类而不是继续平铺？

4. **Claude Code 的 Hook 配置是否也在使用？** Trae 支持读取并合并 Claude Code 的 `settings.json` 中的 `hooks` 配置。如果团队同时用 Claude Code 和 Trae，是否有意利用这个兼容性来共享 Hook 逻辑？

5. **沙箱运行 vs 本地自动运行的安全权衡？** Trae 官方提供两种运行方式，草稿完全没有提及。如果 Hook 脚本需要读取项目外的文件（如全局日志目录），沙箱可能限制其功能；如果选择本地自动运行，则需要评估安全风险。这个决策是否已有结论？

---

*评议依据：Trae IDE 官方文档（docs.trae.cn，2026-06-11/12/14）+ 社区实测（腾讯云 OODER A2UI 团队，2026-06-15）+ 子代理交叉验证（2026-06-27）*
