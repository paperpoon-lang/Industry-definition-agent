"""行业定义 Agent Web UI（计划 v2.4）。

仅真实 API 模式（界面无 Mock 控件；开发验证可启动前注入 MOCK_LLM/MOCK_SEARCH env，
subprocess 天然继承，UI 代码零 Mock 逻辑）。

架构要点：
- subprocess 启动 demo2/frost_agent.py（cwd=demo2，.env 由 load_dotenv 从 cwd 加载）
- 后台 daemon 线程 drain stdout + tail demo2/logs/{trace_id}.jsonl → 写普通 dict（不碰 st.*）
- jsonl = 时间线唯一事实源；stdout 只做引导/兜底/独有信息（fallback_only 事件在 jsonl 激活时被过滤）
- fragment(run_every=1.5) 轮询渲染；终态时 st.rerun() 切静态视图停止轮询
- 全局单任务锁：cache_resource 进程级 + try/finally 收尾 + 僵尸锁检测（裁决 W1）
"""

from __future__ import annotations

import glob as globmod
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import streamlit as st

from ui_events import parse_jsonl_event, parse_stdout_line, tail_jsonl

DEMO2 = Path(__file__).resolve().parent.parent / "demo2"
REPORTS_DIR = DEMO2 / "reports"
LOGS_DIR = DEMO2 / "logs"
STEP_LABELS = {1: "信息收集", 2: "维度筛选", 3: "结构决策", 4: "内容生成", 5: "自检", 6: "输出"}

st.set_page_config(page_title="行业定义Agent", layout="wide")


# ---------------- 全局运行槽（跨会话 + 跨 rerun 单例） ----------------

@st.cache_resource
def get_run_slot():
    return {"lock": threading.Lock(), "run": None}


def _acquire_slot(slot: dict) -> bool:
    """获取全局任务锁；含僵尸锁检测（run 已终态但锁未释放 → 强制重置）。"""
    if slot["lock"].acquire(blocking=False):
        return True
    r = slot["run"]
    if r is not None and r.get("status") in ("done", "failed", "stopped"):
        try:
            slot["lock"].release()
        except RuntimeError:
            pass
        return slot["lock"].acquire(blocking=False)
    return False


# ---------------- 后台 drain 线程 ----------------

def _drain_proc(proc: subprocess.Popen, run: dict, slot: dict) -> None:
    """后台线程：读 stdout + tail jsonl → 写 run dict。绝不触碰 st.*（P0-2）。

    整个函数体 try/finally 保证锁一定释放（裁决 W1）。
    """
    ctx = {"trace_id": None, "jsonl_active": False, "jsonl_offset": 0}
    run["ctx"] = ctx
    try:
        for line in iter(proc.stdout.readline, ""):
            run["log"].append(line.rstrip())
            for ev in parse_stdout_line(line, ctx):
                run["events"].append(ev)
            # 拿到 trace_id 后开始 tail jsonl（每读到一行 stdout 就尝试一次，文件可能还没创建）
            if ctx["trace_id"] and not ctx["jsonl_active"]:
                if (LOGS_DIR / f"{ctx['trace_id']}.jsonl").exists():
                    ctx["jsonl_active"] = True
            if ctx["jsonl_active"]:
                raw_events, ctx["jsonl_offset"] = tail_jsonl(
                    LOGS_DIR / f"{ctx['trace_id']}.jsonl", ctx["jsonl_offset"])
                for raw in raw_events:
                    for ev in parse_jsonl_event(raw, ctx):
                        run["events"].append(ev)
        proc.wait()
        run["exit_code"] = proc.returncode
        # 收尾再 tail 一次，捞最后落盘的事件
        if ctx["jsonl_active"]:
            raw_events, ctx["jsonl_offset"] = tail_jsonl(
                LOGS_DIR / f"{ctx['trace_id']}.jsonl", ctx["jsonl_offset"])
            for raw in raw_events:
                for ev in parse_jsonl_event(raw, ctx):
                    run["events"].append(ev)
        if run.get("stop_requested"):
            run["status"] = "stopped"
        elif proc.returncode == 0:
            run["status"] = "done"
        else:
            run["status"] = "failed"
    except Exception as e:  # 解析异常不吞状态
        run["status"] = "failed"
        run["events"].append({"step": None, "kind": "error", "icon": "❌",
                              "title": "UI 解析异常", "detail": str(e), "fallback_only": False})
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        slot["lock"].release()


# ---------------- 启动 / 停止 ----------------

