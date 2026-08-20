"""v5.2 升级：SessionEventLog — JSONL 持久化日志，带 trace_id（注入式）。

v4 的 SimpleLogger 只 print 到 stdout，调试只能 grep 终端输出，无法跨会话查询。
v5 升级到 JSONL 文件，append-only，支持查询接口，每个事件加 trace_id。

v5.1 修正（评议 Q5）：
- trace_id 由 Orchestrator 统一生成并注入，消除 SessionEventLog 和 TokenAudit 的隐式依赖
- __init__ 的目录创建增加降级处理，磁盘满时不崩溃

签名兼容 v4 的 SimpleLogger.log()，但内部实现完全替换。

关键约束：
- 日志写入失败不应导致主流程崩溃，需 try/except 包裹并降级到 print
- 每个事件加 trace_id 字段，串联同一次运行的所有日志
- 文件名含 trace_id，便于按运行查询
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class SessionEventLog:
    """v5 升级：JSONL 持久化日志，带 trace_id。

    v5.1 修正（评议 Q5）：
    - trace_id 从外部注入（由 Orchestrator 统一生成），不再自己生成
    - __init__ 的目录创建增加降级处理，磁盘满时不崩溃

    签名兼容 v4 的 SimpleLogger.log()，但内部实现完全替换。
    """

    def __init__(
        self,
        industry_name: str,
        trace_id: str,
        log_dir: str = "logs",
    ):
        """v5.1 修正：trace_id 从外部注入。

        Args:
            industry_name: 行业名
            trace_id: 由 Orchestrator 统一生成的 trace_id（uuid.uuid4().hex[:12]）
            log_dir: 日志目录
        """
        self.industry = industry_name
        self.trace_id = trace_id  # v5.1：从外部注入
        self.log_dir = Path(log_dir)
        try:
            self.log_dir.mkdir(exist_ok=True, parents=True)
            self.log_path = self.log_dir / f"{self.trace_id}.jsonl"
        except (IOError, OSError) as e:
            # v5.1 修正：目录创建失败也降级，不崩溃
            print(f"[日志目录创建失败，降级到 print-only 模式] {e}")
            self.log_path = None  # 标记为 print-only

    def log(self, event_type: str, data: dict) -> None:
        """签名兼容 v4 SimpleLogger.log()。

        v3.1 约束：日志写入失败降级到 print，不抛异常。
        """
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "industry": self.industry,
            "event_type": event_type,
            "data": data,
        }
        line = json.dumps(event, ensure_ascii=False)

        # v5.1：log_path 为 None 时只 print
        if self.log_path is None:
            print(line)
            return

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except (IOError, OSError) as e:
            # v3.1 约束：降级到 print，不抛异常
            print(f"[日志写入失败，降级到 print] {e}")
            print(line)

    def query(
        self,
        event_type: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> list[dict]:
        """v5 新增：按 event_type / step_id 过滤查询。"""
        results: list[dict] = []
        if self.log_path is None or not self.log_path.exists():
            return results
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event_type and event.get("event_type") != event_type:
                        continue
                    if step_id and event.get("data", {}).get("step_id") != step_id:
                        continue
                    results.append(event)
        except (IOError, OSError) as e:
            print(f"[日志查询失败] {e}")
        return results
