# 架构设计-Agent架构-v5 评估报告（设计评审）

> **评估者身份**：同行评议专家（协作式评估者，非权威甲方）  
> **评估日期**：2026-06-18  
> **评估对象**：《架构设计-Agent架构-v5.md》（阶段二 A 组：基础设施加固）  
> **评估类型**：架构设计评审（评估 Spec 本身的设计质量、完整性、合理性、可实施性）  
> **对照基准**：《架构演进路线图-v3.1.md》

---

## 一、总体判断

v5 架构设计文档作为阶段二 A 组的开发 Spec，**整体设计方向正确，6 项组件的设计思路清晰且与 v3.1 路线图一致，但存在 3 个设计层面的脆弱性需要修正后才能交付 Trae 生成代码，2 个设计笔记需要补充，1 个文档表述问题需要澄清。**

具体来说：Checkpoint 清理的时间戳字符串解析和 `load_version` 的模糊匹配是**阻塞性设计缺陷**（P1），如果不修正，实现后会产生静默的数据丢失或错误恢复；quality_flags 的严重度判定缺乏可操作规则、报告尾部元信息区块的堆积问题、fixes_required 设计笔记不完整是**需要补充的设计细节**（P2），会影响实现质量但不阻塞编码。

文档的验收标准表格是良好的设计，但部分验收项的可执行性不足（如"模拟 8 天前的文件"）。

---

## 二、分维度评估

### 2.1 设计完整性

| 评估项 | 状态 | 说明 |
|--------|------|------|
| 6 项 A 组组件全部覆盖 | ✅ 完整 | quality_flags、SessionEventLog、TokenAudit、CheckpointManager、OutputSafety、methodology 拆分——与 v3.1 完全对应 |
| 每项组件的设计要素 | ✅ 完整 | 每项都有：痛点说明、设计思路、代码示例、关键设计约束 |
| 与 v4 的接口兼容性设计 | ✅ 完整 | 签名兼容（`log(event_type, data)`、`save(state, step_id)`、`load(industry_name)`）明确标注，行为语义差异也列出 |
| 阶段三预留接口 | ⚠️ 基本完整 | `quality_flags`、Checkpoint 多版本、fixes_required 设计笔记都有，但 fixes_required 缺少循环计数和 severity 阈值细节 |
| 验收标准 | ⚠️ 基本可检验 | 13 项验收标准覆盖了各组件，但部分项的可执行性不足（如"模拟 8 天前的文件"未说明方法） |
| 集成方案 | ❌ 缺失 | 文档没有说明如何在现有 v4 代码（`frost_agent.py` 771 行、`models.py` 186 行）中**增量集成**这 6 项组件，而不是重写。这是 Trae 生成代码时需要的关键上下文 |
| Mock 测试降级场景构造 | ❌ 缺失 | 验收标准提到"Mock 测试：模拟搜索部分失败"，但没有设计如何构造降级场景（如通过环境变量、注入错误响应、还是修改代码？） |

**观察**：v5 的文档假设开发者从一张白纸开始实现，但实际项目已有 v4 的完整代码。"如何在现有代码中增量集成"是设计 Spec 中缺失的关键上下文。建议补充一个"v4 → v5 增量集成指引"章节，明确哪些文件需要修改、哪些文件需要新增、哪些 v4 代码可以保留。

### 2.2 设计合理性