def start_run(industry: str) -> None:
    slot = get_run_slot()
    if not _acquire_slot(slot):
        st.warning("已有任务在运行（可能是其他标签页）")
        return
    try:
        run = {
            "industry": industry,
            "events": [],
            "log": deque(maxlen=2000),
            "status": "running",
            "exit_code": None,
            "report_path": None,
            "stop_requested": False,
            "proc": None,
            "ctx": None,
        }
        slot["run"] = run
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # P0-1：stdout 无缓冲
        proc = subprocess.Popen(
            [sys.executable, "-u", "frost_agent.py", industry],
            cwd=str(DEMO2), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        run["proc"] = proc
        threading.Thread(target=_drain_proc, args=(proc, run, slot), daemon=True).start()
    except Exception:
        slot["lock"].release()  # 启动失败立即释放，不留死锁
        raise


def stop_run() -> None:
    run = get_run_slot().get("run")
    if run and run.get("proc") and run["proc"].poll() is None:
        run["stop_requested"] = True
        run["proc"].terminate()  # SIGTERM 直接终止；收尾由 drain 线程 finally 负责
        threading.Timer(10.0, lambda: run["proc"].kill()
                        if run["proc"].poll() is None else None).start()


# ---------------- 报告定位 ----------------

def find_report(industry: str, run: dict) -> Path | None:
    # 优先：stdout "报告文件: " 行
    for ev in reversed(run["events"]):
        if ev["kind"] == "report_ready" and ev.get("detail"):
            p = Path(ev["detail"])
            if p.exists():
                return p
    # 回退：glob（行业名转义，裁决 W4）
    pattern = str(REPORTS_DIR / f"*{globmod.escape(industry)}*行业定义报告.md")
    matches = sorted(globmod.glob(pattern), key=lambda f: Path(f).stat().st_mtime, reverse=True)
    if matches:
        return Path(matches[0])
    # 最后回退：全量匹配取最新
    matches = sorted(globmod.glob(str(REPORTS_DIR / "*行业定义报告.md")),
                     key=lambda f: Path(f).stat().st_mtime, reverse=True)
    return Path(matches[0]) if matches else None


def list_history() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("*行业定义报告.md"),
                  key=lambda f: f.stat().st_mtime, reverse=True)


# ---------------- 渲染 ----------------

def _visible_events(run: dict) -> list[dict]:
    """jsonl 激活时过滤 fallback_only 事件（唯一事实源，无重复卡片）。"""
    active = bool(run.get("ctx") and run["ctx"].get("jsonl_active"))
    return [e for e in run["events"] if not (active and e.get("fallback_only"))]


def render_timeline(events: list[dict], current_status: str) -> None:
    """双层时间线：顶部六枚徽章 + 每步内事件卡片。"""
    # 计算每步状态
    step_state = {n: "pending" for n in range(1, 7)}
    for e in events:
        n = e.get("step")
        if not n:
            continue
        if e["kind"] == "step_start" and step_state[n] == "pending":
            step_state[n] = "running"
        elif e["kind"] == "step_complete":
            step_state[n] = "done"
    if current_status in ("done", "failed", "stopped"):
        for n in range(1, 7):
            if step_state[n] == "running":
                step_state[n] = "done" if current_status == "done" else "error"
        # Step 6 在 jsonl 中无 step_start/step_complete 事件（frost_agent 输出步骤不记），
        # 整体成功时报告已产出 → 补标为 done，避免徽章停在 ⏳
        if current_status == "done" and step_state[6] == "pending":
            step_state[6] = "done"

    done_count = sum(1 for s in step_state.values() if s in ("done", "error"))
    st.progress(min(done_count / 6, 1.0),
                text=f"进度：{done_count}/6 步")

    cols = st.columns(6)
    icons = {"pending": "⏳", "running": "🔄", "done": "✅", "error": "❌"}
    for i, n in enumerate(range(1, 7)):
        cols[i].markdown(
            f"<div style='text-align:center;font-size:0.85em'>"
            f"{icons[step_state[n]]} {n}.{STEP_LABELS[n]}</div>",
            unsafe_allow_html=True)

    # 每步的事件卡片
    global_events = [e for e in events if e.get("step") is None]
    for e in global_events:
        _render_card(e)

    for n in range(1, 7):
        step_events = [e for e in events if e.get("step") == n and e["kind"] != "step_start"]
        state = step_state[n]
        if state == "pending" and not step_events:
            continue
        label = f"Step {n}: {STEP_LABELS[n]}"
        if state == "running":
            # 进行中步骤：st.status（spinner，程序控制展开，重绘重置无感知）
            with st.status(label, expanded=True, state="running"):
                for e in step_events:
                    _render_card(e)
        else:
            # 已完成步骤：st.expander（key 持久化展开态，支持回看 —— 裁决 W5）
            icon = {"done": "✅", "error": "❌", "pending": "⏳"}[state]
            with st.expander(f"{icon} {label}", expanded=False,
                             key=f"step_exp_{n}", on_change="rerun"):
                for e in step_events:
                    _render_card(e)


