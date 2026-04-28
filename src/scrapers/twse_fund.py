"""證交所三大法人買賣超(T86)。

API 文件:https://www.twse.com.tw/zh/page/trading/fund/T86.html
JSON URL: https://www.twse.com.tw/rwd/zh/fund/T86

回傳欄位包含「外資、投信、自營商」之買進、賣出、買賣超股數,
以及「三大法人合計」(主力)。

DataFrame 欄位:
- ``stock_id``, ``name``
- ``buy``, ``sell``, ``net_buy``       — 投信(保留原命名,向下相容)
- ``foreign_net_buy``                   — 外資 + 外資自營商 合計
- ``dealer_net_buy``                    — 自營商 合計(自行買賣 + 避險)
- ``main_force_net_buy``                — 三大法人合計(主力)
  優先用 T86 直接提供的「三大法人買賣超股數」;若該欄位缺,則
  fallback 為 ``foreign_net_buy + net_buy + dealer_net_buy``。

注意:
- 數值單位為「股」;1 張 = 1000 股。
- 週末 / 國定假日呼叫會回傳 stat != "OK",此時回傳空 DataFrame。
- 失敗時記錄 warning,不 raise。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.scrapers.base import BaseScraper, ScraperError
from src.utils.trading_calendar import is_trading_day

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

# 投信
_BUY_KEYWORDS = ("投信買進股數",)
_SELL_KEYWORDS = ("投信賣出股數",)
_INV_NET_KEYWORDS = ("投信買賣超股數",)
# 外資(含外資自營商)
_FOREIGN_NET_KEYWORDS = (
    "外陸資買賣超股數(不含外資自營商)",
    "外陸資買賣超股數",
    "外資買賣超股數",
)
_FOREIGN_DEALER_NET_KEYWORDS = ("外資自營商買賣超股數",)
# 自營商
_DEALER_TOTAL_KEYWORDS = ("自營商買賣超股數",)
_DEALER_SELF_KEYWORDS = ("自營商買賣超股數(自行買賣)",)
_DEALER_HEDGE_KEYWORDS = ("自營商買賣超股數(避險)",)
# 三大法人合計
_MAIN_FORCE_KEYWORDS = ("三大法人買賣超股數",)
# 識別欄
_STOCK_ID_KEYS = ("證券代號",)
_STOCK_NAME_KEYS = ("證券名稱",)


class TwseFundScraper(BaseScraper):
    """證交所 T86 三大法人買賣超擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="twse_fund", **kwargs)

    def fetch_raw(self, date: str) -> dict[str, Any]:
        """抓取指定日期的 T86 原始 JSON。"""
        params = {
            "date": date,
            "selectType": "ALLBUT0999",
            "response": "json",
        }
        return self.get_json(T86_URL, params=params)

    def get_investment_trust_buy(self, date: str) -> pd.DataFrame:
        """取得指定日期的三大法人買賣超表(欄位含投信 + 主力)。

        函式名稱保留 ``investment_trust_buy`` 是為了向下相容;
        實際回傳欄位包含投信、外資、自營商與三大法人合計。

        Args:
            date: YYYYMMDD。

        Returns:
            DataFrame(欄位見模組 docstring)。失敗或非交易日回傳
            欄位齊全的空 DataFrame。
        """
        empty = _empty_df()

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


def _normalize(s: str) -> str:
    return s.strip().replace(" ", "").replace("　", "")


def _find_field_index(
    fields: list[str],
    keywords: tuple[str, ...],
    strict: bool = False,
) -> int | None:
    """在 fields 中找欄位。

    Args:
        fields: TWSE 回傳的 fields 清單。
        keywords: 候選欄位名(會嘗試每一個)。
        strict: 是否只接受 normalize 後的「精確相等」。
            當欄位名彼此互為子字串時(如「自營商買賣超股數」是
            「外資自營商買賣超股數」的子字串),需設 strict=True。

    Returns:
        欄位索引;找不到回 None。
    """
    norm_fields = [_normalize(f) for f in fields]
    norm_kws = [_normalize(k) for k in keywords]

    # 1. 精確匹配
    for kw in norm_kws:
        for i, nf in enumerate(norm_fields):
            if nf == kw:
                return i

    if strict:
        return None

    # 2. 子字串
    for kw in norm_kws:
        for i, nf in enumerate(norm_fields):
            if kw in nf:
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


def _cell(row: list[Any], idx: int | None) -> int:
    """安全擷取 row[idx] 並轉 int;idx 為 None 或越界回 0。"""
    if idx is None or idx >= len(row):
        return 0
    return _to_int(row[idx])


