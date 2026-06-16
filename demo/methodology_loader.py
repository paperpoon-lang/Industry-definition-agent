"""
行业定义 Agent — 方法论文档加载器 (v4 Demo MVP)

从外部 Markdown 文件（./方法论-v2.md）加载方法论全文，按 step_id 切片注入。
v4 相比 v2 的改动：
- SLICE_MAP 修正版（关键词子串匹配，按 ## 标题切分）
- 空切片降级：匹配为空或总长度 < 100 字符时回退到全量方法论
- 加入全文缓存，避免重复读取文件
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# ============================================================
# Step ID → 方法论章节关键词映射（v4 修正版）
# ============================================================
# 每个步骤需要的章节关键词，按 ## 或 ### 标题做子串匹配。
# "判断原则" 匹配 "## 三、判断原则（Heuristics）"，同时捕获其下所有子节。

SLICE_MAP: Dict[str, List[str]] = {
    "1_info_collection":       ["信息优先级", "参考框架", "Hard Rules"],
    "2_dimension_screening":   ["维度筛选原则", "Heuristics", "自检清单"],
    "3_structure_decision":    ["报告结构", "范围约束"],
    "4_content_generation":    ["Hard Rules", "推理展示", "范围约束"],
    "5_self_check":            ["自检清单"],
}

# ============================================================
# 内部状态：全文缓存
# ============================================================

_cached_full_text: Optional[str] = None
_cached_path: Optional[Path] = None


def _resolve_path(path: str = "方法论-v2.md") -> Path:
    """解析方法论文档路径。默认相对于当前文件所在目录（demo/）。"""
    p = Path(path)
    if p.is_absolute():
        return p
    # 相对于当前文件所在目录解析
    return (Path(__file__).parent / p).resolve()


def load_methodology(path: str = "方法论-v2.md") -> str:
    """加载方法论文档全文（带缓存）。

    Args:
        path: 方法论文档路径，默认相对于 demo/ 目录。

    Returns:
        方法论文档的完整 Markdown 文本。

    Raises:
        FileNotFoundError: 文件不存在且无法降级。
    """
    global _cached_full_text, _cached_path
    resolved = _resolve_path(path)

    # 缓存命中
    if _cached_full_text is not None and _cached_path == resolved:
        return _cached_full_text

    if not resolved.exists():
        raise FileNotFoundError(
            f"方法论文档不存在: {resolved}\n"
            f"请确保 方法论-v2.md 存在于 demo/ 目录下。"
        )

    _cached_full_text = resolved.read_text(encoding="utf-8")
    _cached_path = resolved
    return _cached_full_text


# ============================================================
# 章节切分与匹配
# ============================================================

# 匹配 ## 或 ### 级别标题的正则（捕获整行标题）
_HEADING_PATTERN = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


def _split_by_headings(full_text: str) -> List[Dict[str, str]]:
    """按 ## / ### 标题将全文切分为章节列表。

    Returns:
        [{"heading": "二、不可违背的约束（Hard Rules）", "level": 2, "body": "..."}, ...]
    """
    sections: List[Dict[str, str]] = []
    matches = list(_HEADING_PATTERN.finditer(full_text))

    for i, m in enumerate(matches):
        level = len(m.group(1))  # 2 或 3
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[start:end].strip()
        sections.append({"heading": heading, "level": level, "body": body})

    # 同时保留标题前的引言部分（如文档头的元信息）
    if matches:
        preamble = full_text[:matches[0].start()].strip()
        if preamble:
            sections.insert(0, {"heading": "（前言）", "level": 0, "body": preamble})

    return sections


def load_slice(step_id: str, path: str = "方法论-v2.md") -> str:
    """按 step_id 返回对应的方法论切片。

    切片逻辑：
    1. 加载全文
    2. 按 ## / ### 标题切分为章节
    3. 对每个章节的标题，检查是否包含 SLICE_MAP[step_id] 中的任一关键词（子串匹配）
    4. 拼接匹配到的所有章节
    5. 如果匹配为空或总长度 < 100 字符，打印警告并回退到全量方法论

    Args:
        step_id: 步骤标识，如 '1_info_collection'。
        path: 方法论文档路径。

    Returns:
        对应步骤的方法论切片文本。
    """
    keywords = SLICE_MAP.get(step_id)
    if keywords is None:
        print(f"[方法论加载器] 警告：未知的 step_id '{step_id}'，回退到全量方法论。")
        return load_methodology(path)

    full_text = load_methodology(path)
    sections = _split_by_headings(full_text)

    # 子串匹配：章节标题中包含任一关键词即视为匹配
    matched: List[str] = []
    for sec in sections:
        heading = sec["heading"]
        if any(kw in heading for kw in keywords):
            # 在正文前加上标题行，保持可读性
            prefix = f"{'#' * max(sec['level'], 2)} {heading}"
            matched.append(f"{prefix}\n\n{sec['body']}")

    if not matched:
        print(
            f"[方法论加载器] 警告：step_id='{step_id}' 未匹配到任何章节 "
            f"(关键词: {keywords})，回退到全量方法论。"
        )
        return full_text

    result = "\n\n---\n\n".join(matched)

    # 空切片降级：总长度不足 100 字符视为无效
    if len(result.strip()) < 100:
        print(
            f"[方法论加载器] 警告：step_id='{step_id}' 匹配内容过短 "
            f"({len(result.strip())} 字符)，回退到全量方法论。"
        )
        return full_text

    return result
