# Trae IDE Hooks 配置格式验证报告

> 验证日期：2026-06-27
> 验证范围：Trae IDE 官方 hooks.json 配置格式、Claude Code 兼容性、Hook 运行安全机制
> 验证方式：kimi_search_v2 + kimi_fetch_v2 交叉验证官方文档

---

## 一、已确认事实

### 1.1 Hook 事件类型（6 种）✓ 确认

| 事件名 | 触发时机 | 官方文档 |
|--------|----------|----------|
| `SessionStart` | 创建 Session 后、发起第一个对话之前 | 确认 |
| `UserPromptSubmit` | 用户发送消息后、智能体开始处理前 | 确认 |
| `PreToolUse` | 智能体发起工具调用后、实际执行前 | 确认 |
| `PostToolUse` | 工具调用实际执行完成后 | 确认 |
| `Stop` | 智能体完成输出、准备结束当前查询时 | 确认 |
| `Notification` | 工具调用等待用户确认时，或智能体完成任务时 | 确认 |

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.2 配置文件位置 ✓ 确认

| Hook 类型 | macOS & Linux | Windows | 作用范围 |
|-----------|---------------|---------|----------|
| 全局 Hook | `~/.trae-cn/hooks.json` | `%userprofile%/.trae-cn/hooks.json` | 对本机当前用户下所有工作区生效 |
| 项目 Hook | `$PROJECT_FOLDER/.trae/hooks.json` | — | 仅对当前项目或工作区生效 |

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.3 官方配置格式 ✓ 确认

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

**字段说明（全部确认）：**

