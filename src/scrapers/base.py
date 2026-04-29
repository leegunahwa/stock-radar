"""爬蟲共用基底類別。

提供:
- 共用 ``requests.Session``(連線池重用)
- User-Agent 池(優先用 ``fake-useragent``,失敗則用內建清單)
- ``tenacity`` 自動重試(預設 3 次,指數退避 1s / 2s / 4s)
- 請求節流:每次請求後 sleep(2 + random()*2) 秒
- 統一 logging 與例外處理
- ``get`` / ``get_json`` / ``get_html`` 三種便捷方法

子類別只需呼叫 ``self.get(url)`` 等方法,即可享有上述能力。
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests
from lxml import html as lxml_html
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger

# 內建 UA 池(fake-useragent 失效時的後援)
_FALLBACK_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class ScraperError(Exception):
    """爬蟲操作失敗(網路 / 解析 / HTTP 錯誤)。"""


class BaseScraper:
    """所有爬蟲的共用基底。

    Attributes:
        name: 爬蟲名稱(供 logging)。
        session: 共用 ``requests.Session``。
        timeout: 預設請求逾時秒數。
        throttle_min / throttle_max: 每次請求後隨機 sleep 區間。
    """

    DEFAULT_TIMEOUT: float = 15.0
    THROTTLE_MIN: float = 2.0
    THROTTLE_MAX: float = 4.0

    def __init__(
        self,
        name: str | None = None,
        timeout: float | None = None,
        throttle: tuple[float, float] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name or self.__class__.__name__
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.throttle_min, self.throttle_max = throttle or (
            self.THROTTLE_MIN,
            self.THROTTLE_MAX,
        )
        self.logger = get_logger(f"scraper.{self.name}")
        self.session = requests.Session()
        self.session.headers.update(self._default_headers())
        if extra_headers:
            self.session.headers.update(extra_headers)
        self._ua_pool = self._init_ua_pool()

    # ------------------------------------------------------------------
    # User-Agent 處理
    # ------------------------------------------------------------------
    def _init_ua_pool(self) -> list[str]:
        """初始化 UA 池;優先使用 fake-useragent,失敗時用內建清單。"""
        try:
            from fake_useragent import UserAgent

            ua = UserAgent()
            # 取 5 個常見瀏覽器 UA
            pool = []
            for _ in range(5):
                try:
                    pool.append(ua.random)
                except Exception:  # noqa: BLE001
                    break
            if pool:
                return pool
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"fake-useragent 初始化失敗,使用內建 UA 池: {exc}")
        return list(_FALLBACK_USER_AGENTS)

    def random_user_agent(self) -> str:
        """從 UA 池隨機回傳一個 User-Agent。"""
        return random.choice(self._ua_pool)

    # ------------------------------------------------------------------
    # 預設 HTTP headers
    # ------------------------------------------------------------------
    def _default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(_FALLBACK_USER_AGENTS),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    # ------------------------------------------------------------------
    # 主要請求方法
    # ------------------------------------------------------------------
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """發出 GET 請求(帶自動重試與節流)。

        Args:
            url: 目標 URL。
            **kwargs: 直接傳給 ``requests.Session.get``,可覆蓋
                ``headers`` / ``params`` / ``timeout`` 等。

        Returns:
            ``requests.Response`` 物件。

        Raises:
            ScraperError: 重試次數用盡仍失敗時拋出。
        """
        return self._get_with_retry(url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET 並解析為 JSON。失敗時 raise ScraperError。"""
        response = self.get(url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ScraperError(
                f"{self.name} JSON 解析失敗: {url} ({exc})"
            ) from exc

    def get_html(self, url: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        """GET 並用 lxml 解析為 ``HtmlElement``。"""
        response = self.get(url, **kwargs)
        try:
            return lxml_html.fromstring(response.content)
        except Exception as exc:  # noqa: BLE001
            raise ScraperError(
                f"{self.name} HTML 解析失敗: {url} ({exc})"
            ) from exc

    # ------------------------------------------------------------------
    # 內部:retry + throttle 包裝
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (requests.RequestException, requests.HTTPError)
        ),
        reraise=True,
    )
    def _get_with_retry(self, url: str, **kwargs: Any) -> requests.Response:
        # 每次請求隨機 UA,降低被識別風險
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("User-Agent", self.random_user_agent())
        timeout = kwargs.pop("timeout", self.timeout)

        self.logger.debug(f"GET {url}")
        try:
            resp = self.session.get(
                url, headers=headers, timeout=timeout, **kwargs
            )
            resp.raise_for_status()
        finally:
            # 不論成功失敗都節流,避免重試時打太快
            self._sleep()

        return resp

    def _sleep(self) -> None:
        """隨機 sleep,降低請求頻率。"""
        delay = random.uniform(self.throttle_min, self.throttle_max)
        time.sleep(delay)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    def close(self) -> None:
        """關閉底層 Session。"""
        self.session.close()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()
