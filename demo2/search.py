"""
Search SubAgent — 并行搜索 + 结果截断压缩 (v5.2)

v4 基础：
- 3 个 query 并行发出，单条结果超过 max_chars 截断。
- 支持 Tavily Async API 和 Mock 模式降级。

v5.2 新增（P0-1 修正项）：
- `search_single_query(query, tavily_api_key, max_results)` 函数
- 供 Step 1 补搜循环调用，传入具体 query 而非行业名
- 返回 list[dict] 而非包装 dict，与 search_with_fallback 接口解耦
- 不修改现有 search_with_fallback 接口（v4 兼容）
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


# ============================================================
# 搜索查询模板（3 个维度）
# ============================================================

SEARCH_QUERIES = [
    "{industry} 行业定义 官方定义 标准",
    "{industry} 政策 监管 产业链",
    "{industry} 边界 与相邻行业区分",
]


# ============================================================
# 辅助：截断单条结果
# ============================================================

def _truncate(text: str, max_chars: int) -> str:
    """截断文本到指定长度，尽量在句末截断。"""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # 尝试在最后一个句号处截断
    for sep in ("。", ". ", "\n"):
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.5:
            return truncated[:idx + 1] + "\n（内容已截断）"
    return truncated + "（内容已截断）"


# ============================================================
# 并行搜索 + 结果截断
# ============================================================

async def search_parallel(
    industry: str,
    tavily_api_key: str,
    max_chars_per_result: int = 1500,
) -> dict[str, Any]:
    """并行搜索 3 个 query，单条结果超过 max_chars_per_result 截断。

    Args:
        industry: 行业名称。
        tavily_api_key: Tavily API 密钥。
        max_chars_per_result: 单条搜索结果最大字符数（默认 1500）。

    Returns:
        {
            "results": {query: [{title, url, content}, ...]},
            "data_gaps": [...],
            "error_count": int,
        }
    """
    queries = [q.format(industry=industry) for q in SEARCH_QUERIES]

    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=tavily_api_key)

        async def _search_one(query: str) -> tuple[str, list[dict]]:
            try:
                resp = await client.search(query, search_depth="advanced", max_results=5)
                items = []
                for r in resp.get("results", []):
                    items.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": _truncate(r.get("content", ""), max_chars_per_result),
                    })
                return query, items
            except Exception as e:
                return query, [{"title": f"搜索失败", "url": "", "content": str(e)}]

        tasks = [_search_one(q) for q in queries]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, list[dict]] = {}
        errors = 0
        for item in gathered:
            if isinstance(item, Exception):
                errors += 1
                continue
            query, items = item
            results[query] = items
            # 判断是否是错误结果
            if items and "搜索失败" in items[0].get("title", ""):
                errors += 1

        data_gaps: list[str] = []
        if errors == len(queries):
            data_gaps.append("所有搜索查询均失败")
        elif errors > 0:
            data_gaps.append(f"{errors} 个搜索查询失败")

        return {"results": results, "data_gaps": data_gaps, "error_count": errors}

    except ImportError:
        # tavily 未安装，返回空结果
        return {
            "results": {q: [{"title": "搜索不可用", "url": "", "content": "tavily-python 未安装"}] for q in queries},
            "data_gaps": ["tavily-python 未安装，搜索不可用"],
            "error_count": len(queries),
        }


# ============================================================
# 降级搜索：单 query 重试
# ============================================================

async def search_with_fallback(industry: str, tavily_api_key: str) -> dict[str, Any]:
    """搜索全失败降级：如果并行搜索全部失败，用单个 query 重试。

    Args:
        industry: 行业名称。
        tavily_api_key: Tavily API 密钥。

    Returns:
        与 search_parallel 相同结构的字典。
    """
    result = await search_parallel(industry, tavily_api_key)

    # 如果全部成功或全部失败且没有 data_gaps 指示全失败，直接返回
    if result["error_count"] < len(SEARCH_QUERIES):
        return result

    # 全失败降级：单 query 重试
    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=tavily_api_key)
        resp = await client.search(f"{industry} 行业", search_depth="basic", max_results=3)
        items = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in resp.get("results", [])
        ]
        if items:
            result["results"][f"{industry} 行业（降级）"] = items
            result["data_gaps"].append("已使用降级搜索策略（单 query）")
            result["error_count"] = len(SEARCH_QUERIES) - 1
    except Exception:
        result["data_gaps"].append("降级搜索也失败，所有搜索渠道不可用")

    return result


# ============================================================
# v5.2 新增：单 query 搜索（供 Step 1 补搜循环调用）
# ============================================================

async def search_single_query(
    query: str,
    tavily_api_key: str,
    max_results: int = 5,
    max_chars_per_result: int = 1500,
) -> list[dict]:
    """单 query 搜索，供 Step 1 补搜循环调用。

    与 search_with_fallback 不同：
    - 传入具体 query 而非行业名
    - 返回 list[dict] 而非包装 dict
    - 失败时返回包含错误信息的 list（不抛异常），由调用方决定如何处理

    v5.2 新增（P0-1 修正项）。

    Args:
        query: 完整的搜索查询字符串。
        tavily_api_key: Tavily API 密钥。
        max_results: 单次搜索返回的最大结果数（默认 5）。
        max_chars_per_result: 单条结果最大字符数（默认 1500，与 search_parallel 一致）。

    Returns:
        list[dict]，每个元素为 {"title", "url", "content"}。
        失败时返回 [{"title": "搜索失败", "url": "", "content": str(e)}]。
    """
    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=tavily_api_key)
        resp = await client.search(query, search_depth="advanced", max_results=max_results)
        items: list[dict] = []
        for r in resp.get("results", []):
            items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": _truncate(r.get("content", ""), max_chars_per_result),
            })
        return items
    except ImportError:
        return [{"title": "搜索失败", "url": "", "content": "tavily-python 未安装"}]
    except Exception as e:
        return [{"title": "搜索失败", "url": "", "content": str(e)}]


# ============================================================
# Mock 模式
# ============================================================

def mock_search(industry: str) -> dict[str, Any]:
    """Mock 搜索（不调用 Tavily API）。

    Args:
        industry: 行业名称。

    Returns:
        与 search_parallel 相同结构的字典，包含预设数据。
    """
    queries = [q.format(industry=industry) for q in SEARCH_QUERIES]
    results: dict[str, list[dict]] = {}
    for query in queries:
        results[query] = [
            {
                "title": f"{industry}行业概述（Mock 数据）",
                "url": "https://example.com/mock",
                "content": (
                    f"{industry}是指……（此处为 mock 搜索结果，"
                    "真实环境下将通过 Tavily Search API 获取最新信息）。"
                    f"该行业涉及的主要活动包括……。政策环境方面……。"
                    f"与相邻行业的主要区别在于……。"
                ),
            }
        ]

    return {"results": results, "data_gaps": ["当前为 Mock 模式，搜索结果非真实数据"], "error_count": 0}