- `version`：`number`，非必填，默认 `1`，当前仅支持 `1`
- `hooks`：`object`，必填，事件名到 Hook 组列表的映射
- `matcher`：`string`，非必填，支持正则表达式（如 `Edit|Write`、`mcp.*`），配置为 `*`、空字符串或省略时匹配所有工具/通知类型。仅对 `PreToolUse`、`PostToolUse`、`Notification` 有效
- `loop_limit`：`number`，非必填，仅对 `Stop` 事件有效，默认 `5`
- `hooks`（数组内）：`array`，必填，该组下要执行的 Hook 列表
- `type`：`string`，非必填，默认 `command`，**当前仅支持 `command`**
- `command`：`string`，必填，要执行的 Shell 命令
- `timeout`：`number`，非必填，默认 `30`（秒）

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.4 PreToolUse stdout 输出格式 ✓ 确认

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask",
    "permissionDecisionReason": "...",
    "updatedInput": { ... },
    "additionalContext": "附加给模型的上下文"
  }
}
```

**额外确认：**
- `permissionDecision` 优先级：多个 `PreToolUse` Hook 并行执行时，`deny` → `ask` → `allow`
- `updatedInput`：修改后的工具输入参数，将**整体覆盖替换**原始参数（非合并更新）
- 即使返回 `allow`，若工具运行模式为手动确认，仍需用户确认

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.5 exit code 2 的行为 ✓ 确认（但有事件差异）

| 事件 | exit code 2 行为 |
|------|------------------|
| `PreToolUse` | 等价于 `"permissionDecision": "deny"`，stderr 作为原因附加给模型 |
| `UserPromptSubmit` | 等价于 `"decision": "block"`，stderr 内容展示给用户 |
| `Stop` | 等价于 `"decision": "block"`，stderr 作为新 Query 让智能体继续执行 |
| `SessionStart` | 不影响会话流程 |
| `PostToolUse` | 将 stderr 传递给模型上下文 |
| `Notification` | 任意退出码均视为非阻断性，stdout/stderr/退出码均不影响流程 |

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.6 支持的工具名 ✓ 确认

| 分类 | 工具名 |
|------|--------|
| 文件读取 | `Read` |
| 文件写入 | `Write` |
| 文件编辑 | `Edit` |
| 搜索 | `Glob`, `Grep`, `LS` |
| 终端 | `RunCommand` |
| 网络 | `WebSearch`, `WebFetch` |
| 交互 | `AskUserQuestion` |
| Skill | `Skill` |
| MCP | `mcp__<serverName>__<toolName>`（注意：双下划线） |

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.7 新增确认：stdout 通用流程控制字段 ✓

所有事件均支持以下通用字段（JSON 输出）：

```json
{
  "continue": true,
  "stopReason": "string"
}
```

- `continue`：默认 `true`，设为 `false` 时智能体停止执行。优先于任何事件特定 `decision` 字段
- `stopReason`：`continue` 为 `false` 时展示给用户的停止原因

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.8 新增确认：stdin 通用字段 ✓

```json
{
  "session_id": "string",
  "cwd": "/path/to/workspace",
  "hook_event_name": "PreToolUse",
  "workspace_roots": ["/path/to/workspace"]
}
```

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.9 新增确认：环境变量注入机制 ✓

`SessionStart` 事件支持向 `$TRAE_ENV_FILE` 写入环境变量，格式支持：
- Bash 格式：`export NODE_ENV=production`
- PowerShell 格式：`$env:NODE_ENV=production`
- Dotenv 格式：`NODE_ENV=production`

注入的变量在后续 Hook 执行和 `RunCommand` 工具调用中生效，不影响当前 `SessionStart` Hook 进程。

同时兼容 `$CLAUDE_ENV_FILE`。

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.10 新增确认：运行方式（安全机制）✓

Hook 命令的实际权限取决于设置：
- **沙箱运行**：Hook 在沙箱中自动执行，文件访问和系统权限受沙箱限制
- **本地自动运行**：Hook 在沙箱外自动执行，可访问本地环境，存在更高安全风险

注意：此运行方式设置通过 Trae IDE 设置界面控制，**非 `hooks.json` 配置字段**。

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 1.11 新增确认：执行环境 ✓

- **Shell**：macOS/Linux 默认 Bash，Windows 默认 PowerShell
- **工作目录**：全局 Hook 在第一个工作区根目录；项目 Hook 在配置文件所在项目根目录
- **环境变量**：`TRAE_PROJECT_DIR`（工作区目录），兼容 `CLAUDE_PROJECT_DIR`

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

---

## 二、与草稿的差异

### 2.1 用户提供的配置格式基本准确，但存在以下遗漏/差异：

| 项目 | 草稿内容 | 官方实际情况 | 差异类型 |
|------|----------|-------------|----------|
| `type` 字段 | 草稿中未提及 | 默认 `command`，当前仅支持 `command` | 遗漏 |
| exit code 2 | 统一描述为 "等价于 deny" | 不同事件行为不同（PreToolUse=deny, UserPromptSubmit=block, Stop=block, SessionStart=不影响, PostToolUse=传stderr, Notification=忽略） | 过度简化 |
| `updatedInput` 行为 | 仅列出字段 | 明确为**整体覆盖替换**原始参数，非合并更新 | 遗漏 |
| 通用 stdout 字段 | 未提及 | 所有事件支持 `continue` + `stopReason` | 遗漏 |
| 通用 stdin 字段 | 未提及 | `session_id`, `cwd`, `hook_event_name`, `workspace_roots` | 遗漏 |
| 环境变量注入 | 未提及 | `$TRAE_ENV_FILE` / `$CLAUDE_ENV_FILE` 机制 | 遗漏 |
| 运行方式/安全 | 未提及 | 沙箱运行 vs 本地自动运行 | 遗漏 |
| 运行 Shell | 未提及 | macOS/Linux=Bash, Windows=PowerShell | 遗漏 |
| 工作目录 | 未提及 | 全局 Hook 在第一个工作区，项目 Hook 在配置所在项目根目录 | 遗漏 |
| `loop_limit` 限制 | 列出字段 | 明确仅对 `Stop` 事件有效 | 遗漏 |
| `matcher` 限制 | 列出字段 | 明确仅对 `PreToolUse`/`PostToolUse`/`Notification` 有效 | 遗漏 |
| Claude Code 兼容 | 未提及 | Trae 支持读取 Claude Code 配置并合并执行 | 遗漏 |

### 2.2 草稿中无错误字段

经交叉验证，用户提供的配置结构、事件类型、支持工具名、PreToolUse stdout 格式本身**无错误**，均为准确信息。差异主要集中在**遗漏和简化**上。

---

## 三、Claude Code Hooks 兼容性分析

### 3.1 Trae 对 Claude Code 配置的支持 ✓ 确认

Trae 官方文档明确声明：
> "TRAE 支持读取 Claude Code 中的 Hook 配置，并合并执行。"

Claude Code 配置路径：
- 全局：`~/.claude/settings.json`
- 项目：`$PROJECT_FOLDER/.claude/settings.json` / `$PROJECT_FOLDER/.claude/settings.local.json`

当多个配置文件共存时，Trae 会读取所有已启用的 Hook 配置并合并执行。

来源：`https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）

