"""v4 Demo 打桩：简化版指数退避重试。

未来可替换为完整 CircuitBreaker（三态状态机）。
"""

import asyncio


async def call_with_retry(fn, max_retries: int = 2):
    """简化版：指数退避重试。未来可替换为完整 CircuitBreaker。

    Args:
        fn: async callable，无参数
        max_retries: 最大重试次数（不含首次调用）

    Returns:
        fn 的返回值

    Raises:
        最后一次失败时抛出原始异常
    """
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)
