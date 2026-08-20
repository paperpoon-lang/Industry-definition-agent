# 行业定义 Agent Web UI 实施计划（v2.4）

> v2.4 变更说明（用户拍板）：① UI 只做真实 API——砍掉界面上全 Mock/半 Mock 模式控件
> （demo2 后端的 --mock 与 MOCK_* env 机制原样保留不动，只是 UI 不再暴露）；
> ② UI 独立目录——从 demo2/ 移到项目根目录新建 `webui/`（用户要求），demo2 零文件改动（README 也不动）。
> 前提已验证：PROJECT_ROOT 锚定脚本位置（[L58](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L58)），
> logs/reports/checkpoints 与启动 cwd 无关；load_dotenv() 从 cwd 查找（[L52](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L52)），
> 子进程 cwd=DEMO2 → .env 正常加载。验证用 Mock 场景改由启动前 env 注入实现（不占 UI 控件）。
> v2.3 变更说明：裁决 workbuddy 评审意见（详见「外部评审意见裁决」节）——
> 锁健壮性（try/finally + 僵尸锁检测）、run_every 改为常开 + fragment 内状态检查（放弃动态装饰器参数）、
> FM 审查 JSON 截断降级路径、已完成步骤可回看展开（st.status 无 key 参数，改用 st.expander 混合方案）、glob.escape。
> v2.2 变更说明：Q1 已定（新建 .venv-ui 隔离环境）；派生简化——子进程解释器直接用 `sys.executable`；
> 事件解析器独立为无 streamlit 依赖的 `ui_events.py`（可测试性）；fragment 空闲时停止轮询；
> 半 Mock 验证的具体操作方式明确化；glob 回退收紧为按行业名匹配。
> v2.1 变更说明：吸收 architecture-critic 评审的 2 个 P0 + 3 个 P1 + 5 个 P2 修正（全部经源码验证前提后采纳）；
> 核心变化：**jsonl 升为时间线唯一事实源**（消除双通道去重问题）、stdout 强制无缓冲、线程不碰 session_state、
> 验证步骤修正（Mock 模式不执行 FM 审查循环，需半 Mock + fixture 单测）。
> v2 变更说明：根据用户反馈「进度展示要 step 往下一层、GUI 化、能看到为什么补搜」重写进度方案。
> v1 的 subprocess 调用、零侵入原则、报告 glob 回退经核实保留。

## 摘要

为「行业定义 Agent v5.2」（`/Users/paper/trae_project/行业定义agent/demo2/`）开发简易 Web UI，
UI 代码放**项目根目录独立文件夹 `webui/`**（demo2 零文件改动）：
输入行业名（**仅真实 API 模式**，界面上无 Mock 选项）→ **双层时间线实时展示执行过程**
（顶部六步进度 + 每步内子事件卡片，含"为什么补搜"级别的语义信息）→ 页面内阅读/下载报告 + 历史报告查看。

## v1 方案评审结论（保留 / 修正 / 删除）

