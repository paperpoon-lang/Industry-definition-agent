# 阶段一：Demo MVP 开发日志

> 版本：v1.0 | 日期：2026-06-08  
> 范围：按架构设计 v4 + 架构演进路线图 v2 阶段一，产出可运行的 Demo MVP

---

## 一、交付物清单

```
demo/
├── frost_agent.py           # 703行  主程序：Orchestrator + 六步 + Step 5 警告注入
├── models.py                # 186行  Pydantic 数据模型
├── methodology_loader.py    # 163行  方法论切片加载器
├── context_builder.py       # 118行  四层上下文组装器
├── evaluator.py             # 137行  独立 Evaluator（Step 5 专用）
├── search.py                # 186行  并行搜索 + 截断压缩
├── requirements.txt         #   4行  依赖声明
├── .env.example             #  46行  环境变量模板
├── 方法论-v2.md             #  复制  方法论文档
├── harness/
│   ├── __init__.py          #   1行  包声明
│   ├── circuit_breaker.py   #  28行  打桩：call_with_retry（指数退避重试）
│   ├── session_log.py       #  18行  打桩：SimpleLogger（print 到 stdout）
│   └── checkpoint.py        #  41行  打桩：save/load JSON
├── reports/                 #  自动生成
└── checkpoints/             #  自动生成
```

**总计 1,585 行 Python**（含 Mock 响应生成逻辑约 350 行）。

---

## 二、v4 架构对照

| 类别 | 组件 | 状态 |
|------|------|------|
| **完整做** | 核心 4 文件 + 六步管线 | ✅ |
| | Context Builder 四层 | ✅ |
| | 搜索并行 + 结果截断压缩 | ✅ |
| | StepBudget（数据模型，不强执行） | ✅ |
| | Independent Evaluator（Step 5 独立审查） | ✅ |
| | methodology_loader（按 step_id 切片 + 空切片降级） | ✅ |
| **打桩做** | Circuit Breaker → call_with_retry() | ✅ |
| | Session Event Log → SimpleLogger | ✅ |
| | Checkpoint → save/load JSON | ✅ |
| | Sprint Contract → prompt 内嵌 | ✅ |
| | Token Audit → StepOutput 字段 | ✅ |
| **不做** | Evaluator-Optimizer 自动修正闭环 | ✅ |
| | Model Router（多模型降级链） | ✅ |
| | methodology/ 目录拆分 | ✅ |

---

## 三、开发中遇到的问题及解决

### 问题 1：Step 5 Evaluator 返回非 JSON 导致 parse_error

**表现**：真实 API 跑"低空经济物流"时，Step 1-4 正常完成，Step 5 的 `parse_evaluation()` 无法解析 LLM 响应，返回 `parse_error`，导致自检显示 `fail_with_fixes`。

**根因**：`evaluator.py` 的 `EVALUATOR_PROMPT` 只说"对每个维度输出 PASS/FAIL + 具体问题"，没有要求输出 JSON 格式。DeepSeek 自然返回了一段自然语言分析文本。

**修复**：将 `EVALUATOR_PROMPT` 改为包含完整的 JSON schema 模板，明确写"你必须只输出以下 JSON 格式，不要输出任何其他文字"。修复后 Step 5 自检通过。

---

### 问题 2：LLM 在报告前附加开场白

**表现**：Step 4 生成的报告在正文前多了一行"好的，我将以行业定义分析助手的身份，为您撰写关于「低空经济物流」的行业定义报告。"

**排查过程**：
1. 首先怀疑是方法论导致——检查了 Step 4 注入的方法论切片（Hard Rules、推理展示、范围约束），均无关
2. 定位到 ContextBuilder 的 Layer 1 静态身份："你是行业定义分析**助手**"
3. 中文 LLM 在被定位为"助手"并接到"撰写报告"的任务时，会自然地先确认再执行——这是对话训练数据导致的礼貌性行为