| 评估项 | 状态 | 说明 |
|--------|------|------|
| `quality_flags` 数据流 | ✅ 合理 | `QualityFlag` → `StepOutput.quality_flags`（独立字段，不污染 `result`）→ Step 6 汇总到报告尾部。数据流清晰，避免了数据污染 |
| SessionEventLog 降级策略 | ✅ 合理 | 日志写入失败降级到 print，不抛异常。符合 v3.1 约束 |
| Checkpoint 文件命名 | ✅ 合理 | `{industry}_{timestamp}_{step_id}[_{request_id}].json` 支持阶段三并发扩展 |
| TokenAudit 双格式输出 | ✅ 合理 | JSON（机器可读）+ Markdown（人类可读）同时生成，满足两种消费场景 |
| methodology 拆分策略 | ✅ 合理 | 只拆最可能独立变更的章节（Hard Rules、Heuristics、自检清单），保留完整 fallback 文件。增量拆分策略务实 |
| Checkpoint 清理时间戳解析 | ❌ 有脆弱性 | 从文件名字符串解析时间戳，行业名含下划线+数字时可能误拆（见 Q1） |
| Checkpoint `load_version` 匹配 | ❌ 有脆弱性 | `step_id=None` 时匹配所有步骤，返回第一个匹配的结果随机（见 Q2） |
| OutputSafety UTC + 时区标注 | ⚠️ 可能过度设计 | UTC 时间戳本身已统一，时区标注不解决碰撞问题（碰撞由秒级精度+版本号解决），反而增加文件名复杂度（见 Q3） |
| `quality_flags` severity 判定 | ⚠️ 主观化 | high/medium/low 的定义是定性描述，没有可操作的判定规则（见 Q4） |
| Step 6 尾部元信息堆积 | ⚠️ 未处理 | 自检警告、quality_flags 汇总、Token 统计、方法论附注都堆在尾部，多个 `---` 分隔区块可读性差（见 Q3） |

**观察**：v5 的设计中，数据流和接口兼容性处理得较好，但有两个组件（Checkpoint、OutputSafety）的设计细节需要修正。特别是 Checkpoint 的清理逻辑，v3.1 明确要求"清理逻辑需有单元测试"，但设计本身依赖字符串解析就不可靠——单元测试只能验证已知边界，无法保证所有行业名组合都不触发误拆。

### 2.3 可实施性

| 评估项 | 状态 | 说明 |
|--------|------|------|
| 技术依赖 | ✅ 合理 | 仅新增 `pyyaml`（methodology 的 `_meta.yaml`），其他依赖不变 |
| 工作量与 v3.1 估计一致 | ⚠️ 基本一致 | v3.1 估计 A 组总计 3.5-5 天，v5 未给出工作量估计但 6 项组件的复杂度与 v3.1 匹配 |
| 代码行数估计 | ❌ 低估 | v5 估计总代码量 `~1,100 行`，但实际 v4 已有 `~1,585 行`（含 Mock/注释）。新增 340 行叠加到现有代码后，总量更接近 `~1,900 行`。这个低估可能影响 Trae 的代码生成策略（如误认为需要重写而非增量修改） |
| 实现路径 | ⚠️ 不明确 | 文档没有明确是"增量修改现有文件"还是"新增模块 + 修改 Orchestrator 导入"。从代码示例看，新增模块（`harness/token_audit.py`、`harness/output_safety.py`）+ 修改 `frost_agent.py` 的导入和调用是更合理的路径 |

**观察**：v5 的 `frost_agent.py` 骨架标注为 `~350 行`，但实际 v4 是 771 行。如果 Trae 接收到"生成 ~350 行的 frost_agent.py"的指令，它可能会生成一个重写版本，而不是增量修改。建议 v5 文档补充明确："v5 的实现方式是**新增 5 个模块文件 + 修改现有 Orchestrator 的导入和调用点**，而非重写 frost_agent.py"。

### 2.4 与路线图 v3.1 的对齐度

| 评估项 | 状态 | 说明 |
|--------|------|------|
| 6 项 A 组组件 | ✅ 完全一致 | 与 v3.1 的 A 组表格完全对应 |
| 阶段三预留接口 | ✅ 一致 | `quality_flags`、Checkpoint 多版本、fixes_required 设计笔记——与 v3.1 的"阶段三循环的接口预留"章节一致 |
| B/C/D 组"不做"列表 | ✅ 一致 | 与 v3.1 的 B/C/D 组完全对应 |
| `call_with_timeout` 定位 | ⚠️ 表述轻微不一致 | v5 说 `call_with_timeout` "已在阶段一收尾完成"并将其放在 B 组描述中；v3.1 将其列为 B 组触发条件项。虽然事实一致（阶段一收尾已完成），但 v5 的表述可能让读者误以为 `call_with_timeout` 是 B 组的工作成果。建议修正为："`call_with_timeout` 在阶段一收尾已完成（P0-1），不属于阶段二 A 组工作范围" |
| 命名诚实原则 | ✅ 一致 | v5 继承 v3.1 的"命名诚实"原则，没有过度承诺 |