### 3.2 Claude Code 的 hooks 格式差异

Claude Code 的 `settings.json` 中 `hooks` 字段格式与 Trae 的 `hooks.json` 结构**基本一致**（均使用 `hooks.<EventName> → matcher → hooks` 层级），但存在以下差异：

| 特性 | Claude Code | Trae |
|------|-------------|------|
| Hook 类型 | `command`, `http`, `mcp_tool`, `agent`, `prompt` | **仅 `command`** |
| 顶层字段 | 支持 `description`（plugin 中） | **无** |
| 配置字段 | `settings.json` 含 `model`, `permissions`, `env`, `mcpServers` 等大量非 hook 字段 | `hooks.json` 仅含 `version` + `hooks` |
| 占位符 | 支持 `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}` | 支持 `TRAE_PROJECT_DIR`，兼容 `CLAUDE_PROJECT_DIR` |
| 事件类型 | 更多（如 `Setup`, `PostToolUseFailure`） | 6 种 |

### 3.3 `name`, `enabled`, `description` 字段结论

经交叉验证：

- **Trae 的 `hooks.json` 中不存在 `name`, `enabled`, `description` 字段**
- Trae 通过 IDE 设置界面的开关来启用/禁用 Hook，而非配置文件字段
- 当 Trae 读取 Claude Code 的 `settings.json` 时，只会提取 `hooks` 字段进行合并。Claude Code 的 `settings.json` 本身也没有 `name`/`enabled` 在 hook 组层面的定义（只有顶层 `enabledPlugins`）。因此：
  - ✅ `hooks` 结构可兼容
  - ❌ `description` 等顶层字段会被忽略（无文档说明）
  - ❌ `http`/`mcp_tool`/`agent`/`prompt` 类型不被 Trae 支持

来源：
- `https://docs.trae.cn/ide_hook-configuration-reference`（2026-06-14）
- `https://code.claude.com/docs/en/hooks`（2025-09-01）
- `https://github.com/tanweai/pua/blob/main/docs/FAQ.md`（2026-03-08）—— "Trae / Pi 都不继承 Claude Code hooks"

---

## 四、未确认 / 需要进一步验证的事项

### 4.1 高优先级

1. **Claude Code `description` 字段读取行为**：当 Trae 读取 Claude Code 的 plugin `hooks.json`（含顶层 `description`）时，是否会忽略该字段，还是会导致解析失败？官方文档未明确说明非标准字段的处理方式。

2. **Hook 沙箱的具体技术实现**：官方文档提到"沙箱运行"和"本地自动运行"，但未说明沙箱的具体技术实现（如是否使用 Docker、容器、chroot、seccomp 等）。社区反馈显示 TRAE SOLO 存在"设置沙箱外自动运行后仍然在沙箱内执行"的已知问题（2026-05-15）。

3. **Notification 事件 matcher 的精确匹配规则**：`matcher` 在 Notification 中匹配 `notification_type`，但正则表达式是否支持完整 PCRE 语法，或仅支持子集？未明确说明。

### 4.2 中优先级

4. **多项目 Hook 合并的冲突解决策略**：当多个项目根目录都有 `hooks.json` 时，官方说"合并执行"，但同名事件、同 matcher 的 Hook 组执行顺序是否确定？未明确。