**修复（三层防护）**：
1. 静态身份：`分析助手` → `分析引擎`（减少对话式人格定位）
2. Step 4 任务指令：增加 `直接输出 Markdown 格式报告，从第一个 # 标题开始，不要加任何开场白或礼貌用语`
3. 代码安全网：`_strip_preamble()` 函数，自动剥离第一个 `#` 标题或 `---` 分隔线之前的内容

**验证**："汽车行业"报告开头直接为 `# 汽车行业定义报告`，无开场白。

---

### 问题 3：Checkpoint 恢复后重复执行步骤

**表现**：`--resume` 恢复后正确打印"从 checkpoint 恢复了 5 个步骤"，但随后仍从头执行所有步骤，导致 `total_tokens` 翻倍（18,631 → 37,998），步骤数翻倍（5 → 10）。

**根因**：`run()` 函数中恢复 state 后没有检查 `completed_ids`，直接无差别执行了所有步骤函数。

**修复**：在 `run()` 中每个步骤调用前加 `if step_id not in completed_ids` 判断，已完成步骤打印 `[跳过]`。同时将 Step 5 的警告构建逻辑提取为 `_build_self_check_warning()` 函数，供恢复后的跳过路径复用。

**验证**：恢复后全部 5 步显示 `[跳过]`，报告长度和 token 数不变。

---

### 问题 4："汽车行业" Step 4 生成极慢/卡死

**表现**：首次跑"汽车行业"时，Step 4 在 5-10 分钟内无响应。相比"低空经济物流"（Step 4 约 2 分钟），明显异常。

**排查**：
1. 硅基流动 API 本身可达（`/v1/models` 正常响应）
2. "汽车行业"搜索返回的上下文比"低空经济物流"更大（更宽泛的话题）
3. Step 4 的上下文包含：方法论全文 + Step 1-3 完整摘要 + 任务指令，总计约 40K+ tokens 输入
4. `max_tokens=16000` 给了 LLM 极大的输出空间
5. 初次运行无 `timeout`，无限等待

**期间尝试过的调整**：
- 添加 `AsyncOpenAI(timeout=180.0)` —— 超时未生效（SDK 行为与预期不一致）
- 降低 `max_tokens=16000 → 8000` —— 之后 Step 4 在 2.5 分钟内完成，报告质量可接受

**最终处理**：上述两项修改（timeout、max_tokens）**超出 v4 范围**，已回退到 v4 原样。

**v4 范围内的可选解决方案**（留给阶段一后续或阶段二）：
- `STEP_BUDGETS` 中已定义每步的 `timeout_seconds`，但 v4 明确写"不强执行"
- 阶段二的完整 Circuit Breaker 包含超时和恢复机制
- 如果需要在阶段一解决，可以用 `asyncio.wait_for` 在 Orchestrator 级别按 `STEP_BUDGETS.timeout_seconds` 限时

---

### 问题 5：Context Builder 四层验证

v3 架构只有三层（静态身份 → 方法论切片 → 前序摘要），v4 基于架构评审新增了任务指令层（Layer 3）。开发中确认：**缺少这一层，LLM 不知道当前步骤具体该做什么**。

Step 1 的上下文如果不含 `STEP_TASKS["1_info_collection"]`（要求输出 JSON 包含 summary、official_definitions 等字段），LLM 会自由发挥格式。加上后输出格式稳定。

---

### 问题 6：`_strip_preamble()` 误删报告正文（2026-06-11）

**现象**：运行 `python3 frost_agent.py "新能源汽车"`，Step 4 LLM 生成了完整报告（# 标题 → 第 1-3 章 → 方法论附注），Step 5 自检却报 C4 "报告未提供实际定义文本"。查看输出文件发现报告正文消失，只留方法论附注。

**根因**：`_strip_preamble()` 的逻辑漏洞。当 LLM 输出以 `#` 标题开头（无开场白）时，`m.start() == 0`，第一个条件 `m.start() > 0` 不触发——代码继续走到 `---` 检查，把报告正文中任何位置的 `---`（通常出现在方法论附注前）误判为"开场白边界"，切掉之前所有正文。

