"""證交所投信買賣超(T86 三大法人買賣超日報)。

API 文件:https://www.twse.com.tw/zh/page/trading/fund/T86.html
JSON URL: https://www.twse.com.tw/rwd/zh/fund/T86

回傳欄位包含「外資、投信、自營商」之買進、賣出、買賣超股數。
本模組只擷取「投信」相關欄位。

注意:
- 數值單位為「股」(不是張)。1 張 = 1000 股。
- 週末 / 國定假日呼叫會回傳 stat != "OK",此時回傳空 DataFrame。
- 失敗時記錄 warning,不 raise。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.scrapers.base import BaseScraper, ScraperError
from src.utils.trading_calendar import is_trading_day

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

# T86 JSON fields 中,投信相關欄位的關鍵字
_BUY_KEYWORDS = ("投信買進股數",)
_SELL_KEYWORDS = ("投信賣出股數",)
_NET_KEYWORDS = ("投信買賣超股數",)
_STOCK_ID_KEYS = ("證券代號",)
_STOCK_NAME_KEYS = ("證券名稱",)


class TwseFundScraper(BaseScraper):
    """證交所 T86 三大法人買賣超 — 投信擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="twse_fund", **kwargs)

    def fetch_raw(self, date: str) -> dict[str, Any]:
        """抓取指定日期的 T86 原始 JSON。

        Args:
            date: YYYYMMDD 格式日期字串。

        Returns:
            JSON dict;包含 ``stat``、``fields``、``data`` 等欄位。
        """
        params = {
            "date": date,
            "selectType": "ALLBUT0999",
            "response": "json",
        }
        return self.get_json(T86_URL, params=params)

    def get_investment_trust_buy(self, date: str) -> pd.DataFrame:
        """取得指定日期的投信買賣超表。

        Args:
            date: YYYYMMDD。

        Returns:
            DataFrame,欄位: ``stock_id``, ``name``, ``buy``, ``sell``,
            ``net_buy``。失敗或非交易日回傳空 DataFrame(欄位齊全)。
        """
        empty = _empty_df()

        # 非交易日先擋下,不打 API
        if not is_trading_day(date):
            self.logger.info(f"{date} 非交易日,跳過 T86")
            return empty

        try:
            payload = self.fetch_raw(date)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"T86 抓取失敗 {date}: {exc}")
            return empty

        if not _is_payload_ok(payload):
            self.logger.warning(
                f"T86 回應 stat 不為 OK,date={date} stat={payload.get('stat')!r}"
            )
            return empty

        try:
            df = parse_t86_payload(payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"T86 解析失敗 {date}: {exc}")
            return empty

        return df


# ----------------------------------------------------------------------
# 純函式工具(可單獨測試)
# ----------------------------------------------------------------------
def _is_payload_ok(payload: dict[str, Any]) -> bool:
    """判斷 T86 回應是否成功(stat == "OK" 且有 data)。"""
    return (
        isinstance(payload, dict)
        and payload.get("stat") == "OK"
        and bool(payload.get("data"))
        and bool(payload.get("fields"))
    )


def _find_index(fields: list[str], keywords: tuple[str, ...]) -> int | None:
    """在 fields 清單中尋找符合任一關鍵字的欄位索引。"""
    for i, name in enumerate(fields):
        cleaned = name.strip().replace(" ", "").replace("　", "")
        for kw in keywords:
            if kw in cleaned:
                return i
    return None


def _to_int(value: Any) -> int:
    """字串/數字轉 int,自動去除千分位逗號;失敗回傳 0。"""
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


def parse_t86_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """將 T86 JSON 轉為投信買賣超 DataFrame。

    Args:
        payload: T86 完整 JSON dict。

    Returns:
        DataFrame,欄位:stock_id, name, buy, sell, net_buy。

    Raises:
        ScraperError: 找不到必要欄位。
    """
    fields: list[str] = payload["fields"]
    rows: list[list[Any]] = payload["data"]

    idx_id = _find_index(fields, _STOCK_ID_KEYS)
    idx_name = _find_index(fields, _STOCK_NAME_KEYS)
    idx_buy = _find_index(fields, _BUY_KEYWORDS)
    idx_sell = _find_index(fields, _SELL_KEYWORDS)
    idx_net = _find_index(fields, _NET_KEYWORDS)

    missing = [
        n
        for n, v in [
            ("stock_id", idx_id),
            ("name", idx_name),
            ("buy", idx_buy),
            ("sell", idx_sell),
            ("net_buy", idx_net),
        ]
        if v is None
    ]
    if missing:
        raise ScraperError(f"T86 fields 找不到欄位: {missing} / 實際: {fields}")

    records = []
    for row in rows:
        records.append(
            {
                "stock_id": str(row[idx_id]).strip(),
                "name": str(row[idx_name]).strip(),
                "buy": _to_int(row[idx_buy]),
                "sell": _to_int(row[idx_sell]),
                "net_buy": _to_int(row[idx_net]),
            }
        )

    return pd.DataFrame.from_records(records, columns=_columns())


def _columns() -> list[str]:
    return ["stock_id", "name", "buy", "sell", "net_buy"]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_columns())


# ----------------------------------------------------------------------
# 模組級捷徑函式(對外 API)
# ----------------------------------------------------------------------
def get_investment_trust_buy(date: str) -> pd.DataFrame:
    """模組級捷徑函式;內部使用一次性 ``TwseFundScraper`` 實例。"""
    with TwseFundScraper() as s:
        return s.get_investment_trust_buy(date)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from datetime import datetime

    from src.utils.logger import setup_logger
    from src.utils.trading_calendar import previous_trading_day

    setup_logger()

    # 取最近一個交易日
    today = datetime.now().strftime("%Y%m%d")
    target_date = today if is_trading_day(today) else previous_trading_day(today)

    print(f"=== 抓取投信買賣超 date={target_date} ===")
    df = get_investment_trust_buy(target_date)

    if df.empty:
        print("⚠️  回傳空 DataFrame(可能是非交易日 / API 失敗 / 還沒收盤)")
        sys.exit(0)

    print(f"共 {len(df)} 檔有投信進出")
    print("\n前 10 大投信買超:")
    print(
        df.sort_values("net_buy", ascending=False)
        .head(10)
        .to_string(index=False)
    )

    # 看一下 2330 (台積電)
    tsmc = df[df["stock_id"] == "2330"]
    if not tsmc.empty:
        print("\n--- 2330 台積電 ---")
        print(tsmc.to_string(index=False))