### 2.5 为阶段三预留接口的合理性

| 预留接口 | 状态 | 说明 |
|----------|------|------|
| `quality_flags` 标准化格式 | ✅ 合理 | 循环需要知道"失败的是哪一步"，Pydantic 模型约束格式避免了字符串漂移风险。v3.1 明确要求此修正 |
| Checkpoint 多版本 + `load_version()` | ✅ 合理 | 循环需要恢复到某一步的旧版本重跑。`load_version` 的签名设计为 `(industry_name, timestamp, step_id=None)` 支持精确恢复 |
| Step 5 `fixes_required` 设计笔记 | ⚠️ 基本合理 | 提供了 `FixItem` 的 Pydantic 模型草案，但缺少循环计数逻辑和 severity 阈值（见 Q7） |

**观察**：v5 在"预留接口"方面的设计是务实的——只设计数据结构，不实现循环逻辑。这与 v3.1 的"阶段二必须做循环的接口预留，不做循环本身"原则一致。但 `FixItem` 设计笔记作为阶段三的主要输入，其完整性会直接影响阶段三的开发效率。

---

## 三、关键问题列表（Q 级——需要团队反馈）

### Q1：Checkpoint 清理逻辑依赖文件名字符串解析，行业名含下划线+数字时可能误拆

**我的观察**：

`_cleanup_expired` 从文件名 `{industry}_{YYYYMMDD_HHMMSS}_{step_id}.json` 提取时间戳：

```python
for i, part in enumerate(parts):
    if len(part) == 8 and part.isdigit() and i + 1 < len(parts):
        if len(parts[i + 1]) == 6 and parts[i + 1].isdigit():
            file_timestamp = f"{part}_{parts[i + 1]}"
            break
```

如果行业名被 `_safe_name` 替换后仍包含下划线+数字（如 `AI_2024医疗`），`parts` 拆分后可能出现多个 `8位数字+6位数字` 的组合，时间戳提取会错位。例如文件名 `AI_2024医疗_20250618_143052_4_content_generation.json`，`parts` 为 `['AI', '2024医疗', '20250618', '143052', '4', 'content', 'generation']`——等等，实际上 `_safe_name` 将 `/` 和空格替换为 `_`，但下划线保留。如果行业名本身是 `AI_2024医疗`，`safe_name` 后仍为 `AI_2024医疗`，`parts` 拆分后为 `['AI', '2024医疗', '20250618', '143052', '4', 'content', 'generation']`——不，实际上 `stem` 是 `AI_2024医疗_20250618_143052_4_content_generation`，`split('_')` 后为 `['AI', '2024医疗', '20250618', '143052', '4', 'content', 'generation']`。遍历 `parts` 时，`'20250618'` 是 8 位数字且 `parts[i+1]` 是 `'143052'`（6 位数字），会正确匹配。但如果行业名是 `2024_医疗`，`parts` 是 `['2024', '医疗', '20250618', '143052', '4', 'content', 'generation']`，遍历到 `'2024'` 时，`parts[i+1]` 是 `'医疗'`（不是 6 位数字），不匹配；继续到 `'20250618'` 时匹配。这个例子似乎没问题。

但考虑行业名 `XX_20250618_医疗`，`parts` 为 `['XX', '20250618', '医疗', '20250618', '143052', '4', 'content', 'generation']`。遍历到 `i=1`（`'20250618'`），`parts[2]` 是 `'医疗'`（不是 6 位数字），不匹配。继续到 `i=3`（第二个 `'20250618'`），`parts[4]` 是 `'143052'`（6 位数字），匹配成功。结果是正确的——因为时间戳部分总是紧跟在行业名后面，即使行业名中有类似的数字组合，下一个部分不是 6 位数字就不会误匹配。

