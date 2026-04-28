"""證交所分點 / 全市場買賣超(BFIAUU)。

參考:https://www.twse.com.tw/zh/page/trading/exchange/BFIAUU.html

提供:
- ``get_top_buy_brokers(date)``:當日全市場買賣超彙總
  (TWSE 該頁面 ``BFIAUU_d`` JSON,fields 視日期可能略有不同)。
- ``get_stock_brokers(stock_id, date)``:個股當日分點明細(TODO,需驗證碼)。

注意:
- TWSE BFIAUU_d 實際回傳「外資 / 投信 / 自營商等」三大法人總買賣超,
  並非「分點(券商)」明細;個股分點明細需要 ``bsr.twse.com.tw`` 帶
  驗證碼。本模組將 ``get_top_buy_brokers`` 設計成「彈性解析」:
  只要回應包含 ``fields`` / ``data``,就轉成 DataFrame 給上層使用,
  欄位名 = 原始中文欄位名。上層可自行挑選欄位篩選。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.scrapers.base import BaseScraper, ScraperError
from src.utils.trading_calendar import is_trading_day

BFIAUU_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BFIAUU_d"
BSR_MENU_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"


class TwseBrokerScraper(BaseScraper):
    """TWSE 全市場買賣超彙總 / 個股分點明細擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="twse_broker", **kwargs)

    def fetch_raw(self, date: str) -> dict[str, Any]:
        """抓取指定日期的 BFIAUU_d 原始 JSON。"""
        params = {
            "date": date,
            "selectType": "ALLBUT0999",
            "response": "json",
        }
        return self.get_json(BFIAUU_URL, params=params)

    def get_top_buy_brokers(self, date: str) -> pd.DataFrame:
        """取得當日全市場買賣超彙總。

        Args:
            date: YYYYMMDD。

        Returns:
            DataFrame,欄位 = 原始中文欄位名稱。失敗或非交易日回傳空
            DataFrame。
        """
        if not is_trading_day(date):
            self.logger.info(f"{date} 非交易日,跳過 BFIAUU")
            return pd.DataFrame()

        try:
            payload = self.fetch_raw(date)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"BFIAUU 抓取失敗 {date}: {exc}")
            return pd.DataFrame()

        if not _is_payload_ok(payload):
            self.logger.warning(
                f"BFIAUU 回應 stat 不為 OK,date={date} stat={payload.get('stat')!r}"
            )
            return pd.DataFrame()

        try:
            return parse_bfiauu_payload(payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"BFIAUU 解析失敗 {date}: {exc}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    def get_stock_brokers(self, stock_id: str, date: str) -> pd.DataFrame:
        """取得個股當日前 N 大分點明細。

        TODO: ``bsr.twse.com.tw`` 此頁有驗證碼,需另行處理。本函式
        目前僅為佔位,呼叫時記錄 warning 並回傳空 DataFrame。
        若日後支援,可:
        1. 抓 ``bsMenu.aspx`` 取得 hidden form fields 與 captcha 圖。
        2. 用 OCR / 人工輸入解 captcha。
        3. POST 取得 ``bsContent.aspx`` 表格。

        Args:
            stock_id: 證券代號(如 "2330")。
            date: YYYYMMDD(目前未使用,bsr 只提供當日資料)。

        Returns:
            空 DataFrame(暫不支援)。
        """
        self.logger.warning(
            f"get_stock_brokers({stock_id}, {date}) 尚未實作(需處理驗證碼)"
        )
        _ = BSR_MENU_URL  # 預留:未來實作時使用
        return pd.DataFrame()


# ----------------------------------------------------------------------
# 純函式工具
# ----------------------------------------------------------------------
def _is_payload_ok(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("stat") == "OK"
        and bool(payload.get("data"))
    )


def _to_number(value: Any) -> Any:
    """嘗試把字串轉成數字(去千分位);無法轉換時保留原字串。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip().replace(",", "")
    if not s or s in {"--", "-"}:
        return 0
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return value


def parse_bfiauu_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """將 BFIAUU_d JSON 轉為 DataFrame。

    為了相容 TWSE 各種回應格式(fields 可能是 list 或 list[list]),
    採用較寬鬆的解析策略。
    """
    fields_raw = payload.get("fields") or payload.get("title") or []
    data: list[Any] = payload.get("data") or []

    # 取 1D fields 清單
    if (
        isinstance(fields_raw, list)
        and fields_raw
        and isinstance(fields_raw[0], list)
    ):
        fields = [str(x).strip() for x in fields_raw[0]]
    else:
        fields = [str(x).strip() for x in fields_raw]

    if not fields:
        # 沒有 fields 也沒辦法給欄位名,純列數字
        return pd.DataFrame(data)

    # 欄位數對齊
    width = len(fields)
    rows = []
    for row in data:
        if not isinstance(row, list):
            continue
        # 不足或過多時補齊 / 截斷
        cells = list(row[:width]) + [None] * max(0, width - len(row))
        rows.append([_to_number(c) for c in cells])

    return pd.DataFrame(rows, columns=fields)


# ----------------------------------------------------------------------
# 模組級捷徑函式
# ----------------------------------------------------------------------
def get_top_buy_brokers(date: str) -> pd.DataFrame:
    with TwseBrokerScraper() as s:
        return s.get_top_buy_brokers(date)


def get_stock_brokers(stock_id: str, date: str) -> pd.DataFrame:
    with TwseBrokerScraper() as s:
        return s.get_stock_brokers(stock_id, date)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from datetime import datetime

    from src.utils.logger import setup_logger
    from src.utils.trading_calendar import previous_trading_day

    setup_logger()

    today = datetime.now().strftime("%Y%m%d")
    target_date = today if is_trading_day(today) else previous_trading_day(today)

    print(f"=== 抓取 BFIAUU 全市場彙總 date={target_date} ===")
    df = get_top_buy_brokers(target_date)
    if df.empty:
        print("⚠️  回傳空 DataFrame(可能是非交易日 / API 失敗)")
    else:
        print(f"shape = {df.shape}")
        print(df.head(10).to_string(index=False))

    print("\n=== 個股分點(2330,目前未實作)===")
    df2 = get_stock_brokers("2330", target_date)
    print(f"is_empty = {df2.empty}(預期 True)")