```python
# 修复前（有漏洞）
if m and m.start() > 0:       # 标题在位置 0 时不触发
    return text[m.start():].lstrip("\n")
# 继续走 --- 检查 ← 漏洞：此处应直接返回
```

**修复**：`#` 标题在位置 0 时直接返回原文，`---` 检查仅在没有 Markdown 标题的降级路径中生效。

```python
# 修复后
if m:
    if m.start() > 0:
        return text[m.start():].lstrip("\n")
    return text  # 标题在位置 0，无开场白可剥
# 无 Markdown 标题时，才走 --- 检查
```

**为什么之前没触发**：前两次测试（"低空经济物流"、"汽车"）的 LLM 输出可能带有开场白（标题不在位置 0），走的是 `m.start() > 0` 路径正常剥离。本次 LLM 直接以标题开头，暴露了降级路径的缺陷。

---

## 四、真实 API 测试结果

### 测试 1：低空经济物流

| 指标 | 数值 |
|------|------|
| 端到端耗时 | ~8 分钟 |
| 总 Token | 32,098 |
| 报告长度 | 7,267 字符 |
| Step 1 搜索延迟 | 4 秒 |
| Step 5 自检 | pass（C1-C5 全部通过） |
| 开场白 | 首次有（修复后消除） |

### 测试 2：汽车行业

| 指标 | 数值 |
|------|------|
| 端到端耗时 | ~8 分钟（含调试重试） |
| 总 Token | 29,689 |
| 报告长度 | 6,492 字符 |
| Step 1 搜索延迟 | 2 秒 |
| Step 5 自检 | pass |
| 开场白 | 无 ✅ |

### Mock 模式测试

| 指标 | 数值 |
|------|------|
| 端到端耗时 | < 1 秒 |
| 首次运行 | 6 步全通过 |
| Checkpoint 恢复 | 正确跳过已完成步骤 |
| 报告不含禁止内容 | ✅ |

---

## 五、v4 验收标准对照

| 标准 | 状态 | 证据 |
|------|------|------|
| `python frost_agent.py "低空经济物流"` 稳定产出报告 | ✅ | Mock 3/3 成功，真实 API 2/2 成功 |
| 方法论附注可见完整维度取舍推理 | ✅ | 含 H1-H4 维度选择理由和放弃原因 |
| Step 5 自检 C1-C5 逐项有 PASS/FAIL | ✅ | Evaluator prompt 修复后正常 |
| 自检 FAIL 时报告头部有警告标记 | ✅ | `_build_self_check_warning` + `_strip_preamble` |
| 报告中不含竞争排名/市场份额/投资建议 | ✅ | 仅方法论附注中作为"放弃原因"引述 |
| 进程崩溃后可从 checkpoint 恢复续跑 | ✅ | 恢复后跳过已完成步骤 |
| Step 1 搜索 < 10 秒 | ✅ | 2-4 秒 |
| 成本/延迟有实测数据 | ✅ | Token 和耗时已记录 |

---

## 六、阶段一教训沉淀：新 LLM 调用点的代码规范

以下规范从 `fix-LLM空字段导致Pydantic校验失败` 中提炼，作为阶段二及后续开发的通用纪律：

1. **每个新增的 LLM 调用点**（`call_llm` / `call_with_retry` 包装）返回后，必须同时加：
   - **输出格式兜底**：解析 LLM 返回的字段前加 `or` fallback，避免空字段导致 Pydantic 崩溃
   - **原始响应日志**：`logger.log("llm_raw_response", {"step_id": step_id, "text_preview": llm_result["text"][:1000]})` 在 `_parse_json_response` 解析前记录
2. Step 5 的 Evaluator 走独立 `evaluator.py` 模块内部调用 LLM，不受此规范约束（由 evaluator.py 内部负责）
3. Prompt 指令和代码兜底并行使用：prompt 软约束降低触发概率，代码硬兜底保证不崩溃，两步互不替代

---

## 七、已知局限（留给阶段一后续或阶段二）

