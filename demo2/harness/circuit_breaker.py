"""v5.2 升级：call_with_timeout — 带 429 限流区分处理的超时重试封装。

v4 的 call_with_timeout 不区分异常类型，429 限流和其他异常用相同的指数退避。
v5.2 改进（评议 P1-11）：区分 429 限流和其他异常，429 读取 Retry-After header。

本模块不具备熔断能力（无 CLOSED/OPEN/HALF_OPEN 状态机）。
仅防止 API 卡死时无限等待。
阶段二 B 组如需熔断，需另建 circuit_breaker_v2.py。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional


async def call_with_timeout(
    fn: Callable[[], Any],
    max_retries: int = 2,
    timeout_seconds: Optional[float] = None,
) -> Any:
    """带超时的指数退避重试，区分 429 限流。

    本函数不是 Circuit Breaker——无状态机、无半开探测、无熔断期。
    仅提供"超时即失败 + 指数退避重试"能力，防止 API 卡死时无限等待。

    v5.2 改进（评议 P1-11）：
    - 区分 429 限流和其他异常
    - 429 限流：读取 Retry-After header，按服务端要求等待（最多 60s）
    - 其他异常：指数退避（1s, 2s, 4s...）
    - 超时：指数退避

    Args:
        fn: async callable，无参数
        max_retries: 最大重试次数（不含首次调用）
        timeout_seconds: 单次调用超时上限（秒）。None 表示不设超时（向后兼容）。

    Returns:
        fn 的返回值

    Raises:
        asyncio.TimeoutError: 最后一次尝试仍超时
        Exception: 最后一次尝试仍抛出原始异常
    """
    for attempt in range(max_retries + 1):
        try:
            if timeout_seconds is not None:
                return await asyncio.wait_for(fn(), timeout=timeout_seconds)
            return await fn()
        except asyncio.TimeoutError:
            if attempt == max_retries:
                raise
            # 超时用指数退避
            backoff = 2 ** attempt
            await asyncio.sleep(backoff)
        except Exception as e:
            if attempt == max_retries:
                raise
            # v5.2：区分 429 限流
            retry_after = _extract_retry_after(e)
            if retry_after is not None:
                # 429 限流：按服务端要求等待（最多 60s）
                wait_time = min(retry_after, 60.0)
                await asyncio.sleep(wait_time)
            else:
                # 其他异常：指数退避
                backoff = 2 ** attempt
                await asyncio.sleep(backoff)


def _extract_retry_after(exc: Exception) -> Optional[float]:
    """从异常中提取 Retry-After 值（秒）。

    支持 OpenAI SDK 的 APIStatusError（含 429 状态码和 response headers）。
    返回 None 表示不是 429 限流或无法解析 Retry-After。

    Args:
        exc: 捕获的异常

    Returns:
        Retry-After 值（秒），或 None
    """
    # OpenAI SDK 的 APIStatusError 有 status_code 和 response 属性
    status_code = getattr(exc, "status_code", None)
    if status_code != 429:
        return None

    # 尝试从 response headers 读取 Retry-After
    response = getattr(exc, "response", None)
    if response is None:
        # 无 response 对象，用默认等待
        return 5.0

    headers = getattr(response, "headers", None)
    if headers is None:
        return 5.0

    retry_after_raw = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after_raw is None:
        return 5.0

    try:
        # Retry-After 可以是秒数或 HTTP 日期
        return float(retry_after_raw)
    except (ValueError, TypeError):
        # 如果是 HTTP 日期格式，解析失败则用默认值
        return 5.0
