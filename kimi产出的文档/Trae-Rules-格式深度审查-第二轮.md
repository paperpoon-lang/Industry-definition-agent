# Trae Rules 格式深度审查 — 第二轮同行评议意见

> **角色**：行业定义 Agent 项目同行评议专家
> **评议对象**：`.trae/rules/project_rules.md`（已部署）+ `草稿_rules/*.md`（三个拆分文件）+ `project_rules_v1.3_草稿.md`（根目录草稿）
> **评议日期**：2026-06-27
> **评议依据**：Trae IDE 官方文档（docs.trae.cn/ide_rules，2026-06-11）+ 实际文件内容对比
> **与上一轮的关系**：这是聚焦 Rules 的第二轮审查，上一轮（Hooks）的结论已部分采纳，但 Rules 被遗漏

---

## 一、总体判断

**Rules 的核心问题只有一个，但很严重：所有规则文件都缺少 YAML frontmatter。这意味着它们被放在 `.trae/rules/` 下，但 Trae 很可能无法正确识别为规则文件，或者识别后属性缺失（如 `alwaysApply` 不生效）。**

这不是"内容写得不够好"，而是"文件格式根本不对"——类似于把 Python 代码保存成 `.txt` 后缀，文件内容写得再好也跑不起来。

---

## 二、文件部署现状（实测检查）

我在 `.trae/rules/` 和 `草稿_rules/` 下做了实际文件检查，发现以下状态：

| 文件 | 位置 | 状态 | 版本 | 问题 |
|------|------|------|------|------|
| `project_rules.md` | `.trae/rules/`（已部署） | ✅ 存在 | **v1.2**（旧版） | ① 缺少 YAML frontmatter<br>② 规则 9 阈值仍为 100 行（v1.3 应改为 80）<br>③ 无规则 11、12（v1.3 新增） |
| `agent_review_rules.md` | 仅在 `草稿_rules/` | ❌ 未部署 | v1.3 | 缺少 YAML frontmatter；`> alwaysApply。` 在引用块中 |
| `multi_agent_rules.md` | 仅在 `草稿_rules/` | ❌ 未部署 | v1.3 | 缺少 YAML frontmatter；`> alwaysApply。` 在引用块中 |
| `project_rules.md`（精简版） | 仅在 `草稿_rules/` | ❌ 未部署 | v1.3 | 缺少 YAML frontmatter |
| `project_rules_v1.3_草稿.md` | 项目根目录 | ❌ 不在 `.trae/rules/` 下 | v1.3 | 缺少 YAML frontmatter |

**关键发现**：
1. `.trae/rules/` 下**只有 v1.2 的旧版** `project_rules.md`，没有更新到 v1.3
2. `agent_review_rules.md` 和 `multi_agent_rules.md` **从未部署到 `.trae/rules/`**，所以 Trae 根本没有加载它们
3. 即使已部署的 `project_rules.md`（v1.2），也**缺少 YAML frontmatter**，格式不完整

---

## 三、核心问题：YAML frontmatter 缺失

### 3.1 什么是 YAML frontmatter，为什么重要

Trae 官方文档（`docs.trae.cn/ide_rules`）明确规则文件的格式：

> "在 `---` 下方，使用 Markdown 语法添加规则的内容。"

同时给出示例：

```markdown
---
scene: git_message
---
正文：生成提交内容时应遵守的规范
```

这说明 Trae 的规则文件格式是 **YAML frontmatter + Markdown 内容**：
- `---` 上方（或第一个 `---` 之前）是 YAML 属性区（如 `alwaysApply`, `description`, `globs`）
- `---` 下方是 Markdown 正文内容

**Trae 读取规则时，会先把文件开头到第一个 `---` 之间的内容当作 YAML 解析**，提取规则属性，然后再解析 `---` 下方的 Markdown 作为规则内容。

### 3.2 草稿文件的实际格式（错误）

以 `project_rules.md`（已部署到 `.trae/rules/`）为例：

```markdown
# 行业定义 Agent — 项目规则

> 对 Trae（AI 助手）的行为约束。每次任务自动加载。

---

## 规则 1：事实性数据必须带来源
...
```

**Trae 解析器看到的**：
1. 尝试把文件开头到第一个 `---` 之间的内容解析为 YAML frontmatter：
   ```yaml
   # 行业定义 Agent — 项目规则

   > 对 Trae（AI 助手）的行为约束。每次任务自动加载。
   ```
