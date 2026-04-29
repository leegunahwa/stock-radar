"""FinMind API 後援:當 Goodinfo 反爬蟲擋太兇時改用此模組。

註冊取得 token: https://finmindtrade.com/

API:
- 月營收: ``dataset=TaiwanStockMonthRevenue``
- 財務報表: ``dataset=TaiwanStockFinancialStatements``

免費版每日 600 次請求,夠用。

回傳格式刻意對齊 ``goodinfo`` 模組的回傳欄位,讓上層可無痛切換:
- ``get_monthly_revenue(code)`` → 同 Goodinfo 結構
- ``get_quarterly_eps(code)`` → 同 Goodinfo 結構
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from src.scrapers.base import BaseScraper, ScraperError

API_URL = "https://api.finmindtrade.com/api/v4/data"


class FinmindScraper(BaseScraper):
    """FinMind v4 資料 API。"""

    def __init__(self, token: str | None = None, **kwargs: Any) -> None:
        super().__init__(name="finmind", **kwargs)
        self.token = token or os.getenv("FINMIND_TOKEN") or ""
        if not self.token:
            self.logger.warning(
                "未設定 FINMIND_TOKEN,免費 IP 額度可能很快用完"
            )

    def _request(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """送出 API 請求並回傳 ``data`` 欄位。"""
        if self.token:
            params = {**params, "token": self.token}
        payload = self.get_json(API_URL, params=params)
        if not isinstance(payload, dict):
            raise ScraperError(f"FinMind 回應非 dict: {type(payload)}")
        if payload.get("status") != 200:
            raise ScraperError(
                f"FinMind 回應狀態異常: {payload.get('status')}, "
                f"msg={payload.get('msg')}"
            )
        return payload.get("data") or []

    # ------------------------------------------------------------------
    def get_monthly_revenue(self, code: str) -> dict[str, Any] | None:
        """取得最新一筆月營收。回傳結構與 Goodinfo 對齊。"""
        # 抓近 18 個月的資料找最新
        end = datetime.now().date()
        start = end - timedelta(days=550)
        try:
            rows = self._request(
                {
                    "dataset": "TaiwanStockMonthRevenue",
                    "data_id": code,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                }
            )
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"FinMind 月營收抓取失敗 {code}: {exc}")
            return None

        if not rows:
            return None

        # FinMind 月營收欄位:date, revenue, revenue_year (累計), revenue_month
        # 以 date 為基準排序取最新
        rows_sorted = sorted(rows, key=lambda r: r.get("date", ""))
        latest = rows_sorted[-1]
        prev_year = _find_same_month_last_year(rows_sorted, latest)
        prev_month = rows_sorted[-2] if len(rows_sorted) >= 2 else None

        revenue = latest.get("revenue")
        ytd_revenue = latest.get("revenue_year") or latest.get("revenue_month")

        yoy = _safe_growth(revenue, prev_year.get("revenue") if prev_year else None)
        mom = _safe_growth(
            revenue, prev_month.get("revenue") if prev_month else None
        )
        ytd_yoy = _safe_growth(
            ytd_revenue,
            prev_year.get("revenue_year") if prev_year else None,
        )

        return {
            "month": latest.get("date"),
            "revenue": revenue,
            "yoy": yoy,
            "mom": mom,
            "ytd_revenue": ytd_revenue,
            "ytd_yoy": ytd_yoy,
        }

    # ------------------------------------------------------------------
    def get_quarterly_eps(self, code: str) -> dict[str, Any] | None:
        """取得最新一季 EPS。"""
        end = datetime.now().date()
        start = end - timedelta(days=900)
        try:
            rows = self._request(
                {
                    "dataset": "TaiwanStockFinancialStatements",
                    "data_id": code,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                }
            )
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"FinMind EPS 抓取失敗 {code}: {exc}")
            return None

        # FinMind 財報欄位:date, type (EPS / Revenue ...), value
        eps_rows = [r for r in rows if str(r.get("type", "")).upper() == "EPS"]
        if not eps_rows:
            return None

        eps_rows.sort(key=lambda r: r.get("date", ""))
        latest = eps_rows[-1]
        date_str = str(latest.get("date", ""))
        quarter = _date_to_quarter(date_str)

        # 同期(去年)EPS 找年增
        prev_year = _find_prev_year_quarter(eps_rows, date_str)
        eps = _to_float(latest.get("value"))
        yoy = _safe_growth(eps, _to_float(prev_year.get("value")) if prev_year else None)

        # 累計 EPS:同年所有季度加總
        year = date_str[:4]
        ytd_eps_value = sum(
            _to_float(r.get("value")) or 0
            for r in eps_rows
            if str(r.get("date", "")).startswith(year)
        )
        prev_year_str = str(int(year) - 1) if year.isdigit() else ""
        ytd_prev = sum(
            _to_float(r.get("value")) or 0
            for r in eps_rows
            if str(r.get("date", "")).startswith(prev_year_str)
        )
        ytd_yoy = _safe_growth(ytd_eps_value, ytd_prev) if prev_year_str else None

        return {
            "quarter": quarter,
            "eps": eps,
            "yoy": yoy,
            "ytd_eps": ytd_eps_value,
            "ytd_yoy": ytd_yoy,
        }


# ----------------------------------------------------------------------
# 工具函式
# ----------------------------------------------------------------------
def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_growth(curr: Any, prev: Any) -> float | None:
    """計算 (curr - prev) / prev * 100;任一為 None 或 prev=0 回 None。"""
    c, p = _to_float(curr), _to_float(prev)
    if c is None or p is None or p == 0:
        return None
    return (c - p) / p * 100


def _find_same_month_last_year(
    rows: list[dict[str, Any]], latest: dict[str, Any]
) -> dict[str, Any] | None:
    """從 rows 找與 latest 同月份、年份 -1 的紀錄。"""
    date_str = str(latest.get("date", ""))
    if len(date_str) < 10:
        return None
    year = int(date_str[:4]) - 1
    month_day = date_str[4:]
    target_prefix = f"{year}{month_day[:3]}"  # YYYY-MM
    for r in rows:
        if str(r.get("date", "")).startswith(target_prefix):
            return r
    return None


def _find_prev_year_quarter(
    rows: list[dict[str, Any]], date_str: str
) -> dict[str, Any] | None:
    if len(date_str) < 10:
        return None
    year = int(date_str[:4]) - 1
    target = f"{year}{date_str[4:]}"
    for r in rows:
        if str(r.get("date", "")) == target:
            return r
    return None


def _date_to_quarter(date_str: str) -> str:
    """將 ``2024-09-30`` 轉為 ``2024Q3``。"""
    if len(date_str) < 7:
        return date_str
    year = date_str[:4]
    month = int(date_str[5:7])
    q = (month - 1) // 3 + 1
    return f"{year}Q{q}"


# ----------------------------------------------------------------------
# 模組級捷徑函式
# ----------------------------------------------------------------------
def get_monthly_revenue(code: str) -> dict[str, Any] | None:
    with FinmindScraper() as s:
        return s.get_monthly_revenue(code)


def get_quarterly_eps(code: str) -> dict[str, Any] | None:
    with FinmindScraper() as s:
        return s.get_quarterly_eps(code)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from src.utils.logger import setup_logger

    setup_logger()
    code = "2330"

    print(f"=== {code} 月營收 (FinMind) ===")
    print(get_monthly_revenue(code))

    print(f"\n=== {code} 季度 EPS (FinMind) ===")
    print(get_quarterly_eps(code))
