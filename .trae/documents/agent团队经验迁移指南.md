# Agent 团队经验迁移指南 — 生成计划

> 任务：把当前行业定义 agent 项目的成功经验总结成一份 markdown，迁移到 YOLOpose 科研优化项目，让新 agent 拿这份文档 + 项目文件夹定制出 agent 团队结构、subagent 提示词、rules、hooks。
>
> 文档定位：纯经验总结 + 模板（让新 agent 自己根据 YOLOpose 项目定制）
>
> 项目性质：YOLOpose 是纯科研项目（论文复现、消融实验、超参搜索、论文撰写）
>
> 规范查证：本地为主 + Trae 官网补充，官网信息必须由 subagent 核查正确性和最新性

---

## Phase 1 探索结论（已完成）

### 当前项目的成功经验形态

通过探索 `.trae/` 目录、`开发日志/Subagent与规则改进建议.md`、`project_rules.md`、hooks 实现、方法论文件、架构设计文档，确认本项目采用 **"规则驱动 + 全局 agent 引用"** 模式：

1. **项目仓库内只存三类配置**：
   - `.trae/rules/project_rules.md`（v1.3，203 行，12 条规则）
   - `.trae/hooks.json` + `.trae/hooks/pre_edit_models_py_guard.py`（PreToolUse ask 模式守卫）
   - `.trae/documents/`（实施计划文档）
2. **Subagent 定义不在项目内**：7 个专用 agent（architecture-critic、ai-architecture-fact-checker、agent-code-validator、methodology-expert、definition-quality-checker、python-backend-implementer、frost-test-runner）均为全局/用户级，通过 rules 中的"推荐路由表"按名称引用
3. **配套机制**：方法论拆分（`_meta.yaml` + `hard_rules.md` + `heuristics.md` + `self_check.md` + `methodology_full.md`）、6 步编排主文件（frost_agent.py，trace_id 注入 + quality_flags + SessionEventLog + TokenAudit + CheckpointManager）、Kimi 同行评议、开发日志文化

### Trae 官方规范要点（已查证）

| 配置类型 | 位置 | 格式 | 关键字段/能力 |
|---------|------|------|--------------|
| **Rules** | 项目级 `.trae/rules/`；全局 `~/.trae-cn/` | Markdown + YAML frontmatter | `alwaysApply`/`description`/`globs`/`scene`；4 种生效方式；3 层嵌套；兼容 AGENTS.md/CLAUDE.md |
| **Hooks** | 项目级 `$PROJECT/.trae/hooks.json`；全局 `~/.trae-cn/hooks.json` | JSON | `version:1` + 6 事件（SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/Stop/Notification）+ `matcher`/`loop_limit`/`hooks[]`；stdin JSON + stdout JSON/纯文本；退出码 0/2/其他；沙箱/本地运行 |
| **Skills** | 项目级 `.trae/skills/<name>/SKILL.md`；全局 `~/.trae-cn/skills/` | Markdown + YAML frontmatter | `name`+`description`；三层渐进式加载（L1 元数据/L2 说明/L3 资源） |
| **Agents（智能体）** | ⚠️ **矛盾点，待核查** | — | 官方文档说通过 IDE 界面创建（参数：头像/名称/提示词/可被其他智能体调用/工具）；juejin 文章（2026-03）提到 `.trae/agents/<name>.md` 目录；本地项目实际无此目录 |

### 关键矛盾（需在文档中标注 + 由 subagent 核查）

1. **智能体定义方式**：官方文档（docs.trae.cn/ide_agent）只描述 IDE 界面创建流程，未提及 `.trae/agents/` 文件系统目录；但 juejin 文章（2026-03-23）和 CSDN 文章提到 `.trae/agents/<agent-name>.md`。需核查：(a) 是否支持文件系统定义；(b) 若支持，YAML frontmatter 字段是什么；(c) 两种方式是否等价
2. **Skills 全局路径**：官方文档（英文版）说全局 skills 在 `~/.trae/skills/`；CSDN 文章（2026-04）说是 `~/.traecli/skills/`；本地 Subagent 改进建议.md 说在 `/Users/paper/.trae-cn/skills/`。需核查 tra-cn 版本的正确路径
3. **Hooks 沙箱内 python3 可用性**：本地脚本用 `python3 .trae/hooks/...`，但沙箱是否允许执行 python3 未实测（Subagent 改进建议.md 已标注此假设）

