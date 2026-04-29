"""證交所融資融券（MI_MARGN）。
# update by Leo 2026-04-29 & 新增融資融券爬蟲

API: https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN

回傳 DataFrame 欄位:
- stock_id, name
- margin_buy         : 融資買進（張）
- margin_sell        : 融資賣出（張）
- margin_balance     : 融資餘額（張）
- margin_change      : 融資增減（張，正=融資增加，負=融資減少）
- short_buy          : 融券買進（張）
- short_sell         : 融券賣出（張）
- short_balance      : 融券餘額（張）
- short_change       : 融券增減（張，正=融券增加）
- short_margin_ratio : 券資比（%）
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.scrapers.base import BaseScraper, ScraperError
from src.utils.trading_calendar import is_trading_day

MI_MARGN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"

_STOCK_ID_KEYS = ("股票代號",)
_STOCK_NAME_KEYS = ("股票名稱",)
_MARGIN_BUY_KEYS = ("融資買進",)
_MARGIN_SELL_KEYS = ("融資賣出",)
_MARGIN_BALANCE_KEYS = ("融資今日餘額", "融資餘額")
_MARGIN_PREV_KEYS = ("融資前日餘額",)
_SHORT_BUY_KEYS = ("融券買進",)
_SHORT_SELL_KEYS = ("融券賣出",)
_SHORT_BALANCE_KEYS = ("融券今日餘額", "融券餘額")
_SHORT_PREV_KEYS = ("融券前日餘額",)
_RATIO_KEYS = ("券資比",)


class TwseMarginScraper(BaseScraper):
    """證交所融資融券擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="twse_margin", **kwargs)

    def fetch_raw(self, date: str) -> dict[str, Any]:
        params = {
            "date": date,
            "selectType": "ALLBUT0999",
            "response": "json",
        }
        return self.get_json(MI_MARGN_URL, params=params)

    def get_margin_data(self, date: str) -> pd.DataFrame:
        """取得指定日期全市場融資融券資料。"""
        empty = _empty_df()

        if not is_trading_day(date):
            self.logger.info(f"{date} 非交易日，跳過 MI_MARGN")
            return empty

        try:
            payload = self.fetch_raw(date)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"MI_MARGN 抓取失敗 {date}: {exc}")
            return empty

        if not _is_payload_ok(payload):
            self.logger.warning(
                f"MI_MARGN 回應異常, date={date} stat={payload.get('stat')!r}"
            )
            return empty

        try:
            return parse_margin_payload(payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"MI_MARGN 解析失敗 {date}: {exc}")
            return empty


def _is_payload_ok(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("stat") == "OK"
        and bool(payload.get("data"))
        and bool(payload.get("fields"))
    )


def _normalize(s: str) -> str:
    return s.strip().replace(" ", "").replace("　", "")


def _find_field_index(
    fields: list[str], keywords: tuple[str, ...],
) -> int | None:
    norm_fields = [_normalize(f) for f in fields]
    norm_kws = [_normalize(k) for k in keywords]
    for kw in norm_kws:
        for i, nf in enumerate(norm_fields):
            if nf == kw:
                return i
    for kw in norm_kws:
        for i, nf in enumerate(norm_fields):
            if kw in nf:
                return i
    return None


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


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in {"--", "-"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _cell_int(row: list[Any], idx: int | None) -> int:
    if idx is None or idx >= len(row):
        return 0
    return _to_int(row[idx])


def _cell_float(row: list[Any], idx: int | None) -> float:
    if idx is None or idx >= len(row):
        return 0.0
    return _to_float(row[idx])


def parse_margin_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """將 MI_MARGN JSON 轉為 DataFrame。"""
    # MI_MARGN 回傳可能有多個 data 區塊，融資融券明細通常在第二區塊
    fields_list = payload.get("fields") or []
    data_list = payload.get("data") or []

    # 有時候 fields/data 是巢狀 list（多區塊），取含「股票代號」的那組
    if isinstance(fields_list[0], list):
        for i, f in enumerate(fields_list):
            joined = "".join(str(x) for x in f)
            if "股票代號" in joined:
                fields = [str(x).strip() for x in f]
                data = data_list[i] if i < len(data_list) else []
                break
        else:
            raise ScraperError("MI_MARGN 找不到含股票代號的 fields 區塊")
    else:
        fields = [str(x).strip() for x in fields_list]
        data = data_list

    idx_id = _find_field_index(fields, _STOCK_ID_KEYS)
    idx_name = _find_field_index(fields, _STOCK_NAME_KEYS)
    idx_m_buy = _find_field_index(fields, _MARGIN_BUY_KEYS)
    idx_m_sell = _find_field_index(fields, _MARGIN_SELL_KEYS)
    idx_m_bal = _find_field_index(fields, _MARGIN_BALANCE_KEYS)
    idx_m_prev = _find_field_index(fields, _MARGIN_PREV_KEYS)
    idx_s_buy = _find_field_index(fields, _SHORT_BUY_KEYS)
    idx_s_sell = _find_field_index(fields, _SHORT_SELL_KEYS)
    idx_s_bal = _find_field_index(fields, _SHORT_BALANCE_KEYS)
    idx_s_prev = _find_field_index(fields, _SHORT_PREV_KEYS)
    idx_ratio = _find_field_index(fields, _RATIO_KEYS)

    if idx_id is None or idx_name is None:
        raise ScraperError(f"MI_MARGN 找不到必要欄位, fields={fields}")

    records = []
    for row in data:
        if not isinstance(row, list):
            continue
        m_bal = _cell_int(row, idx_m_bal)
        m_prev = _cell_int(row, idx_m_prev)
        s_bal = _cell_int(row, idx_s_bal)
        s_prev = _cell_int(row, idx_s_prev)

        records.append({
            "stock_id": str(row[idx_id]).strip(),
            "name": str(row[idx_name]).strip(),
            "margin_buy": _cell_int(row, idx_m_buy),
            "margin_sell": _cell_int(row, idx_m_sell),
            "margin_balance": m_bal,
            "margin_change": m_bal - m_prev if idx_m_prev is not None else 0,
            "short_buy": _cell_int(row, idx_s_buy),
            "short_sell": _cell_int(row, idx_s_sell),
            "short_balance": s_bal,
            "short_change": s_bal - s_prev if idx_s_prev is not None else 0,
            "short_margin_ratio": _cell_float(row, idx_ratio),
        })

    return pd.DataFrame.from_records(records, columns=_columns())


def _columns() -> list[str]:
    return [
        "stock_id", "name",
        "margin_buy", "margin_sell", "margin_balance", "margin_change",
        "short_buy", "short_sell", "short_balance", "short_change",
        "short_margin_ratio",
    ]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_columns())


def get_margin_data(date: str) -> pd.DataFrame:
    """模組級捷徑函式。"""
    with TwseMarginScraper() as s:
        return s.get_margin_data(date)