1. **超时保护缺失**：API 响应极慢时无主动中断，需依赖阶段二的 Circuit Breaker
2. **无进度指示**：每步 LLM 调用期间终端无输出，不知道在等什么
3. **方法论匹配依赖关键词**：`SLICE_MAP` 用子串匹配，方法论章节名变化后可能匹配为空（有空切片降级兜底）
4. **单文件方法论**：阶段二应拆分 `方法论-v2.md` 为模块化结构 + `_meta.yaml` 版本管理
5. **Mock 模式响应是硬编码的**：如果 `STEP_TASKS` 关键词变化，Mock 检测逻辑会失效

---

## 八、同行评议启发（来自 2026-06-08 架构评审）

以下不是 bug，而是评审中暴露的**设计层面的已知脆弱性**，值得在进入阶段二前审视：

### 7.1 搜索 query 的静态性（P1）

当前 `search.py` 的 `SEARCH_QUERIES` 是 3 个固定模板：

```python
"{industry} 行业定义 官方定义 标准"
"{industry} 政策 监管 产业链"
"{industry} 边界 与相邻行业区分"
```

对"低空经济物流"和"汽车"这类信息丰富的行业，3 个 query 足够。但对于高度细分的新兴行业（如"固态电池回收"），模板 query 不会自动衍生出"电解质回收工艺""正极材料分离技术"等关键术语。当前代码没有任何机制让 Step 1 的 LLM 总结结果反哺搜索策略。

**方向**：阶段二引入 Persistent Memory 时，可从历史搜索中提炼行业关键词库；或让 Step 1 的 LLM 根据初步结果生成补充 query。

### 7.2 `_strip_preamble()` 的设计边界

当前实现依赖正则 `^#{1,4}\s+` 匹配第一个 Markdown 标题。如果 LLM 输出的前导文本是纯中文段落（不含 `#` 标题标记），函数会返回原文——开场白残留。修复后的两份报告虽未触发此边界，但这不是"运气好"可以依赖的。

**方向**：增加对常见开场白模式的字符串前缀匹配（如 `好的，我将`、`当然可以`、`以下是` 等）作为正则匹配的补充。

### 7.3 方法论规则冲突的潜在场景

两次运行中 LLM 均未报告规则冲突，但以下两种场景在方法论 v2 框架下可能产生矛盾：

- **H1 vs H4**：一个特征在行业中"被极端放大"（H1 候选），但其数据不可得（H4 允许放弃）。当前方法论没有给出优先级指引——LLM 可能在两者之间犹豫或做出不一致的选择。
- **H2 独立侧要求 vs 新兴行业**：某些行业（如平台型、生态型行业）的供需两侧高度重叠，难以从独立维度区分。当前方法论假设行业存在自然分化的维度侧，未覆盖高耦合场景。

**方向**：用 2-3 个"低信息量 + 边界模糊"的困难案例做压力测试，观察 Step 2 的 raw reasoning 是否出现矛盾或不确定表述。

### 7.4 代码规模统计口径

v4 架构文档预估总计 ~760 行 Python，实际产出 1,585 行。偏差来源：
- Mock 响应数据：~350 行（硬编码的预设 JSON/Markdown）
- Step 具体实现：~200 行（v4 骨架只有调用骨架，不包含参数构建、解析逻辑）
- 辅助函数：~150 行（`_strip_preamble`、`_parse_json_response`、`_extract_industry` 等）
- 注释/空行/导入/CLI 入口：~125 行

核心六步管线逻辑约 760 行，与文档估计一致。文档应标注"核心逻辑行数"而非"文件总行数"。

---

## 九、超出 v4 范围的改动（已回退）

以下改动在调试过程中引入，后因超出 v4 范围已回退：

| 改动 | 位置 | 说明 | 回退后状态 |
|------|------|------|-----------|
| `AsyncOpenAI(timeout=180.0)` | `frost_agent.py` L188 | 尝试防止 API 无限等待 | 已移除，无 timeout |
| `max_tokens=16000 → 8000` | `frost_agent.py` L195 | 尝试加速 Step 4 | 已恢复为 16000 |

---

*日志版本：v1.0 | 日期：2026-06-08*