| v1 设计点 | 结论 | 依据 |
|---|---|---|
| subprocess 调用 frost_agent.py | ✅ 保留 | CLI 入口稳定（[frost_agent.py L1584-L1640](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L1584-L1640)，含 `__main__` 守卫），隔离 asyncio |
| Mock 通过 env 变量传递 | ⚠️ 收窄（v2.4） | UI 界面不再暴露 Mock 选项（用户拍板只做真实 API）；`MOCK_LLM`/`MOCK_SEARCH` env 机制在 demo2 后端原样保留，且 subprocess 天然继承环境变量 → **验证/调试时可启动前注入 env 实现低成本跑通，无需 UI 代码** |
| 零侵入（不改 frost_agent.py） | ✅ 保留并升级 | jsonl 机器通道 + stdout 已足够；v2.4 进一步做到 demo2 目录零文件改动（含 README） |
| 报告 glob 回退 | ✅ 保留 | 实际文件名 `{行业}_{UTC时间戳}_UTC_行业定义报告.md`，`*行业定义报告.md` 可匹配（已核实 reports/ 34 个文件全部符合） |
| 进度 = step 标记 + 日志尾部滚动 | ❌ 修正 | 不满足"step 往下一层"需求，改为双层时间线 |
| 阻塞式 `for line in iter(readline)` | ❌ 修正 | 卡死页面无法交互，改为后台线程 + fragment 轮询 |
| `st.session_state.proc` 存 Popen 重挂载 | ⚠️ 简化 | 改为后台线程 + 文件偏移量读取；**代价**：服务重启/关标签页后任务成孤儿（见 P2-6 处理） |
| .env 从求职与发展/demo 复制 | ❌ 删除 | 核实 demo2/.env 已存在 |
| requirements-ui.txt 写 `streamlit>=1.36` | ❌ 修正 | `st.fragment(run_every)` 需 **streamlit>=1.37**（[官方文档](https://docs.streamlit.io/develop/concepts/architecture/fragments)，2026-08-17 查阅，可信度 ★★★★★） |
| UI 放 demo2/ 目录 | ❌ 修正（v2.4） | 用户要求独立目录 → `webui/`；技术前提已验证（PROJECT_ROOT 锚定脚本位置、load_dotenv 从 cwd 查找且子进程 cwd=DEMO2） |

## 现状分析（已核实事实）

### 数据通道 1：stdout（引导 + 兜底，v2.1 降级为辅助角色）

- 步骤边界：`--- Step N: {label} 开始/完成 ---`、`[跳过] Step N: ... — 已从 checkpoint 恢复`
- trace_id 在启动横幅即打印（`trace_id: {id}`）→ 用于定位 jsonl 文件
- jsonl 中**没有**的信息：机械信号行、补搜停止原因原文、`自检结果:`、Token 审计表、`报告文件:`、`[质量门终止]`/`[错误]`
- ⚠️ 全部为裸 `print()` 无 flush，管道下块缓冲 → 必须 `-u` + `PYTHONUNBUFFERED=1`（P0-1）

### 数据通道 2：`logs/{trace_id}.jsonl`（时间线唯一事实源）

- [SessionEventLog.log()](file:///Users/paper/trae_project/行业定义agent/demo2/harness/session_log.py#L60-L85) 每事件 `open(append)+write+close`，close 强制 flush，UI 可实时 tail（已核实源码）
- 事件类型全集（已核实 frost_agent.py 全部 18 处 `logger.log` 调用点，去重后 9 种）：
  `start` / `step_start` / `step_complete` / `search_done` / `llm_raw_response` /
  `supplement_search_done` / `search_gap_record` / `self_check_failed` / `complete`
- **"为什么补搜"的数据源**：`llm_raw_response`（step_id=`1_info_collection_fm_review`）的
  `text_preview`（截断 1000 字符）含 FM 审查 JSON：`data_gaps`、`gap_types`、`suggested_queries`、`yield_evidence`
- `supplement_search_done`：每轮补搜的 queries + 每 query 返回条数
- `search_gap_record`：搜索阶段终态（stop_reason、补搜轮数、剩余缺口、yield_history）
- `step_complete` 字段差异（已核实）：Step1 含 `confidence`（[L1292-L1295](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L1292-L1295)）；
  Step2-4 仅 `step_id`+`quality_flags_count`（[L1392-L1395](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L1392-L1395)）；Step5 含 `overall`+`failed`
- `complete` 事件**不含**报告路径 → 报告路径只能从 stdout `报告文件: ` 解析 + glob 回退
- ⚠️ **Mock 搜索模式直接跳过整个 FM 审查/补搜循环**（[L569-L571](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L569-L571)：
  `if mock_search_mode or not tavily_api_key: return`）→ 全 Mock 下 jsonl 无 fm_review 事件（影响验证设计，见 P1-4）

### 环境事实（2026-08-17 实测）

- demo2/.env 已存在
- 系统 python3 = 3.9.6（无 agent 依赖）；`python3.12` 可用（`~/.local/bin`）；`uv` 可用
- streamlit 未安装于任何已探测到的解释器
- **Q1 已定（用户确认）**：新建隔离 venv（uv venv，python3.12），位于 `webui/.venv-ui`，
  安装 agent 依赖（引用 `../demo2/requirements.txt`）+ streamlit（webui/requirements-ui.txt）→
  派生简化：UI 与子进程同解释器，`subprocess` 直接用 `sys.executable`，无需配置 AGENT_PYTHON 路径
- **目录独立可行性（v2.4 已验证）**：`PROJECT_ROOT = Path(__file__).parent`（[L58](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L58)）→
  agent 的 logs/reports/checkpoints 全部锚定 demo2/ 脚本位置，与启动 cwd 无关；
  `load_dotenv()`（[L52](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L52)）从子进程 cwd（=DEMO2）向上查找 → demo2/.env 正常加载。
  UI 侧读产物用绝对路径：`DEMO2/logs/{trace_id}.jsonl`、`DEMO2/reports/`

## 方案设计

### 1. 进度展示：双层时间线（核心升级）

```
┌ 主区域 ────────────────────────────────────────────────┐
│ ①信息收集 ✅ → ②维度筛选 🔄 → ③结构决策 ⏳ → ④⑤⑥ ⏳      │  ← st.progress(2/6) + 六枚徽章
│                                                        │
│ ▼ Step 1: 信息收集（已完成，3 轮补搜）                    │  ← 每步一个 st.status
│   🔍 初始搜索：3 个 query，全部返回                       │
│   🧠 FM 审查第 1 轮：发现 4 个信息缺口                    │  ← 卡片：缺口摘要（前 2 条）
│      · 缺少国家/行业标准文件原文或标准号…                 │
│      · 缺少与半固态电池的量化区分参数…                    │
│   ⚡ 补搜第 1 轮：2 个 query → 各返回 5 条                │
│   🧠 FM 审查第 2 轮：上轮有收获（GB/T 43568-2026 确认）   │  ← yield_evidence
│   ✅ 补搜结束：无缺口（stop_reason=gaps_closed）          │
│   📝 LLM 总结完成 — 置信度: 高                           │
│ ▶ Step 2: 维度筛选（进行中：LLM 生成中…）                │
│                                                        │
│ ▸ 原始日志（折叠 expander，调试用）                      │
└────────────────────────────────────────────────────────┘
```

**通道分工（v2.1 关键决策，消除双通道重复卡片）**：
- **jsonl = 时间线唯一事实源**：所有语义卡片只从 jsonl 事件生成（event sourcing 思路，
  UI 是事件日志的纯投影；参考 LangSmith/AgentOps 的单通道设计）
- **stdout 只承担三个职责**：① 解析 trace_id 引导 jsonl tail；② 提供 jsonl 没有的信息
  （机械信号、停止原因原文、自检结果、Token 审计、报告路径、错误）；③ jsonl 不可用时的降级展示
- **同一物理事件两通道都有落点时**（补搜轮次、FM 审查、停止原因），只出 jsonl 卡片，
  stdout 对应行进原始日志 expander，不出卡片 → 无需运行时去重
- **时序基准**：事件流用解析端单调递增序号 `seq`（stdout 行无时间戳，不做 wall-clock 排序）

**事件映射表（完整决策，实现时照表解析）**：

| 来源 | 匹配模式 | UI 事件卡片 |
|---|---|---|
| stdout | `trace_id: (\w+)` | 记录 trace_id → 打开 jsonl tail（不渲染卡片） |
| jsonl | `step_start` | 徽章转"进行中"，开新 st.status |
| jsonl | `llm_raw_response` + step_id 含 `fm_review` | 🧠 FM 审查第 N 轮：解析 text_preview JSON → data_gaps 条数+前 2 条摘要、suggested_queries 数；**截断降级（v2.3，裁决 W3）**：text_preview 截断 1000 字符（[L484](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L484)，已核实该事件无完整原文字段），JSON 超限时解析失败 → 降级为正则提取 `data_gaps` 数组条数 + 展示 text_preview 原文前 200 字；再失败则卡片显示"审查完成（返回非结构化）"。单测 fixture 必须覆盖截断场景 |
| jsonl | `supplement_search_done` | ⚡ 补搜第 N 轮：query 数 + 每 query 返回条数 |
| jsonl | `search_gap_record` | 📊 搜索阶段终态：stop_reason、总轮数、剩余缺口数 |
| jsonl | `step_complete` | 徽章转 ✅；Step1 显示 confidence，Step2-4 显示降级标记数，Step5 显示 overall+failed |
| jsonl | `self_check_failed` | ⚠️ 自检失败维度卡片 |
| jsonl | `complete` | 报告生成完成标记（路径另从 stdout 取） |
| stdout | `[跳过] Step (\d)` | 徽章标"已恢复跳过" |
| stdout | `[机械信号] ... unproductive` | ⚠️ 机械信号卡片（jsonl 无此事件） |
| stdout | `[补搜] ... 停止`（止损/轮数上限/关键词穷尽） | ⛔ 停止原因原文卡片（jsonl 的 stop_reason 在终态卡合并展示，不重复出卡） |
| stdout | `自检结果: (.+)` | Step5 结果卡片 |
| stdout | Token 审计表 + `总成本:` | Step6 成本卡片 |
| stdout | `报告文件: (.+)` | 报告就绪 → 渲染 + 下载按钮（glob 回退兜底） |
| stdout | `[质量门终止]` / `[错误]` / exit_code≠0 | ❌ 错误卡片 + 日志尾部 20 行（以 exit_code 为准，正则只是增强） |

**降级策略**：jsonl 文件缺失/损坏 → 时间线退化为 stdout 粗粒度行（step 边界 + 子步骤原文），不崩溃。

**fragment 重绘与展开状态（P2-8 → v2.3 升级，裁决 W5）**：fragment 每 1.5s 重绘会重置容器展开状态。
v2.3 混合方案（已核实 `st.status` 至 1.60 版仍**无 key 参数**，无法用 session_state 持久化展开态，
[官方 API](https://docs.streamlit.io/develop/api-reference/status/st.status)，2026-08-17 查阅，可信度 ★★★★★）：
- **进行中步骤**用 `st.status(expanded=True)`（spinner 视觉，程序控制展开，重置无感知）
- **已完成步骤**改用 `st.expander(key=..., on_change="rerun", expanded=False)`——
  expander 支持 key + session_state 持久化展开态（[官方 API](https://docs.streamlit.io/develop/api-reference/layout/st.expander)），
  fragment 重绘后用户手动展开的回看状态可保留（满足"已完成步骤可回看"需求）

### 2. 执行架构：后台线程 + fragment 轮询

```python
# webui/app.py 顶部：
DEMO2 = Path(__file__).resolve().parent.parent / "demo2"   # v2.4：UI 在 webui/，demo2 用相对锚定

# 全局单例锁（跨会话 + 跨 rerun）：
@st.cache_resource
def get_run_slot():
    return {"lock": threading.Lock(), "run": None}   # P1-5：session_state 是每会话的，锁必须进程级

# 启动（按钮回调，主线程）。v2.3 锁健壮性（裁决 W1）：
slot = get_run_slot()
acquired = slot["lock"].acquire(blocking=False)
if not acquired:
    # 僵尸锁检测：锁被占但 run 已终态（上次 drain 收尾异常）→ 强制重置
    r = slot["run"]
    if r is not None and r["status"] in ("done", "failed", "stopped"):
        try: slot["lock"].release()
        except RuntimeError: pass
        acquired = slot["lock"].acquire(blocking=False)
    if not acquired:
        st.warning("已有任务在运行（可能是其他标签页）"); return
try:
    run = {"events": [], "log": deque(maxlen=2000), "seq": 0, "status": "running",
           "trace_id": None, "report_path": None, "exit_code": None}
    slot["run"] = run
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}          # P0-1：stdout 无缓冲，双保险
    proc = subprocess.Popen([sys.executable, "-u", "frost_agent.py", industry],  # v2.2：同 venv，sys.executable
                            cwd=DEMO2, env=env, stdout=PIPE, stderr=STDOUT, text=True)
    run["proc"] = proc
    threading.Thread(target=drain_proc, args=(proc, run), daemon=True).start()
except Exception:
    slot["lock"].release()   # 启动失败立即释放，不留死锁
    raise

# drain_proc（后台线程，绝不 import/触碰 st.*，只写普通 dict —— P0-2）：
#   v2.3：整个函数体包 try/finally，finally 中统一收尾（裁决 W1）：
#     proc.wait() 回收 → run["status"]="done"/"failed"/"stopped" → slot["lock"].release()
#   即使解析中途抛异常，锁也一定释放（代价：该次时间线可能不完整，可接受）
#   逐行读 stdout → ui_events.parse_stdout_line() → with run_lock: run["events"].append(...)
#   拿到 trace_id 后 tail logs/{trace_id}.jsonl（偏移量增量读，半行保护 —— P2-7）：
#       chunk = f.read(); last_nl = chunk.rfind("\n")
#       last_nl == -1 → seek 回原偏移下次重读；否则只处理 chunk[:last_nl]，偏移推进到 last_nl+1
#   jsonl 事件 → ui_events.parse_jsonl_event() → 并入 events

# v2.3：run_every 常开 1.5s，fragment 内部检查状态（放弃 v2.2 的动态装饰器参数方案，见裁决 W2）
# 装饰器参数在函数定义时求值，依赖"启动后全量 rerun 重定义"时序脆弱；
# 常开方案下 fragment 内：status != running 且本次已渲染终态 → st.rerun() 触发一次全量重跑，
# 主脚本以 run["status"] 非 running 渲染静态终态视图（不再调用 progress_view）→ 轮询自然停止
@st.fragment(run_every=1.5)
def progress_view():
    run = get_run_slot()["run"]
    if run is None: return
    with run_lock: events = list(run["events"])   # 拷贝快照再渲染，避免与线程 append 交叉
    渲染双层时间线（纯渲染，毫秒级）
    if run["status"] != "running": st.rerun()   # 终态：最后一次全量重跑切到静态视图
```

**解析器独立模块（v2.2）**：`ui_events.py`（纯函数，不 import streamlit）承载映射表全部逻辑：
`parse_stdout_line(line, ctx) -> list[Event]`、`parse_jsonl_event(event, ctx) -> list[Event]`、
`tail_jsonl(path, offset) -> (events, new_offset)`。app.py 只做进程管理 + 渲染。
好处：单测无需启动 Streamlit；映射表改动不动 UI 代码。

**停止按钮（P2-9 修正语义）**：`proc.terminate()`（SIGTERM 直接终止进程，可靠；agent 的
KeyboardInterrupt 分支不会执行）+ 10s Timer 兜底 `kill()`；收尾（wait/置状态/释放锁）统一由
drain_proc 末尾负责。UI 文案："已停止。已完成步骤已存档，可用 CLI `--resume` 从最后完成步骤恢复
（当前步骤的搜索/调用成本会重跑）"——checkpoint 只在每步完成后保存（[L1291](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L1291)）。

**孤儿任务提示（P2-6，README 级处理）**：关闭标签页/服务重启不会杀死子进程（产物都落盘，损失限于
进度可见性 + 真实 API 费用）。README 写明"关闭页面不会停止任务，停止请用停止按钮"；
不做 pidfile 扫描（本机单人工具，避免过度设计；记录为未试动作，见下）。

### 3. UI 布局（v2.4：无运行模式控件，仅真实 API）

```
┌─ 侧边栏 ──────────────┐  ┌─ 主区域 ──────────────────────┐
│ • 历史报告下拉          │  │ 标题 + 行业名输入 + [开始][停止] │
│   (reports/ 按 mtime)  │  │ 双层时间线（fragment 轮询）      │
│ • 使用说明             │  │ 报告渲染 + 下载按钮（完成后）    │
│   （含成本提示：        │  │ 原始日志 expander（默认折叠）    │
│    真实 API 按次计费）  │  └────────────────────────────────┘
└───────────────────────┘
```

- **无 Mock 控件（v2.4 用户拍板）**：界面只跑真实 API。使用说明注明成本量级（单次约 2-8 分钟）
- Mock 仍可用于开发验证：启动 streamlit 前注入 env（`MOCK_LLM=true` 等），subprocess 天然继承，
  **UI 代码不含任何 Mock 逻辑**；demo2 后端 `--mock` 与 env 机制原样保留
- 历史报告查看与生成互不冲突（只读文件）

## 具体改动（v2.4：全部位于根目录新建 `webui/`，demo2 零文件改动）

```
行业定义agent/
├── webui/                      ← 新建（本次全部产物）
│   ├── app.py                  Streamlit 应用，约 250 行（进程管理 + fragment 渲染 + 侧边栏）
│   ├── ui_events.py            事件解析器，约 150 行纯函数（映射表 + jsonl tail，不依赖 streamlit）
│   ├── tests/
│   │   └── test_ui_event_parser.py   解析器持久化单测（fixture 覆盖 fm_review/截断/supplement/半行/损坏行）
│   ├── requirements-ui.txt     streamlit>=1.37（agent 依赖直接引用 ../demo2/requirements.txt，不复制）
│   ├── README.md               使用说明：安装/启动/停止/孤儿任务/pkill（W7）
│   └── .venv-ui/               uv venv（python3.12），gitignore
└── demo2/                      ← 零改动（frost_agent.py、models.py、harness/、requirements.txt、.env、README 全部不动）
```

| 文件 | 操作 | 内容 |
|---|---|---|
| `webui/app.py` | 新建 | Streamlit 应用（进程管理 + fragment 渲染 + 侧边栏；`DEMO2 = parent.parent/"demo2"` 锚定） |
| `webui/ui_events.py` | 新建 | 事件解析器纯函数（映射表 + jsonl tail，不依赖 streamlit） |
| `webui/tests/test_ui_event_parser.py` | 新建 | 解析器持久化单测：手工构造 jsonl fixture（含 fm_review/supplement/半行/截断场景），验证卡片事件生成与降级（规则 10.2 要求持久化 test 文件） |
| `webui/requirements-ui.txt` | 新建 | `streamlit>=1.37` |
| `webui/README.md` | 新建 | 「使用」：`cd webui && uv venv .venv-ui && uv pip install -r ../demo2/requirements.txt -r requirements-ui.txt` + `streamlit run app.py` + 孤儿任务注意事项 + 僵尸子进程清理 `pkill -f frost_agent.py`（裁决 W7） |

不修改 demo2/ 下任何文件（比 v2.3 更彻底：README 也不动）。

## 假设与决策

1. **目标 = demo2（v5.2）**：沿用 v1 决策（最新版且唯一匹配需求）
2. **技术栈 = Streamlit ≥1.37**：fragment 是官方推荐的后台任务刷新机制；若需前后端分离可否决改 FastAPI+SSE
3. **UI 目录 = 根目录 webui/（v2.4 用户拍板）**：demo2 零文件改动；技术前提已验证——
   PROJECT_ROOT 锚定脚本位置（产物路径不受启动 cwd 影响）、load_dotenv 从子进程 cwd=DEMO2 加载 .env。
   项目规则"修改在 demo2/"的本意是不动 demo 基线与 agent 代码，新增独立 webui/ 目录不违反
4. **UI 仅真实 API（v2.4 用户拍板）**：无 Mock 控件；demo2 后端 --mock/MOCK_* 机制原样保留；
   开发验证靠启动前 env 注入（subprocess 继承环境变量是 Python 默认行为，UI 代码零 Mock 逻辑）
5. **jsonl 唯一事实源 + stdout 引导/兜底**（v2.1 升级自"双通道平等取数"）：
   critic 指出双通道平等映射必然产生重复卡片（补搜轮次/FM 审查/停止原因三处重叠，已逐一核实源码），
   且两通道时序基准不同无法归并；改为单事实源后去重问题被消除而非被解决。
   未采纳的替代方案：为双通道加 dedup_key 运行时去重——能解决但复杂度高，且 stdout 无时间戳的时序问题仍在
6. **Python 环境 = webui/.venv-ui（用户已确认）**：uv venv（python3.12）+ 引用 ../demo2/requirements.txt + requirements-ui.txt，
   与现有环境隔离且依赖清单单一事实源（不复制 demo2 的 requirements.txt）；
   派生简化：子进程解释器 = `sys.executable`（UI 与 agent 同 venv）
7. **解析器独立 ui_events.py（v2.2）**：纯函数不依赖 streamlit → 单测无需启动 Streamlit，映射表与 UI 解耦
8. **报告 glob 回退收紧（v2.2 + v2.3 裁决 W4）**：`reports/*{glob.escape(行业名)}*行业定义报告.md` 按 mtime 取最新
   （v1 的 `*行业定义报告.md` 会匹配到别的行业的报告；行业名含 `[]*?` 等 glob 特殊字符时用
   `glob.escape` 转义，已核实 glob.escape 为 Python 3.7+ 标准库；行业名解析失败时才退化为全量匹配）
9. **不做用户认证/多用户并发/断点续跑 UI 入口/pidfile 孤儿扫描**：本机单人简易工具；
   孤儿扫描列入未试动作清单（若实际使用中遇到再补）
10. **计划文件在当前工作区 `.trae/documents/`（Plan 约定），实现产物在 webui/**

## 外部评审意见裁决（workbuddy，2026-08-17；规则 11 去偏见化）

> 裁决方法：逐条用源码/官方文档验证技术前提，再决定采纳/修正/驳回。

| # | workbuddy 意见 | 前提验证结果 | 裁决 |
|---|---|---|---|
| W1 | 🔴 裸锁无持有者身份，drain 异常死亡/关标签页后锁永久占用 | 属实：daemon 线程随会话回收，finally 之外的异常路径确实漏 release | ✅ 采纳：drain_proc 全包 try/finally + 启动时僵尸锁检测（run 已终态但锁被占 → 强制重置）+ 启动失败 except 释放。已写入执行架构伪代码 |
| W2 | 🔴 run_every 装饰器参数定义时求值，动态化可能不成立 | 属实：装饰器参数在函数定义时求值；v2.2 依赖"启动后全量 rerun 重定义"的时序确实脆弱 | ✅ 采纳（改方案）：run_every 常开 1.5s，fragment 内检测终态后 st.rerun() 切静态视图停止轮询。未采纳其"st.stop()"建议——st.stop 只中止当次执行不阻止 run_every 下次触发，空转仍在 |
| W3 | 🟡 text_preview 截断 1000 字符导致 JSON 解析失败 | 部分属实：截断确实存在（[L484](file:///Users/paper/trae_project/行业定义agent/demo2/frost_agent.py#L484) 已核实）；但其建议"从 event['content']/event['response'] 原始字段解析"**前提不成立**——已核实 llm_raw_response 事件只有 step_id/round_label/text_preview 三个字段，无完整原文 | ⚠️ 部分采纳：零侵入约束下无完整原文可用 → 加两级降级（正则提取 data_gaps 条数 → 展示原文前 200 字），单测覆盖截断 fixture。驳回"换原始字段"建议（字段不存在） |
| W4 | 🟡 glob 行业名特殊字符 | 属实：glob 对 `[]*?` 敏感；glob.escape 为 Python 3.7+ 标准库 | ✅ 采纳：glob.escape(行业名) |
| W5 | 🟡 已完成步骤恒折叠导致无法回看 | 需求合理；但其建议"st.status 展开态存 session_state"**前提不成立**——已核实 st.status 至 1.60 版无 key 参数（[官方 API](https://docs.streamlit.io/develop/api-reference/status/st.status)，2026-08-17，★★★★★） | ⚠️ 部分采纳：改用混合方案——进行中步骤 st.status，已完成步骤改 st.expander（支持 key+session_state 持久化展开态，[官方 API](https://docs.streamlit.io/develop/api-reference/layout/st.expander)）。驳回原实现路径，采纳需求本身 |
| W6 | 🟡 停止后立刻关页面 → daemon 线程被杀 → 锁不释放 | 与 W1 同根因 | ✅ 合并入 W1 处理（僵尸锁检测覆盖此场景） |
| W7 | README 补 pkill 清理僵尸子进程 | 合理 | ✅ 采纳 |
| W8 | fixture 易随日志格式失效，建议写提取说明 | 合理且符合用户"低开销"偏好 | ✅ 采纳：测试文件头部 docstring 写明"从真实 logs/{trace_id}.jsonl 提取 fixture"的步骤，不写独立脚本（避免过度设计） |
| W9 | 渲染逻辑拆 ui_render.py | 不采纳：当前总规模 ~400 行，拆三个文件反而增加跳转成本；若实施中超 500 行再拆（记入未试动作） | ❌ 驳回（记录理由：规模未达拆分阈值） |
| W10 | 半 Mock 验证标为可选（依赖真实 TAVILY key） | 合理 | ✅ 采纳：验证步骤 3 标注"可选（需有效 TAVILY_API_KEY）" |
| W11 | 性能：事件多时重绘开销 | 与既有未试动作"已完成步骤移出 fragment"重合 | ✅ 已有覆盖，不重复记录 |

**经验证无反驳点的采纳**：W1/W4/W7/W8/W10。**前提不成立但需求合理的修正采纳**：W3/W5。
**驳回并记录理由**：W9。

## 验证步骤（v2.4：UI 无 Mock 控件，Mock 场景通过启动前 env 注入实现）

1. **语法 + 单测**（webui/.venv-ui 解释器）：`python -m py_compile app.py ui_events.py`；
   `pytest tests/test_ui_event_parser.py`（fixture 覆盖：fm_review 缺口卡片、**text_preview 截断降级（W3）**、
   supplement 卡片、半行 jsonl、损坏行降级、exit_code≠0 错误卡片；
   fixture 提取方法写在测试文件 docstring —— W8）
2. **UI 骨架端到端（env 注入全 Mock，不花钱）**：
   `MOCK_LLM=true MOCK_SEARCH=true streamlit run app.py` → 输入"测试行业" → 提交 → 验证：
   - 六枚徽章状态流转正确（全 Mock 下 Step1 只有"初始搜索+LLM总结"两张卡片，**无 FM/补搜卡片属预期**）
   - 首个事件在提交后 2s 内出现（P0-1 缓冲修复的显式断言）
   - 执行中页面可交互（停止按钮可终止）；完成后报告渲染 + 下载可用；历史下拉出现新报告
   - **锁健壮性（W1）**：完成后立即再次提交新任务能成功启动（锁已释放）
   - **回看展开（W5）**：完成后手动展开已完成步骤的 expander，等待数秒后展开态保留
   - **产物落盘位置**：报告/checkpoint 仍在 demo2/reports、demo2/checkpoints（验证 webui/ 目录独立的正确性）
3. **语义卡片验证（env 注入半 Mock，可选 —— W10）**：
   `MOCK_LLM=true streamlit run app.py`（真实 TAVILY 搜索 + 真实 FM 审查循环 + 预设 LLM 响应）
   → 验证 🧠/⚡/📊 卡片在真实事件流下渲染正确、无重复卡片
4. **异常路径**：空输入（按钮禁用）；执行中重复提交（禁用）；双标签页同时提交（第二个被全局锁拒绝）；
   jsonl 缺失时降级为 stdout 展示不崩溃；**僵尸锁场景（W1/W6）**：模拟 drain 异常后再次提交，僵尸锁检测能重置
5. **真实 API 冒烟（正式使用路径）**：正常启动 `streamlit run app.py`（无 env 注入）→
   跑一个真实行业，确认全流程 + FM/补搜语义卡片 + 成本卡片（界面无 Mock 入口，即用户真实使用形态）
6. **回归确认**：`frost_agent.py "任意行业" --mock` CLI 不受影响（demo2 零改动）

## 未试动作清单（本次不做，供迭代）

- 孤儿任务 pidfile 扫描与侧边栏提示（P2-6 完整方案）
- 已完成步骤移出 fragment 避免重绘（P2-8 方案 b；兼覆盖 W11 性能建议）
- UI 内 `--resume` 恢复入口
- 多任务并行队列（当前全局单任务锁）
- 渲染逻辑拆分 ui_render.py（W9，若 app.py 实施中超 500 行再做）
