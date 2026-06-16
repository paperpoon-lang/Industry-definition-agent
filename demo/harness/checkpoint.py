"""v4 Demo 打桩：简单 JSON 文件读写。

未来可替换为 CheckpointManager（多版本管理）。
"""

import json
from pathlib import Path

CHECKPOINT_DIR = Path("checkpoints")
CHECKPOINT_DIR.mkdir(exist_ok=True)


def save_checkpoint(state, step_id: str):
    """保存当前 State 到 JSON 文件（覆盖写入）。

    Args:
        state: ReportState 对象（有 model_dump_json 方法）
        step_id: 当前步骤标识
    """
    path = CHECKPOINT_DIR / f"{state.industry_name}.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def try_resume(industry_name: str):
    """尝试从 checkpoint 恢复。

    Args:
        industry_name: 行业名称

    Returns:
        ReportState 或 None
    """
    from models import ReportState

    path = CHECKPOINT_DIR / f"{industry_name}.json"
    if not path.exists():
        return None
    try:
        return ReportState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