---

## Phase 2 澄清结论（已完成）

用户已确认：
- YOLOpose 项目性质：**纯科研项目**
- 文档定位：**纯经验总结 + 模板**（让新 agent 自己定制，不预设最终方案）
- 规范查证：**本地为主 + 官网补充，官网信息必须由 subagent 核查**

---

## Phase 3 计划

### 文档存放位置

**默认路径**：`/Users/paper/trae_project/行业定义agent/agent团队经验迁移指南-YOLOpose科研项目.md`

理由：放在当前项目根目录，用户可手动复制到 YOLOpose 项目。文件名含目标项目标识，避免与项目内其他文档混淆。

### 文档结构（8 个章节，预估 400-500 行）

#### 第 1 章：使用说明（约 30 行）
- 文档来源（行业定义 agent 项目，v1.3 规则体系）
- 目标读者（YOLOpose 科研项目的主 agent）
- 使用方式：先读本章 → 探索 YOLOpose 项目 → 按第 7 章执行步骤定制
- 重要声明：本文档是经验总结 + 模板，不是最终方案；新 agent 必须根据 YOLOpose 项目实际情况定制

#### 第 2 章：成功经验核心总结（约 100 行）
提炼 7 条可迁移的核心机制（每条含：机制描述 + 为什么有效 + 迁移要点）：
1. **规则驱动模式**：项目仓库只存 rules + hooks，subagent 全局引用
2. **12 条规则的设计哲学**：事实性来源、不确定就说不知道、评估先定义框架、工程视角强制覆盖、代码建议具体化、文件修改前先读、术语统一、批判性思维门槛、质量门、审查 agent 调用、去偏见化、多 agent 仲裁
3. **Hooks 守卫机制**：PreToolUse ask 模式拦截关键文件修改（非真正强制，依赖用户自律）
4. **Agent 推荐路由表**：解决 agent 发现性不足（规则 10.4）
5. **"实现完成"精确定义**：接口稳定 + Mock 测试 + 真实 API 测试 + 持久化 test 文件（规则 10.2）
6. **方法论拆分**：`_meta.yaml` 版本声明 + hard_rules + heuristics + self_check 模块化
7. **多 agent 治理**：去偏见化（规则 11）+ 多 agent 仲裁（规则 12）+ Kimi 同行评议

#### 第 3 章：Trae 规范速查（约 80 行）
基于官方文档（已查证），给出 4 类配置的规范要点：
1. **Rules**：位置、YAML frontmatter（alwaysApply/description/globs/scene）、4 种生效方式、3 层嵌套、子目录规则、兼容 AGENTS.md/CLAUDE.md
2. **Hooks**：位置、6 种事件（含触发时机/阻断能力/stdin/stdout/退出码）、hooks.json 格式、沙箱 vs 本地运行、环境变量（TRAE_PROJECT_DIR/TRAE_ENV_FILE）
3. **Skills**：位置、SKILL.md 格式（YAML + Markdown）、三层渐进式加载、与 Rules/MCP 的区别
4. **Agents（智能体）**：⚠️ 标注矛盾点 — 官方文档说 IDE 界面创建（参数：名称/提示词/可被其他智能体调用/工具），juejin 说 `.trae/agents/` 目录；新 agent 需先核查本地 Trae 版本支持哪种方式

每条规范标注来源 URL + 日期 + 可信度（按规则 1）。

#### 第 4 章：可迁移模板（约 150 行）
提供 5 类填空式模板（新 agent 根据 YOLOpose 项目填空）：

1. **project_rules.md 模板**：12 条规则骨架，每条留 `<定制指引>` 占位符
   - 例：规则 1 事实性数据来源 → 科研场景调整为"实验数据/超参数/模型性能指标必须标注来源（论文引用 + 数据集版本 + 实验日期）"
   - 例：规则 9 质量门 → 科研场景触发条件改为"产出 >80 行 .md 或新实验报告时"