5. **Claude Code `settings.json` 的 `allowManagedHooksOnly` 等字段**：当 Trae 读取 Claude Code 的 `settings.json` 时，是否也会处理 `permissions.allow`/`permissions.deny` 等字段，还是仅提取 `hooks`？目前无证据表明 Trae 会处理非 `hooks` 字段。

6. **`updatedInput` 的验证机制**：`updatedInput` 会整体替换原始参数，但 Trae 是否会对修改后的参数进行 schema 验证？如果修改后的参数不满足工具的 JSON Schema 要求，是否会触发错误？官方文档未提及。

### 4.3 低优先级

7. **Hook 执行的超时传播**：当 `timeout` 设置时，如果 Hook 在超时前输出部分结果，这部分结果是否会被处理？还是整个 Hook 被 kill 后所有 stdout 被忽略？未明确。

8. **Windows 下的 PowerShell 执行策略**：官方示例使用 `powershell -ExecutionPolicy Bypass`，但这是否意味着默认执行策略可能限制 Hook 运行？文档未明确说明默认行为。

---

## 五、来源列表

| # | URL | 日期 | 说明 |
|---|-----|------|------|
| 1 | `https://docs.trae.cn/ide_hook-configuration-reference` | 2026-06-14 | **Trae 官方 Hook 配置参考文档**，最权威来源。涵盖配置格式、字段说明、事件详情、I/O 规范、执行环境、工具列表和示例。 |
| 2 | `https://docs.trae.cn/ide_automate-actions-with-hooks` | 2026-06-12 | Trae 官方 Hook 入门指南，说明如何通过 IDE 界面创建和管理 Hook。 |
| 3 | `https://code.claude.com/docs/en/hooks` | 2025-09-01 | Claude Code 官方 Hooks 参考文档，用于对比 Claude Code 的扩展功能（http, mcp_tool, agent, prompt）。 |
| 4 | `https://github.com/tanweai/pua/blob/main/docs/FAQ.md` | 2026-03-08 | pua 项目 FAQ，提到 "Trae / Pi 都不继承 Claude Code hooks"，用于验证兼容性的边界。 |
| 5 | `https://github.com/Trae-AI/TRAE/issues/2436` | 2026-04-04 | Trae GitHub Feature Request，提供了 Hooks 生态对比和上下文，确认这是行业通用模式。 |
| 6 | `https://forum.trae.cn/t/topic/17779` | 2026-05-15 | TRAE SOLO 社区论坛帖子，反映沙箱/本地运行模式切换存在已知问题。 |
| 7 | `https://code.claude.com/docs/en/settings` | 2025-09-01 | Claude Code 官方 Settings 文档，说明 `settings.json` 的完整字段，用于对比 Trae 的读取范围。 |

---

## 六、总结

**结论：用户提供的信息基本准确，核心配置格式（6 事件、配置文件路径、hooks.json 结构、PreToolUse stdout 格式、exit code 2 行为）均与官方文档一致。**

主要差异点：
1. **exit code 2 行为**被过度简化为统一 "deny"，实际各事件行为不同
2. **大量遗漏**：通用 stdout/stdin 字段、环境变量注入、运行方式（沙箱/本地）、工作目录、Shell 环境等
3. **Claude Code 兼容性**：Trae 支持读取并合并 Claude Code 的 `hooks` 配置，但仅支持 `command` 类型，不支持 Claude Code 的 `http`/`mcp_tool`/`agent`/`prompt` 扩展类型
4. **`name`/`enabled`/`description`**：这些字段在 Trae 的 `hooks.json` 中不存在，Trae 通过 IDE 设置界面控制启用/禁用

建议：在编写 `.trae/hooks.json` 时，严格遵循 Trae 官方格式（`version` + `hooks` 对象），不要混入 Claude Code 的扩展字段。如需同时支持两者，可将共享逻辑抽取为独立脚本，两边均通过 `type: command` 调用。