def parse_t86_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """將 T86 JSON 轉為 DataFrame(欄位見模組 docstring)。

    Raises:
        ScraperError: 找不到必要欄位(投信買賣超 / 證券代號 / 證券名稱)。
    """
    fields: list[str] = payload["fields"]
    rows: list[list[Any]] = payload["data"]

    idx_id = _find_field_index(fields, _STOCK_ID_KEYS)
    idx_name = _find_field_index(fields, _STOCK_NAME_KEYS)
    idx_buy = _find_field_index(fields, _BUY_KEYWORDS)
    idx_sell = _find_field_index(fields, _SELL_KEYWORDS)
    idx_inv_net = _find_field_index(fields, _INV_NET_KEYWORDS)

    # 必要欄位
    missing = [
        n
        for n, v in [
            ("stock_id", idx_id),
            ("name", idx_name),
            ("buy", idx_buy),
            ("sell", idx_sell),
            ("net_buy", idx_inv_net),
        ]
        if v is None
    ]
    if missing:
        raise ScraperError(f"T86 fields 找不到必要欄位: {missing} / 實際: {fields}")

    # 選擇性欄位:外資 / 自營商 / 主力
    idx_foreign = _find_field_index(fields, _FOREIGN_NET_KEYWORDS)
    idx_foreign_dealer = _find_field_index(fields, _FOREIGN_DEALER_NET_KEYWORDS)
    # 自營商合計欄位名「自營商買賣超股數」是「外資自營商買賣超股數」與
    # 「自營商買賣超股數(自行買賣)」的子字串,故只接受精確匹配。
    idx_dealer_total = _find_field_index(
        fields, _DEALER_TOTAL_KEYWORDS, strict=True
    )
    idx_dealer_self = _find_field_index(fields, _DEALER_SELF_KEYWORDS)
    idx_dealer_hedge = _find_field_index(fields, _DEALER_HEDGE_KEYWORDS)
    idx_main_force = _find_field_index(fields, _MAIN_FORCE_KEYWORDS)

    records = []
    for row in rows:
        inv_net = _cell(row, idx_inv_net)

        # 外資合計 = 「外陸資(不含外資自營商)」 + 「外資自營商」
        foreign_main = _cell(row, idx_foreign)
        foreign_dealer = _cell(row, idx_foreign_dealer)
        foreign_net = foreign_main + foreign_dealer

        # 自營商合計:優先用「自營商買賣超股數(合計欄,不含括號)」,
        # 否則用 自行買賣 + 避險
        if idx_dealer_total is not None:
            dealer_net = _cell(row, idx_dealer_total)
        else:
            dealer_net = _cell(row, idx_dealer_self) + _cell(
                row, idx_dealer_hedge
            )

        # 主力(三大法人):優先用 T86 提供的合計欄,否則 fallback 加總
        if idx_main_force is not None:
            main_force_net = _cell(row, idx_main_force)
        else:
            main_force_net = foreign_net + inv_net + dealer_net

        records.append(
            {
                "stock_id": str(row[idx_id]).strip(),
                "name": str(row[idx_name]).strip(),
                "buy": _cell(row, idx_buy),
                "sell": _cell(row, idx_sell),
                "net_buy": inv_net,  # 投信淨買超
                "foreign_net_buy": foreign_net,
                "dealer_net_buy": dealer_net,
                "main_force_net_buy": main_force_net,
            }
        )

    return pd.DataFrame.from_records(records, columns=_columns())


def _columns() -> list[str]:
    return [
        "stock_id",
        "name",
        "buy",
        "sell",
        "net_buy",
        "foreign_net_buy",
        "dealer_net_buy",
        "main_force_net_buy",
    ]


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

    today = datetime.now().strftime("%Y%m%d")
    target_date = today if is_trading_day(today) else previous_trading_day(today)

    print(f"=== 抓取三大法人買賣超 date={target_date} ===")
    df = get_investment_trust_buy(target_date)

    if df.empty:
        print("⚠️  回傳空 DataFrame(非交易日 / API 失敗 / 尚未收盤)")
        sys.exit(0)

    print(f"共 {len(df)} 檔有法人進出\n")

    print("前 10 大「投信」買超:")
    print(
        df.sort_values("net_buy", ascending=False)
        .head(10)[["stock_id", "name", "net_buy", "main_force_net_buy"]]
        .to_string(index=False)
    )

    print("\n前 10 大「主力(三大法人)」買超:")
    print(
        df.sort_values("main_force_net_buy", ascending=False)
        .head(10)[
            [
                "stock_id",
                "name",
                "foreign_net_buy",
                "net_buy",
                "dealer_net_buy",
                "main_force_net_buy",
            ]
        ]
        .to_string(index=False)
    )

    tsmc = df[df["stock_id"] == "2330"]
    if not tsmc.empty:
        print("\n--- 2330 台積電 ---")
        print(tsmc.to_string(index=False))