def _render_card(e: dict) -> None:
    if e["kind"] == "step_complete":
        st.markdown(f"**{e['icon']} {e['title']}**" + (f" — {e['detail']}" if e.get("detail") else ""))
    elif e["kind"] == "error":
        st.error(f"{e['icon']} {e['title']}" + (f"：{e['detail']}" if e.get("detail") else ""))
    else:
        st.markdown(f"{e['icon']} **{e['title']}**")
        if e.get("detail"):
            st.caption(e["detail"])


# ---------------- 主界面 ----------------

st.title("行业定义Agent")
st.caption("输入行业名称，实时查看六步分析过程（含补搜原因），生成完整行业定义报告。真实 API 模式，单次约 2-8 分钟。")

slot = get_run_slot()
run = slot.get("run")
running = bool(run and run["status"] == "running")

# 侧边栏
with st.sidebar:
    st.subheader("历史报告")
    history = list_history()
    pick = st.selectbox("查看历史报告", [f.name for f in history],
                        index=None, placeholder=f"共 {len(history)} 篇报告，点击选择")
    if pick:
        target = REPORTS_DIR / pick
        if target.exists():
            st.markdown(target.read_text(encoding="utf-8"))
            st.download_button("下载该报告", target.read_text(encoding="utf-8"),
                               file_name=target.name, mime="text/markdown")
    st.divider()
    # 使用说明入口（左下角按钮 → 弹窗）
    if st.button("📖 使用说明", use_container_width=True):
        st.session_state.show_help = True

# 使用说明弹窗
if st.session_state.get("show_help"):
    @st.dialog("使用说明")
    def help_dialog():
        st.markdown(
            "1. 输入行业名称 → 点「开始生成」\n"
            "2. 时间线实时展示每步进展（FM 审查/补搜原因/自检结果）\n"
            "3. 完成后报告直接渲染在下方，可下载\n"
            "4. **关闭页面不会停止任务**，请用「停止」按钮\n"
            "5. 真实 API 按次计费，请确认行业名无误再提交")
        if st.button("知道了", type="primary", use_container_width=True):
            st.session_state.show_help = False
            st.rerun()

    help_dialog()

# 输入区
c1, c2, c3 = st.columns([4, 1, 1])
with c1:
    industry = st.text_input("行业名称", placeholder="如：低空经济物流（输入后按 Enter 或点别处生效）",
                             disabled=running, label_visibility="collapsed")
with c2:
    if st.button("开始生成", disabled=running or not industry.strip(),
                 type="primary", use_container_width=True):
        start_run(industry.strip())
        st.rerun()
with c3:
    if st.button("停止", disabled=not running, use_container_width=True):
        stop_run()

# 进度区（fragment 轮询）
run = slot.get("run")  # 刷新引用（start_run 可能刚创建）

if run is not None:
    if run["status"] == "running":
        @st.fragment(run_every=1.5)
        def progress_view():
            r = get_run_slot().get("run")
            if r is None:
                return
            events = _visible_events(r)
            render_timeline(events, r["status"])
            with st.expander("原始日志", expanded=False):
                st.code("\n".join(list(r["log"])[-30:]) or "（等待输出…）", language=None)
            if r["status"] != "running":
                st.rerun()  # 终态：切静态视图，停止轮询

        progress_view()
    else:
        # 终态静态视图
        events = _visible_events(run)
        render_timeline(events, run["status"])

        if run["status"] == "stopped":
            st.warning("已停止。已完成步骤已存档，可用 CLI `python frost_agent.py \"行业名\" --resume` "
                       "从最后完成步骤恢复（当前步骤的搜索/调用成本会重跑）。")
        elif run["status"] == "failed":
            st.error(f"执行失败（退出码 {run['exit_code']}）。完整日志见下方。")
            with st.expander("完整日志（尾部 50 行）", expanded=True):
                st.code("\n".join(list(run["log"])[-50:]), language=None)

        if run["status"] == "done":
            report_path = find_report(run["industry"], run)
            if report_path and report_path.exists():
                st.divider()
                st.subheader("📄 报告正文")
                content = report_path.read_text(encoding="utf-8")
                st.markdown(content)
                st.download_button("下载 .md 报告", content,
                                   file_name=report_path.name, mime="text/markdown")
            else:
                st.warning("未找到报告文件，请检查 demo2/reports/ 目录。")

        with st.expander("原始日志", expanded=False):
            st.code("\n".join(list(run["log"])[-100:]), language=None)
