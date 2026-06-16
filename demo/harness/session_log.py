"""v4 Demo 打桩：简化版日志组件。

未来可替换为 SessionEventLog（JSONL 追加写入）。
"""

import json
from datetime import datetime


class SimpleLogger:
    """简化版日志：print + 可选文件写入。未来可替换为 SessionEventLog。"""

    def __init__(self, industry_name: str):
        self.industry = industry_name

    def log(self, event_type: str, data: dict):
        msg = f"[{datetime.now():%H:%M:%S}] [{event_type}] {json.dumps(data, ensure_ascii=False)}"
        print(msg)
