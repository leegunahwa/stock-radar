"""共用重試 (retry) 工具。

封裝 tenacity 的常用重試策略,供爬蟲與 API 呼叫使用。
"""

from __future__ import annotations

from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def default_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 8.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[..., Any]:
    """回傳預設的 retry decorator。

    使用指數退避策略(1s / 2s / 4s ...),最多重試指定次數。

    Args:
        max_attempts: 最多嘗試次數(含首次)。
        min_wait: 第一次重試前的等待秒數。
        max_wait: 最大等待秒數上限。
        exceptions: 觸發重試的例外類型。

    Returns:
        tenacity 的 retry decorator。
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=min_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        reraise=True,
    )