但等等，如果行业名是 `XX_20250618_143052`，这是一个极端情况：`parts` 为 `['XX', '20250618', '143052', '20250618', '143052', '4', 'content', 'generation']`。遍历到 `i=1`（`'20250618'`），`parts[2]` 是 `'143052'`（6 位数字），匹配成功！但此时 `file_timestamp` 是行业名的一部分，不是真正的时间戳。真正的时间戳在 `i=3`（第二个 `'20250618'`），但循环在 `i=1` 就停止了。

**这就是一个真实的碰撞场景**：行业名包含 `YYYYMMDD_HHMMSS` 格式的数字时，清理逻辑会将其误判为时间戳，导致该 checkpoint 文件被错误地判断为过期或不过期。

**建议**：
1. 方案 A：将时间戳部分固定放在已知位置（如文件名总是 `{safe_name}_{timestamp}_{step_id}.json`，从 `parts` 的倒数第二个位置取时间戳的日期部分，倒数第一个位置取时间戳的时间部分）。但 request_id 的存在会使位置不固定。
2. 方案 B：改用文件系统的 `mtime`（`path.stat().st_mtime`）进行时间判断，完全不依赖文件名解析。这是更可靠的做法。
3. 方案 C：在 checkpoint 文件中写入元数据（如 `{"saved_at": "2025-06-18T14:30:52Z"}`），清理时读取 JSON 的 `saved_at` 字段。这比 `mtime` 更可靠（`mtime` 可能被外部工具修改）。

**需要团队反馈**：
- 是否接受方案 B（`mtime`）或方案 C（文件内元数据）？
- 如果坚持文件名解析，是否可以在文件名中加入显式分隔符（如 `{safe_name}__{timestamp}__{step_id}.json`，用双下划线分隔行业名和时间戳）？

### Q2：`load_version` 的 `step_id=None` 时可能返回随机匹配

**我的观察**：

```python
def load_version(industry_name, timestamp, step_id=None):
    pattern = f"{safe_name}_{timestamp}_*"
    if step_id:
        pattern = f"{safe_name}_{timestamp}_{step_id}_*"
    matches = list(self.checkpoint_dir.glob(pattern + ".json"))
    if not matches:
        return None
    return ReportState.model_validate_json(matches[0].read_text(...))  # 取第一个匹配
```

当 `step_id=None` 时，如果同一行业在同一时间戳下有多个 step 的 checkpoint（如 Step 1、Step 2、Step 3 都在 `20250618_143052` 保存了），`glob` 会匹配到所有文件，而 `matches[0]` 的返回顺序取决于文件系统的排序（通常是字典序，但不保证）。这意味着调用方可能随机得到 Step 1、Step 2 或 Step 3 的 checkpoint。

**建议**：
1. 方案 A：当 `step_id` 为 None 时，返回所有匹配的 `ReportState` 列表，让调用方选择。
2. 方案 B：将 `step_id` 改为必填参数，不提供默认值。
3. 方案 C：在 `load_version` 的文档中明确说明"当 `step_id=None` 时，返回最新（按 `mtime` 排序）的一个"，并修改实现按 `mtime` 排序。

**需要团队反馈**：
- 阶段三 Evaluator-Optimizer 循环的使用场景：循环在恢复时是否总是知道要恢复哪一步？如果是，方案 B 最简单。

### Q3：Step 6 报告尾部已有多个元信息区块，quality_flags 汇总追加后会造成堆积

**我的观察**：

v4 的 `frost_agent.py` 第 676-688 行在报告尾部追加 Token 统计：

```markdown
---

*总 Token 消耗: 34562 | 步骤数: 5*
```

v5 的 `_build_quality_flags_summary` 在报告尾部追加 quality_flags 汇总：

```markdown
---

## ⚠️ 降级记录（quality_flags）

### 高严重度（影响报告质量，建议人工复核）
- [search_partial_failure] 2/3: Tavily API 限流，query 3 失败
```

如果 Step 5 自检也 fail，还会追加自检警告：

```markdown
---

## 自检未通过

以下维度未通过审查：C2, C4
```

此外，v4 的 Mock 报告本身在末尾已有方法论附注和生成时间标记。这意味着一个失败的报告尾部可能有 4-5 个 `---` 分隔的区块，可读性差。

