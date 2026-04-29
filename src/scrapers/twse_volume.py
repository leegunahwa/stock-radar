"""證交所個股日成交資訊（STOCK_DAY）。
# update by Leo 2026-04-29 & 新增成交量爬蟲

API: https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY

回傳近一個月的日成交資料，用來計算:
- today_volume   : 當日成交量（張）
- vol_5ma        : 5 日均量（張）
- vol_20ma       : 20 日均量（張）
- vol_ratio_5    : 當日量 / 5 日均量
- vol_ratio_20   : 當日量 / 20 日均量
"""

from __future__ import annotations

import re
from typing import Any

from src.scrapers.base import BaseScraper, ScraperError

STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"


class TwseVolumeScraper(BaseScraper):
    """TWSE 個股日成交量擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="twse_volume", **kwargs)

    def get_volume_stats(self, stock_id: str, date: str) -> dict[str, Any]:
        """取得個股成交量統計。

        Args:
            stock_id: 股票代號。
            date: YYYYMMDD，用於決定查詢月份。

        Returns:
            dict: today_volume, vol_5ma, vol_20ma, vol_ratio_5, vol_ratio_20
            失敗回傳全 None dict。
        """
        empty = _empty_dict()

        try:
            payload = self.get_json(
                STOCK_DAY_URL,
                params={
                    "date": date,
                    "stockNo": stock_id,
                    "response": "json",
                },
            )
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"STOCK_DAY 抓取失敗 {stock_id}: {exc}")
            return empty

        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            self.logger.warning(
                f"STOCK_DAY 回應異常 {stock_id}: stat={payload.get('stat')!r}"
            )
            return empty

        try:
            return parse_volume_data(payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"STOCK_DAY 解析失敗 {stock_id}: {exc}")
            return empty


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if not s or s in {"--", "-"}:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def parse_volume_data(payload: dict[str, Any]) -> dict[str, Any]:
    """解析 STOCK_DAY 回傳，計算成交量統計。"""
    data = payload.get("data") or []
    if not data:
        return _empty_dict()

    # STOCK_DAY fields: [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
    # 成交股數在 index 1
    volumes_shares: list[int] = []
    for row in data:
        if not isinstance(row, list) or len(row) < 2:
            continue
        vol = _to_int(row[1])
        if vol > 0:
            volumes_shares.append(vol)

    if not volumes_shares:
        return _empty_dict()

    # 轉成張（/1000）
    volumes = [v / 1000 for v in volumes_shares]

    today_vol = volumes[-1]
    vol_5ma = sum(volumes[-5:]) / min(5, len(volumes)) if volumes else 0
    vol_20ma = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0

    return {
        "today_volume": round(today_vol, 0),
        "vol_5ma": round(vol_5ma, 0),
        "vol_20ma": round(vol_20ma, 0),
        "vol_ratio_5": round(today_vol / vol_5ma, 2) if vol_5ma > 0 else None,
        "vol_ratio_20": round(today_vol / vol_20ma, 2) if vol_20ma > 0 else None,
    }


def _empty_dict() -> dict[str, Any]:
    return {
        "today_volume": None,
        "vol_5ma": None,
        "vol_20ma": None,
        "vol_ratio_5": None,
        "vol_ratio_20": None,
    }


def get_volume_stats(stock_id: str, date: str) -> dict[str, Any]:
    """模組級捷徑函式。"""
    with TwseVolumeScraper() as s:
        return s.get_volume_stats(stock_id, date)
