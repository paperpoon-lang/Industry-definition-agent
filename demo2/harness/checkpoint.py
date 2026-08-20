"""v5.2 升级：CheckpointManager — 多版本 Checkpoint + 过期清理。

v4 的 save_checkpoint() 是覆盖写入，崩溃后只能恢复到最新版本，无法回滚到历史版本。
v5 升级：每次 save 创建新版本文件，自动保留 7 天，文件命名考虑 request_id 扩展性。

v5.1 修正（评议 Q1/Q2 + 二次评议）：
- 清理逻辑从文件名字符串解析改为文件内 saved_at 字段（消除碰撞风险）
- load_version 的 step_id 改为必填（避免 glob 返回随机匹配）
- fromisoformat 跨版本兼容（Python 3.9 不支持 Z 后缀，用 .replace("Z", "+00:00")）
- load() 处理 v4 遗留格式（纯 ReportState）和 v5 包装格式
- 损坏文件分层清理（JSONDecodeError 直接删除，其他解析问题保留并记录）
- glob 模式 {step_id}_* → {step_id}*（P0-2 修正：无 request_id 时不匹配 _*）

签名兼容 v4 的 save_checkpoint() / try_resume()。

关键约束：
- 清理逻辑需有单元测试（时间判断 bug 会导致磁盘占满）
- 文件命名考虑 request_id 扩展性（阶段三并发场景）
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


class CheckpointManager:
    """v5 升级：多版本 Checkpoint + 过期清理。

    v5.1 修正（评议 Q1 + 二次评议）：
    - 清理逻辑从文件名解析改为文件内 saved_at 字段
    - load_version 的 step_id 改为必填
    - load() 兼容 v4 遗留格式（纯 ReportState）和 v5 包装格式
    - 损坏文件分层清理

    签名兼容 v4 的 save_checkpoint() / try_resume()。
    """

    def __init__(
        self,
        checkpoint_dir: str = "checkpoints",
        retention_days: int = 7,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True, parents=True)
        self.retention_days = retention_days

    # ----------------------------------------------------------
    # 保存（签名兼容 v4 save_checkpoint）
    # ----------------------------------------------------------

    def save(
        self,
        state,
        step_id: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Path:
        """保存当前 State 到新版本文件。

        签名兼容 v4 save_checkpoint(state, step_id)。
        request_id 为可选参数，阶段三并发场景使用。
        trace_id 为可选参数（v5.2 P2-15：wrapper 增加 trace_id 字段）。

        v5.1 修正：写入包装格式 {"saved_at": ..., "state": ...}，
        清理逻辑读取 saved_at 字段而非文件名解析。

        Args:
            state: ReportState 对象
            step_id: 当前步骤标识
            request_id: 可选，阶段三并发场景使用
            trace_id: 可选，v5.2 新增，便于关联日志

        Returns:
            保存的文件路径
        """
        # 文件命名：{industry}_{timestamp}_{step_id}[_{request_id}].json
        safe_name = state.industry_name.replace("/", "_").replace(" ", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        parts = [safe_name, timestamp, step_id]
        if request_id:
            parts.append(request_id)
        filename = "_".join(parts) + ".json"
        path = self.checkpoint_dir / filename

        # v5.1 修正：包装格式，saved_at 用于清理逻辑
        # v5.2 P2-15：wrapper 增加 trace_id 字段
        wrapper: dict = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "step_id": step_id,
            "state": json.loads(state.model_dump_json()),  # ReportState 的 JSON
        }
        if trace_id:
            wrapper["trace_id"] = trace_id

        path.write_text(
            json.dumps(wrapper, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 同时更新 latest 指针（兼容 v4 try_resume 的"读最新"语义）
        latest_path = self._latest_path(state.industry_name)
        try:
            latest_path.write_text(path.name, encoding="utf-8")
        except (IOError, OSError) as e:
            print(f"[Checkpoint] latest 指针更新失败（不影响主流程）: {e}")

        # 顺手清理过期文件
        self._cleanup_expired()

        return path

    # ----------------------------------------------------------
    # 加载最新（签名兼容 v4 try_resume）
    # ----------------------------------------------------------

    def load(self, industry_name: str):
        """尝试从最新 checkpoint 恢复。

        签名兼容 v4 try_resume(industry_name)。

        v5.1 修正（二次评议 Q1-B）：兼容 v4 遗留格式（纯 ReportState）
        和 v5 包装格式（{"saved_at": ..., "state": ...}）。
        """
        from models import ReportState

        latest_path = self._latest_path(industry_name)
        if not latest_path.exists():
            return None
        filename = latest_path.read_text(encoding="utf-8").strip()
        path = self.checkpoint_dir / filename
        if not path.exists():
            return None
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            # v5 包装格式：提取 state 字段
            if isinstance(data, dict) and "state" in data and "saved_at" in data:
                return ReportState.model_validate(data["state"])
            # v4 遗留格式：直接是 ReportState
            return ReportState.model_validate(data)
        except Exception as e:
            print(f"[Checkpoint] 加载失败: {e}")
            return None

    # ----------------------------------------------------------
    # 加载历史版本（v5 新增，阶段三 Evaluator-Optimizer 闭环用）
    # ----------------------------------------------------------

    def load_version(
        self,
        industry_name: str,
        timestamp: str,
        step_id: str,  # v5.1 修正：从 Optional 改为必填（评议 Q2）
    ):
        """v5 新增：按时间戳 + step_id 加载历史版本。

        v5.1 修正（评议 Q2）：step_id 改为必填，避免 glob 返回随机匹配。
        v5.1 修正（P0-2）：glob 模式从 {step_id}_* 改为 {step_id}*，
        无 request_id 时文件名是 {step_id}.json，不匹配 _*。

        Args:
            industry_name: 行业名
            timestamp: 版本时间戳，格式 YYYYMMDD_HHMMSS
            step_id: 必填，指定步骤

        Returns:
            ReportState 或 None
        """
        from models import ReportState

        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        # P0-2 修正：{step_id}_* → {step_id}*（无 request_id 时不匹配 _*）
        pattern = f"{safe_name}_{timestamp}_{step_id}*"
        matches = list(self.checkpoint_dir.glob(pattern + ".json"))
        if not matches:
            return None
        try:
            raw_text = matches[0].read_text(encoding="utf-8")
            data = json.loads(raw_text)
            # v5 包装格式
            if isinstance(data, dict) and "state" in data and "saved_at" in data:
                return ReportState.model_validate(data["state"])
            # v4 遗留格式
            return ReportState.model_validate(data)
        except Exception as e:
            print(f"[Checkpoint] load_version 失败: {e}")
            return None

    # ----------------------------------------------------------
    # 内部辅助
    # ----------------------------------------------------------

    def _latest_path(self, industry_name: str) -> Path:
        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        return self.checkpoint_dir / f"{safe_name}_latest.txt"

    def _cleanup_expired(self) -> None:
        """v5.1 修正：清理过期 Checkpoint 文件，基于文件内 saved_at 字段。

        v5.0 的文件名字符串解析有碰撞风险（行业名含 YYYYMMDD_HHMMSS 时误判）。
        v5.1 改用文件内 saved_at 字段，完全不依赖文件名解析。

        v5.1 修正（二次评议 Q1-C）：损坏文件分层清理：
        - JSONDecodeError：直接删除（无恢复价值）
        - 其他解析问题：保留并记录（可能是未来版本格式）
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

        for path in self.checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))

                # v5 包装格式：读取 saved_at 字段
                if isinstance(data, dict) and "saved_at" in data:
                    # v5.1 修正（二次评议 Q1-A）：Python 3.9 不支持 Z 后缀
                    saved_at_str = data["saved_at"].replace("Z", "+00:00")
                    saved_at = datetime.fromisoformat(saved_at_str)
                    if saved_at < cutoff:
                        path.unlink(missing_ok=True)
                    continue

                # v4 遗留格式：无 saved_at 字段
                # 检查是否是有效的 ReportState（有 industry_name 字段）
                if isinstance(data, dict) and "industry_name" in data:
                    # v4 文件无法判断时间，保留不删（保守策略）
                    # v4 文件会在自然迭代中被 v5 文件替代
                    continue

                # 既不是 v5 包装格式，也不是 v4 ReportState：未知格式，保留并记录
                print(f"[Checkpoint 清理] 跳过未知格式文件: {path.name}")

            except json.JSONDecodeError:
                # v5.1 修正（二次评议 Q1-C）：损坏文件，直接删除（无恢复价值）
                path.unlink(missing_ok=True)
            except (KeyError, ValueError) as e:
                # v5.1 修正：其他解析问题，保留并记录（可能是未来版本格式）
                print(f"[Checkpoint 清理] 跳过无法解析的文件: {path.name} ({e})")
            except Exception as e:
                # 其他意外错误，保留并记录
                print(f"[Checkpoint 清理] 跳过文件 {path.name}（意外错误）: {e}")


# ============================================================
# v4 兼容函数（保持 save_checkpoint / try_resume 可调用）
# ============================================================

# 全局单例（v4 代码直接调用 save_checkpoint / try_resume，v5 通过 CheckpointManager 实例）
_default_manager: Optional[CheckpointManager] = None


def _get_default_manager() -> CheckpointManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = CheckpointManager()
    return _default_manager


def save_checkpoint(state, step_id: str) -> None:
    """v4 兼容：保存 checkpoint（委托给 CheckpointManager.save）。"""
    _get_default_manager().save(state, step_id)


def try_resume(industry_name: str):
    """v4 兼容：尝试恢复（委托给 CheckpointManager.load）。"""
    return _get_default_manager().load(industry_name)