**建议**：
1. 方案 A：设计一个统一的"报告尾部元信息区块"格式，将自检警告、quality_flags 汇总、Token 统计、方法论附注合并到一个区块中，用子标题区分。
2. 方案 B：明确优先级顺序——自检警告（最高优先级，因为涉及报告质量）→ quality_flags 汇总（次高，说明降级详情）→ Token 统计（最低，纯审计信息）。
3. 方案 C：将 Token 统计和 quality_flags 从报告正文中分离，只写入 JSONL 日志和 TokenAudit 报表，不在报告尾部显示。报告尾部只保留自检警告和方法论附注。

**需要团队反馈**：
- 用户阅读报告时，哪些尾部信息是最关键的？哪些可以放到独立的审计文件中？
- 自检警告和 quality_flags 同时存在时，优先级关系是什么？

### Q4：`quality_flags` 的 severity 判定缺乏可操作规则

**我的观察**：

v5 文档定义 severity：
- `high`：影响报告质量
- `medium`：有降级但质量可接受
- `low`：仅记录

但什么是"影响报告质量" vs "质量可接受"是主观判断。例如：
- Step 1 搜索 3 个 query 只有 1 个成功 → 是 high（信息来源不足）还是 medium（LLM 仍可从剩余 2 个 query 生成有效摘要）？
- Step 1 搜索全部失败，降级到 mock 搜索 → 是 high（所有信息都是假的）还是 medium（Mock 数据在开发测试中是可接受的）？
- `json_parse_fallback` 花括号提取成功 → 是 medium（降级但恢复了）还是 low（仅记录解析方式）？

**建议**：
1. 为每个预定义 `category` 给出默认 severity 映射表：

| category | 默认 severity | 判定规则 |
|----------|--------------|----------|
| `llm_empty_field` | medium | 字段为空，但其他字段可能足够 |
| `search_partial_failure` | 取决于失败比例 | 1/3 失败→medium；2/3 失败→high；全部失败→high |
| `json_parse_fallback` | low | 降级成功恢复，无数据丢失 |
| `or_fallback` | medium | 占位符替代了 LLM 输出，质量可能下降 |
| `timeout_retry` | low | 超时后重试成功，无质量影响 |

2. 允许实现者在默认映射基础上根据上下文调整，但要求调整时必须在 `detail` 中说明理由。

**需要团队反馈**：
- 团队是否已有 severity 判定的心智模型？
- 是否接受"默认映射 + 可覆盖"的方案？

### Q5：`SessionEventLog` 降级到 print 时，`trace_id` 如何传递给 `TokenAudit`

**我的观察**：

v5 的 `frost_agent.py` 骨架中：

```python
logger = SessionEventLog(industry_name)  # 生成 trace_id
token_audit.generate_report(state, logger.trace_id, industry_name)  # 从 logger 获取 trace_id
```

但如果 `SessionEventLog` 初始化失败（如日志目录不可写），`SessionEventLog.__init__` 中的 `self.log_dir.mkdir(exist_ok=True)` 在磁盘满时可能抛出 `OSError`。虽然 `log()` 方法有 `try/except` 降级到 print，但 `__init__` 的目录创建没有降级处理。如果 `__init__` 失败，整个 Orchestrator 会崩溃，根本走不到 `token_audit.generate_report`。

即使 `__init__` 成功，如果 `log()` 方法中的文件写入降级到 print，此时 `logger.trace_id` 仍然可用（因为 `trace_id` 在 `__init__` 中生成）。所以 `token_audit.generate_report` 仍然能获取到 `trace_id`。但这个依赖关系是隐式的——`TokenAudit` 依赖 `SessionEventLog` 的 `trace_id` 属性，两者之间的数据流没有在设计文档中明确。

**建议**：
1. 方案 A：在 `TokenAudit` 的设计中明确说明 `trace_id` 从外部注入（通过 `generate_report` 的参数），而不是自己生成。如果注入为 None，则 `TokenAudit` 自己生成一个。
2. 方案 B：在 Orchestrator 中统一生成 `trace_id`（通过 `uuid.uuid4().hex[:12]`），然后分别注入 `SessionEventLog` 和 `TokenAudit`。这样两者不互相依赖。

