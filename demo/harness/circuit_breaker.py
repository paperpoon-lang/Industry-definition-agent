"""v4 Demo：带超时的重试封装（非 Circuit Breaker）。

本模块不具备熔断能力（无 CLOSED/OPEN/HALF_OPEN 状态机）。
仅防止 API 卡死时无限等待。
阶段二 B 组如需熔断，需另建 circuit_breaker_v2.py。
"""

from __future__ import annotations

import asyncio


async def call_with_timeout(fn, max_retries: int = 2, timeout_seconds: float | None = None):
    """带超时的指数退避重试。

    本函数不是 Circuit Breaker——无状态机、无半开探测、无熔断期。
    仅提供"超时即失败 + 指数退避重试"能力，防止 API 卡死时无限等待。

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
            await asyncio.sleep(2 ** attempt)
        except Exception:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)