2. **hooks.json + guard 脚本模板**：
   - hooks.json 骨架（PreToolUse + PostToolUse）
   - `pre_edit_core_model_guard.py` 模板（YOLOpose 场景：修改核心模型文件如 `yolopose/model.py`、`train.py`、`config.yaml` 前拦截，要求调 architecture-critic）
   - `post_write_experiment_log.py` 模板（新增/修改实验脚本时提示记录实验日志）

3. **subagent 提示词模板**（7 类，每类含角色/触发条件/工具/输出格式）：
   - `experiment-design-agent`（消融实验设计/超参搜索方案）
   - `code-implementer`（模型代码实现/训练脚本）
   - `experiment-validator`（实验运行验证/结果复现）
   - `paper-fact-checker`（论文数据核查/引用验证）
   - `architecture-critic`（模型架构变更审查）
   - `methodology-expert`（实验方法论审查）
   - `paper-writer`（论文章节撰写）
   - 每类提示词含"科研场景特化"指引（如 fact-checker 增加实验可复现性检查、统计显著性检查）

4. **agent 推荐路由表模板**：场景 → 推荐 agent → 用途（留空让新 agent 填）

5. **方法论文件结构模板**：
   ```
   methodology/
   ├── _meta.yaml          # 版本声明
   ├── hard_rules.md       # 硬性规则（实验规范、可复现性要求）
   ├── heuristics.md       # 启发式规则（超参选择、模型选择）
   └── self_check.md       # 自检清单（实验报告完整性）
   ```

#### 第 5 章：YOLOpose 科研项目定制指引（约 60 行）
针对纯科研项目的特化建议：
1. **典型任务分解**：论文复现 / 消融实验 / 超参搜索 / 论文撰写
2. **建议 agent 团队结构**（5-7 个 subagent，新 agent 根据项目实际调整）
3. **科研场景 rules 调整要点**：
   - 实验可复现性（随机种子、环境版本、数据集版本必须记录）
   - 数据来源标注（论文引用 + 数据集 URL + 版本号）
   - 统计显著性（多次实验均值 + 标准差 + 显著性检验）
   - 消融实验设计（控制变量 + 单一变量原则）
4. **科研场景 hooks 调整要点**：
   - 修改核心模型代码前审查（`model.py`/`train.py`/`config.yaml`）
   - 新增实验脚本时提示记录实验日志
   - 修改实验结果文件时提示备份

#### 第 6 章：迁移执行步骤（约 40 行）
新 agent 的操作清单（6 步）：
1. 探索 YOLOpose 项目结构（识别核心模型文件、训练脚本、配置文件、实验日志、论文草稿）
2. 核查 Trae 规范（按第 3 章标注的矛盾点，核查智能体定义方式、skills 全局路径、hooks 沙箱 python3 可用性）
3. 创建 `.trae/rules/project_rules.md`（按第 4 章模板填空）
4. 创建 `.trae/hooks.json` + guard 脚本（按第 4 章模板填空）
5. 创建 subagent（通过 IDE 界面或文件系统，取决于核查结果；按第 4 章提示词模板填空）
6. 创建方法论文件结构（按第 4 章模板）
7. 验证：用一个小任务（如"复现 YOLOpose baseline"）测试 agent 团队协作

#### 第 7 章：待核查事项（约 30 行）
明确列出需新 agent 核查的 5 个矛盾点（用户要求）：
1. 智能体是否支持 `.trae/agents/` 文件系统定义（官方文档 vs juejin 文章矛盾）
2. Skills 全局路径是 `~/.trae/skills/`、`~/.traecli/skills/` 还是 `~/.trae-cn/skills/`
3. Hooks 沙箱内 python3 是否可执行（本地未实测）
4. Hooks 沙箱 cwd 是否是项目根目录（相对路径是否可用）
5. `tool_input.file_path` 字段在 Edit/Write 工具中的实际结构（待 IDE 实测）

每条标注：矛盾描述 + 来源 A + 来源 B + 核查方法（grep/实测/官网再查）。