**需要团队反馈**：
- 是否接受方案 B（Orchestrator 作为 trace_id 的生成者和分发者）？这会使 trace_id 的生成逻辑更集中，但也增加了 Orchestrator 的复杂度。

### Q6：methodology 版本升级时的模块迁移策略未设计

**我的观察**：

v5 的 `_meta.yaml` 示例：

```yaml
version: "v2"
modules:
  - name: hard_rules
    file: hard_rules.md
    keywords: ["Hard Rules", "R1", "R2", "R3", "R4", "R5"]
```

当版本从 v2 升级到 v2.1 时：
- 是否新增 `modules` 条目？
- 旧模块文件是否保留？
- 如果新增模块，但 `fallback` 文件（`methodology_full.md`）仍是旧版本，`MethodologyLoader` 加载 fallback 时是否会丢失新模块的内容？
- `keywords` 映射是否需要向后兼容（即新模块的 keywords 是否覆盖旧模块的 keywords）？

**建议**：
1. 补充版本升级规则：
   - 版本升级时，`_meta.yaml` 的 `version` 字段更新，`modules` 列表可以增删改。
   - 新增模块必须有对应的 `.md` 文件，否则 `load_slice` 回退到 `fallback` 文件时，该模块的内容会从 `fallback` 中通过正则切片提取（这可能导致重复加载）。
   - 建议：`fallback` 文件应始终保持为最新完整版本，即使模块已拆分。

2. 或者简化策略：不允许运行时版本切换，版本变更时手动替换 `_meta.yaml` 和模块文件，`fallback` 文件同步更新。

**需要团队反馈**：
- 方法论的版本变更频率预期是多少？（如每季度一次、每月一次、还是很少变更？）
- 是否需要运行时版本切换能力（如 A/B 测试不同版本的方法论），还是只需要静态替换？

### Q7：Step 5 `fixes_required` 设计笔记缺少循环计数和 severity 阈值

**我的观察**：

v5 的 `fixes_required` 设计笔记只给出了 `FixItem` 的 Pydantic 模型：

```python
class FixItem(BaseModel):
    dimension: str
    problem: str
    target_step: str | None
    severity: str  # "high" / "medium" / "low"
```

但缺少以下关键设计细节：
- "最多 3 轮自动修正"：是按 FixItem 的数量计数（如一轮修复一个 FixItem），还是按重跑次数计数（如一轮重跑所有 target_step）？
- 如果 `severity="low"`，是否触发自动修正？还是只有 high/medium 才触发？
- 如果多个 FixItem 指向同一个 `target_step`，是合并后重跑一次，还是逐个重跑？
- 如果重跑后新的 FixItem 列表与之前不同（如引入了新的问题），是否继续循环？

**建议**：
1. 补充循环计数规则：按**重跑次数**计数（每轮重跑所有 target_step 不为 None 的 FixItem），最多 3 轮。
2. 补充 severity 阈值：只有 `severity="high"` 或 `"medium"` 的 FixItem 触发自动修正，`severity="low"` 只记录不触发。
3. 补充合并规则：同一 `target_step` 的多个 FixItem 合并后只重跑一次该 step。

**需要团队反馈**：
- 阶段三循环的停止条件是否有更明确的约束？
- 3 轮是否足够？是否有参考数据支持这个上限？

---

## 四、风险矩阵

