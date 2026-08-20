"""v5.2 新增：OutputSafety — 输出安全，防止报告覆盖写入。

v4 的报告保存是覆盖写入。阶段一收尾 P1-2 已做临时修复（追加本地时间戳），
但本地时间戳在不同时区运行时会碰撞。

v5 设计：时间戳使用 UTC + 时区标注，检测到已存在时追加版本号。

v5.1 补充（评议 P3-12）：时区标注的用途说明——价值在可读性（避免非技术用户
误读 UTC 为本地时间），非防碰撞（碰撞由秒级精度 + 版本号解决）。

v5.2 P2-13：版本号上限（max_versions = 100），防止极端情况下无限循环。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class OutputSafety:
    """v5 新增：输出安全，防止报告覆盖写入。

    v3.1 关键约束：
    - 时间戳使用 UTC + 时区标注（避免不同时区运行时碰撞）
    - 检测到已存在时追加版本号

    v5.1 补充（评议 P3-12）：时区标注的用途是可读性——
    UTC 时间戳（如 20250618_143052）对非技术用户不直观，可能误读为本地时间。
    'UTC' 标注能避免误读，成本仅是文件名多 4 个字符。
    碰撞防护由秒级精度 + 版本号追加解决，不依赖时区标注。

    v5.2 P2-13：版本号上限 max_versions=100，防止极端情况下无限循环。
    """

    def __init__(self, reports_dir: str = "reports", max_versions: int = 100):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True, parents=True)
        self.max_versions = max_versions

    def safe_save(self, content: str, industry_name: str) -> Path:
        """安全保存报告，返回最终文件路径。

        文件名格式：{industry}_{UTC时间戳}_{时区}_行业定义报告.md
        若已存在，追加版本号：..._v2.md、..._v3.md
        版本号上限 max_versions（v5.2 P2-13），超过则覆盖最新版本。

        Args:
            content: 报告内容（Markdown）
            industry_name: 行业名

        Returns:
            最终保存的文件路径
        """
        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        # UTC 时间戳 + 时区标注
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        tz_label = "UTC"

        base_filename = f"{safe_name}_{timestamp}_{tz_label}_行业定义报告"
        path = self.reports_dir / f"{base_filename}.md"

        # 检测已存在，追加版本号
        version = 2
        while path.exists() and version <= self.max_versions:
            path = self.reports_dir / f"{base_filename}_v{version}.md"
            version += 1

        # v5.2 P2-13：超过版本号上限，覆盖当前 path（最后计算的版本）
        # 这是一个安全阀，正常情况下不会触发（同秒同行业运行 100 次几乎不可能）
        path.write_text(content, encoding="utf-8")
        return path