#### 第 8 章：附录 — 当前项目资料索引（约 30 行）
列出新 agent 可参考的具体文件路径（含行数和作用）：
- `project_rules.md`（v1.3，203 行，12 条规则完整文本）
- `开发日志/Subagent与规则改进建议.md`（v1.2，592 行，agent 提示词改进 + hooks 可行性分析）
- `.trae/hooks/pre_edit_models_py_guard.py`（67 行，ask 模式实现范例）
- `demo2/方法论/`（方法论拆分结构范例）
- `架构设计/架构设计-Agent架构-v5.md`（6 步编排 + 9 组件设计）
- 各开发日志（阶段一/二实战经验）

### 实施步骤

1. **创建文档文件**（Write 工具）
   - 路径：`/Users/paper/trae_project/行业定义agent/agent团队经验迁移指南-YOLOpose科研项目.md`
   - 按上述 8 章结构编写
   - 所有 Trae 规范数据标注来源 URL + 日期 + 可信度（按规则 1）
   - 所有矛盾点明确标注"待核查"

2. **调用 ai-architecture-fact-checker 核查 Trae 规范数据**（规则 10.1 + 用户要求）
   - 核查范围：第 3 章 Trae 规范速查 + 第 7 章待核查事项
   - 重点核查：6 种 hooks 事件的触发时机和阻断能力、hooks.json 字段说明、rules 的 4 种生效方式、skills 的三层加载机制、智能体创建方式
   - 输出：核查报告，标注哪些数据准确、哪些需修正

3. **根据核查结果修正文档**（Edit 工具）
   - 修正 fact-checker 指出的不准确数据
   - 补充 fact-checker 提供的更准确信息

4. **调用 architecture-critic 审查文档客观性**（规则 10.1）
   - 审查范围：第 2 章成功经验总结 + 第 5 章定制指引
   - 重点审查：是否有过度乐观的声称、是否有工程遗漏、是否对矛盾点的处理客观
   - 输出：审查报告，标注 P0/P1/P2 级问题

5. **根据 critic 结果修正文档**（Edit 工具）
   - 修正 P0/P1 级问题
   - P2 级问题视情况修正

6. **最终交付**：向用户汇报文档路径 + 核查结果摘要 + 待用户确认事项

### 假设与决策

1. **假设**：YOLOpose 项目使用 Trae CN 版本（与当前项目一致），故规范以 docs.trae.cn 为主、docs.trae.ai 为辅
2. **假设**：新 agent 能访问当前项目的文件路径（用户会手动复制文档到 YOLOpose 项目，或两个项目在同一台机器）
3. **决策**：文档不预设 YOLOpose 的最终 agent 团队方案，只提供模板和定制指引（按用户要求"纯经验总结+模板"）
4. **决策**：subagent 提示词模板提供 7 类，但说明新 agent 可根据项目实际增减
5. **决策**：所有 Trae 规范数据必须标注来源 URL + 日期 + 可信度（按规则 1），矛盾点必须标注"待核查"（按规则 2）

### 验证步骤

1. **文档完整性验证**：
   - 8 个章节全部存在
   - 所有模板含 `<定制指引>` 占位符（说明需要新 agent 填空）
   - 所有 Trae 规范数据有来源标注
   - 所有矛盾点有"待核查"标注

2. **fact-checker 核查通过**：
   - 第 3 章和第 7 章的所有技术数据被 fact-checker 确认准确
   - 或已按 fact-checker 建议修正

3. **architecture-critic 审查通过**：
   - 无 P0 级问题
   - P1 级问题已修正或记录反驳理由（按规则 11）

4. **行数验证**：预估 400-500 行，触发规则 9 质量门（>80 行 .md），已完成 fact-checker + architecture-critic 双审查

5. **用户确认**：通过 NotifyUser 通知用户文档路径 + 核查结果摘要，用户确认后可复制到 YOLOpose 项目使用

---

## 注意事项

- 文档中引用当前项目的文件路径时，用相对路径（如 `开发日志/Subagent与规则改进建议.md`），避免硬编码绝对路径（新 agent 可能在不同机器）
- subagent 提示词模板要符合 Trae 规范：若支持文件系统定义则用 YAML frontmatter；若只支持 IDE 创建则给出"在 IDE 中创建智能体时填入以下提示词"的指引
- 文档中不使用 emoji（除非用户要求）
- 所有外链用 markdown 格式，附访问日期