| 风险等级 | 风险 | 说明 | 建议应对 |
|----------|------|------|----------|
| **P1** | **Checkpoint 时间戳解析误拆导致误删/漏删** | 行业名含 `YYYYMMDD_HHMMSS` 格式时（如 `AI_20250618_医疗`），清理逻辑会将其误判为时间戳，导致文件被错误地判断为过期或不过期。 | **修正设计**：将 `_cleanup_expired` 从文件名解析改为文件内元数据（JSON 的 `saved_at` 字段）或 `mtime`。这是设计缺陷，实现后难以通过单元测试完全覆盖。 |
| **P1** | **`load_version` 返回随机匹配的 checkpoint** | 当 `step_id=None` 时，同一 time戳有多个 step 的 checkpoint，`matches[0]` 的返回顺序取决于文件系统排序，可能导致恢复错误的步骤。 | **修正设计**：将 `step_id` 改为必填参数，或返回所有匹配的列表让调用方选择。 |
| **P2** | **质量严重度判定主观化，导致质量报告不一致** | 不同实现者对同一降级场景（如"1/3 搜索失败"）可能给出不同 severity，导致报告的 quality_flags 汇总不可比。 | **补充设计**：为每个预定义 `category` 给出默认 severity 映射表，允许上下文覆盖但要求说明理由。 |
| **P2** | **报告尾部多个 `---` 分隔区块堆积** | 自检警告、quality_flags 汇总、Token 统计、方法论附注都堆在尾部，可读性差，用户可能忽略关键信息。 | **补充设计**：统一尾部元信息格式，或降低部分信息（如 Token 统计）的显示优先级，将其移到独立审计文件。 |
| **P2** | **`trace_id` 降级传递未设计** | 如果 `SessionEventLog` 降级到 print（无文件），`TokenAudit` 的报表文件名 `{trace_id}_token_audit.json` 是否仍能正确关联？依赖关系是隐式的。 | **补充设计**：明确 `trace_id` 由 Orchestrator 统一生成并注入各组件，避免组件间隐式依赖。 |
| **P3** | **methodology 版本迁移策略缺失** | 版本升级时模块文件如何同步、fallback 文件如何更新，设计未涉及。可能导致新旧模块混用或内容丢失。 | **补充设计**：在 `_meta.yaml` 中补充版本升级规则，或明确"运行时版本切换不在本阶段支持范围内"。 |
| **P3** | **`fixes_required` 设计笔记不完整** | 缺少循环计数逻辑、severity 阈值、合并规则，阶段三开发者需要重新设计这些细节。 | **补充设计**：在 v5 文档中补充 3 条规则（按重跑次数计数、low severity 不触发、同 target_step 合并）。 |
| **P3** | **OutputSafety 时区标注可能过度设计** | UTC 时间戳本身已统一，碰撞由秒级精度+版本号解决。`_{tz_label}` 增加文件名长度但不增加安全性。 | **可选修正**：简化文件名格式为 `{industry}_{timestamp}_行业定义报告.md`，移除时区标注；或在文档中明确说明时区标注的用途（如"便于人工阅读时识别时间基准"）。 |
| **P3** | **v5 代码行数估计低估** | `~1,100 行` 的估计明显低于实际（v4 已有 `~1,585 行`），可能导致 Trae 生成代码时采用重写策略而非增量修改。 | **修正文档**：将总代码量估计更新为 `~1,900 行`（v4 实际 + v5 新增），并明确说明实现方式是"新增模块 + 修改导入/调用点"而非重写。 |
| **P3** | **验收标准的可执行性不足** | "Mock 测试：模拟搜索部分失败"、"创建 8 天前的文件"等验收项没有说明如何构造降级场景。 | **补充设计**：在验收标准表格中增加"测试构造方法"列，说明如何通过环境变量或注入错误来模拟降级。 |

---

## 五、建议与行动清单

### P0（修正后才能交付 Trae 生成代码）

| # | 行动 | 改动范围 | 估计工作量 | 说明 |
|---|------|----------|------------|------|
| 1 | **修正 Checkpoint 清理逻辑**：从文件名解析改为文件内元数据或 `mtime` | `v5 文档第 2.4 节` | 30 分钟 | 这是设计缺陷，实现后会产生静默的数据丢失。建议方案 C（文件内 `saved_at` 字段）最可靠。 |
| 2 | **修正 `load_version`**：将 `step_id` 改为必填参数 | `v5 文档第 2.4 节` | 15 分钟 | 避免阶段三循环恢复时加载错误的步骤。 |
| 3 | **补充集成方案**：明确 v5 的实现方式是"新增 5 个模块 + 修改 Orchestrator 导入/调用点" | `v5 文档第 5 节或新增章节` | 30 分钟 | 避免 Trae 误将 v5 理解为重写。 |

### P1（建议修正，可与 P0 同步进行）