2. 这段 YAML 是**无效的**：
   - `# 行业定义...`：在 YAML 中 `#` 是注释，但后面没有有效的键值对，解析器可能报空文档或错误
   - `> 对 Trae...`：`>` 在 YAML 中不是合法的键名，会触发解析错误

3. 结果：
   - **最可能**：YAML 解析失败，frontmatter 被丢弃，Trae 把 `---` 下方的内容当作规则正文读取，但**没有 `alwaysApply` 属性**
   - **次可能**：如果解析器更宽容，frontmatter 被当作空，只读取正文内容，但同样**没有属性**

### 3.3 `agent_review_rules.md` 和 `multi_agent_rules.md` 的额外问题

这两个文件的开头更奇怪：

```markdown
> alwaysApply。规范何时、如何调用审查类 Agent...

---

## 规则 9：质量门
```

**Trae 解析器尝试把 `> alwaysApply。规范...` 解析为 YAML frontmatter**。`>` 在 YAML 中表示折叠标量（folded scalar），但 `alwaysApply` 不是合法的键名结构（缺少 `:` 分隔符），所以这段 YAML 也会解析失败。

### 3.4 正确的格式应该是什么

参考官方文档中 IDE 自动创建规则的格式（推测），正确的格式应该是：

```markdown
---
alwaysApply: true
---
# 行业定义 Agent — 项目规则

> 对 Trae（AI 助手）的行为约束。每次任务自动加载。

## 规则 1：事实性数据必须带来源
...
```

或者，对于 `agent_review_rules.md`：

```markdown
---
alwaysApply: true
---
# 行业定义 Agent — 纠错 Agent 调用规则

> 规范何时、如何调用审查类 Agent...

## 规则 9：质量门
...
```

这样：
- `---` 上方是有效的 YAML：`alwaysApply: true`
- `---` 下方是 Markdown 正文，Trae 正确解析为规则内容

---

## 四、v1.2 vs v1.3 的内容差异（同步问题）

`.trae/rules/project_rules.md` 是 **v1.2**（2026-06-18），但你的 v1.3 草稿已经做了多项修改。两者差异：

| 项 | v1.2（已部署） | v1.3（草稿） | 状态 |
|---|---|---|---|
| 规则 9 阈值 | 100 行 | 80 行 | 草稿已改，未部署 |
| 规则 10.1 | 无行数说明 | 明确">80 行" | 草稿已改，未部署 |
| 规则 10.2 | 只说"最小调用测试" | 明确 Mock + 真实 API 双重要求 | 草稿已改，未部署 |
| 规则 10.3 | 存在 | 行数阈值改为 80 | 草稿已改，未部署 |
| 规则 10.4 | **不存在** | **新增** agent 推荐路由表 | 草稿已改，未部署 |
| 规则 11 | **不存在** | **新增** 去偏见化 | 草稿已改，未部署 |
| 规则 12 | **不存在** | **新增** 多 agent 仲裁 | 草稿已改，未部署 |
| 文件拆分 | 单文件 | 拆分为 3 个文件 | 草稿已拆，未部署 |

**结论**：v1.3 的内容改进虽然已完成，但从未同步到 `.trae/rules/`。Trae 实际加载的是旧版 v1.2。

---

## 五、其他发现（次要但值得注意）

### 5.1 `project_rules_v1.3_草稿.md` 在根目录下，不在 `.trae/rules/` 下

这个文件是 v1.3 的完整版（296 行），但放在项目根目录。如果用户希望它作为规则被 Trae 加载，需要移动到 `.trae/rules/` 下。但即使移动了，也需要修正 YAML frontmatter。

### 5.2 版本历史标注在正文尾部

草稿文件尾部有：
```markdown
*规则版本：v1.3（草稿） | 生效日期：待审批*
```

这个标注在 Markdown 正文中。如果规则被 Trae 加载，每次对话时这段文本都会被注入上下文。这在语义上没有问题，但值得确认这是你的意图（作为规则文件的一部分被 AI 读取）。

### 5.3 规则编号不连续