| # | 行动 | 改动范围 | 估计工作量 | 说明 |
|---|------|----------|------------|------|
| 4 | **补充 quality_flags severity 默认映射表** | `v5 文档第 2.1 节` | 30 分钟 | 为每个预定义 category 给出默认 severity，允许上下文覆盖。 |
| 5 | **设计报告尾部元信息统一格式** | `v5 文档第 2.1 节或 2.5 节` | 30 分钟 | 明确自检警告、quality_flags、Token 统计的排列优先级，或决定将 Token 统计从报告尾部移除。 |
| 6 | **补充 `trace_id` 生成和分发方案** | `v5 文档第 5 节（Orchestrator 骨架）` | 15 分钟 | 明确 `trace_id` 由 Orchestrator 统一生成，注入 `SessionEventLog` 和 `TokenAudit`。 |
| 7 | **补充 fixes_required 循环规则** | `v5 文档第 3 节` | 20 分钟 | 补充"最多 3 轮"的定义（按重跑次数）、severity 阈值（low 不触发）、同 target_step 合并规则。 |
| 8 | **修正 `call_with_timeout` 的 B 组表述** | `v5 文档第 1 节"v5 不做的"` | 5 分钟 | 明确说明 `call_with_timeout` 在阶段一收尾已完成，不属于 B 组。 |

### P2（可在实现过程中补充）

| # | 行动 | 改动范围 | 说明 |
|---|------|----------|------|
| 9 | **补充 methodology 版本迁移策略** | `v5 文档第 2.6 节或 _meta.yaml` | 明确版本升级时模块文件和 fallback 文件的同步规则。 |
| 10 | **补充验收标准的测试构造方法** | `v5 文档第 7 节` | 为每个需要 Mock 测试的验收项说明降级场景如何构造。 |
| 11 | **更新代码行数估计** | `v5 文档第 6 节` | 将总代码量估计更新为实际值（~1,900 行），避免 Trae 低估。 |

### P3（可选）

| # | 行动 | 改动范围 | 说明 |
|---|------|----------|------|
| 12 | **简化 OutputSafety 时区标注** | `v5 文档第 2.5 节` | 移除时区标注或改为可选，简化文件名。 |
| 13 | **TokenAudit 定价配置化** | `v5 文档第 2.3 节` | 将硬编码定价改为可配置（环境变量或配置文件），为未来切换供应商预留。 |
| 14 | **补充 Mock 测试策略** | `v5 文档新增章节` | 设计如何在单元测试中构造降级场景（如通过 monkeypatch、环境变量注入、还是错误响应模拟）。 |

---

## 六、已确认的事实与已修正的判断

| 原判断 | 修正 | 依据 |
|--------|------|------|
| 无（本次为设计评审，不验证代码） | — | — |

---

## 七、留给团队的核心提问

1. **Checkpoint 清理的时间戳解析方案**：是否接受改用文件内元数据（`saved_at` 字段）替代文件名解析？这可以彻底消除行业名碰撞问题，但需要在 checkpoint 文件中写入额外字段。

2. **报告尾部元信息的优先级**：自检警告、quality_flags 汇总、Token 统计——当三者同时存在时，用户应该先看到哪个？Token 统计是否应该从报告正文中移除，只保留在独立的审计文件中？

3. **`trace_id` 的生成策略**：是否接受由 Orchestrator 统一生成 `trace_id` 并注入各组件？这会增加 Orchestrator 的复杂度，但消除了 `SessionEventLog` 和 `TokenAudit` 之间的隐式依赖。

4. **methodology 版本变更频率**：方法论的版本变更预期是多久一次？如果变更频率很低（如每季度一次），版本迁移策略可以简化到"手动替换全部文件"；如果频率高，则需要更复杂的运行时切换能力。

5. **P0 修正后的时间线**：P0 的 3 项修正预计需要 1-1.5 小时，修正后的 v5 文档是否可以直接交付给 Trae 生成代码？还是 Trae 会先基于当前 v5 生成，再由人工做 P0 修正？

---

*评估报告版本：v1.0（设计评审）*  
*评估者：同行评议专家*  
*评估完成时间：2026-06-18*  
*评估类型：架构设计评审（不验证代码实现）*