`project_rules.md`（精简版）有规则 1-8，`agent_review_rules.md` 有规则 9-10，`multi_agent_rules.md` 有规则 11-12。拆分后三个文件的规则编号合在一起是连续的，但单独看每个文件时编号跳跃。这本身不是格式问题，但如果 Trae 独立加载每个文件，AI 可能会困惑"为什么规则从 9 开始"或"规则 1-8 在哪里"。建议在拆分文件中保留一个简短的注释说明。

---

## 六、修正方案（建议）

### 6.1 格式修正（必须）

所有规则文件必须在文件开头添加 YAML frontmatter：

```markdown
---
alwaysApply: true
---
```

然后才是标题和正文。例如：

```markdown
---
alwaysApply: true
---
# 行业定义 Agent — 核心行为约束

> 对 Trae（AI 助手）的行为约束。每次任务自动加载。
> 适用于所有对话场景。

## 规则 1：事实性数据必须带来源
...
```

### 6.2 部署修正（必须）

将三个文件从 `草稿_rules/` 复制到 `.trae/rules/`：

```
.trae/rules/
├── project_rules.md          ← 覆盖旧版 v1.2（新版 v1.3 精简版）
├── agent_review_rules.md     ← 新部署（目前未部署）
└── multi_agent_rules.md      ← 新部署（目前未部署）
```

注意：`.trae/rules/` 下已有旧版 `project_rules.md`，需要被覆盖。

### 6.3 验证步骤（建议）

1. 在 Trae IDE 中打开规则设置面板（设置 → 规则），确认文件是否被识别
2. 检查"已配置的规则"列表中是否出现三个规则文件
3. 在 IDE 中打开其中一个文件，确认 `alwaysApply` 字段显示为"始终生效"
4. 如果没有，检查文件开头的 YAML 格式是否正确（注意空格、缩进）

### 6.4 备选：用 IDE 创建规则来验证格式

如果不确定手动写的 frontmatter 是否正确，可以在 Trae IDE 中：
1. 设置 → 规则 → 创建 → 项目
2. 输入任意规则名称，选择"始终生效"
3. 观察 IDE 自动在文件中生成的格式
4. 对比你的手动写法，修正差异

---

## 七、风险矩阵

| 风险 | 等级 | 说明 | 应对 |
|------|------|------|------|
| 规则文件放在 `.trae/rules/` 下但 frontmatter 缺失，导致不被识别 | **P1** | 文件存在但规则不生效，用户以为规则在约束 AI 行为，实际没有 | 立即添加 YAML frontmatter |
| v1.3 规则从未部署，Trae 仍加载旧版 v1.2 | **P1** | 新规则（去偏见化、多 agent 仲裁等）未生效 | 将三个文件复制到 `.trae/rules/` 并覆盖旧版 |
| `agent_review_rules.md` 和 `multi_agent_rules.md` 从未被加载 | **P1** | 两个文件只在 `草稿_rules/` 下，Trae 规则引擎看不到它们 | 部署到 `.trae/rules/` |
| 规则编号跳跃导致 AI 困惑 | **P3** | 拆分文件中编号不连续（9-10, 11-12） | 添加注释说明或重新编号 |

---

## 八、留给团队的提问

1. **你是手动把文件放到 `.trae/rules/` 下的，还是通过 IDE 的"创建规则"功能？** 如果是手动放的，那 frontmatter 问题就是我上面分析的那样。如果是通过 IDE 创建的，IDE 应该自动添加了 frontmatter，那文件可能已经被覆盖过。

2. **你通过 Trae IDE 的规则设置面板能看到这三个文件吗？** 如果在设置 → 规则列表中能看到，说明文件被识别了；如果看不到，说明格式问题导致被忽略。这是最直接验证我判断是否正确的方式。

3. **规则拆分后，你是否希望 AI 同时看到三个文件？** 如果三个文件都被正确加载，每次对话时 AI 会同时收到三个文件的上下文。这在你的设计意图中吗？还是你只想让 AI 在特定场景下看到特定文件（如"产出 >80 行 md 时"才看到 `agent_review_rules.md`）？

---

*评议依据：Trae IDE 官方文档（docs.trae.cn/ide_rules，2026-06-11）+ 实际文件系统检查（`.trae/rules/` 和 `草稿_rules/` 目录）*

*核心判断：Rules 不是"内容不够好"，而是"文件格式（YAML frontmatter）完全缺失"——这个问题比 Hooks 的格式问题更严重，因为文件在目录下但可能不被解析。这解释了"改完了但还觉得有问题"的感受。*
