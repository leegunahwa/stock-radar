"""交易日判斷工具。

判斷指定日期是否為台灣股市交易日:
- 排除週六、週日
- 排除已知國定假日(可逐年於 TW_HOLIDAYS 中維護)

對於精準度要求更高的場景,建議改接 TWSE 行事曆 API。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

# =============================================================================
# 台灣股市休市日(逐年補充)
# 資料來源:證交所公告
# 格式:YYYYMMDD
# =============================================================================
TW_HOLIDAYS: set[str] = {
    # ---- 2026 (示例,實際請依證交所公告調整) ----
    "20260101",  # 元旦
    "20260216",  # 農曆除夕
    "20260217",  # 春節
    "20260218",  # 春節
    "20260219",  # 春節
    "20260220",  # 春節
    "20260227",  # 和平紀念日(補假)
    "20260403",  # 兒童節 / 清明節
    "20260619",  # 端午節
    "20261001",  # 中秋節
    "20261009",  # 國慶日(補假)
    # ---- 提醒:每年初請更新此清單 ----
}


def _to_yyyymmdd(d: str | date | datetime) -> str:
    """將輸入日期統一轉為 YYYYMMDD 字串。

    Args:
        d: 可接受 datetime / date 物件,或 YYYYMMDD / YYYY-MM-DD 字串。

    Returns:
        YYYYMMDD 格式字串。

    Raises:
        ValueError: 字串格式不符。
    """
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    if isinstance(d, str):
        s = d.replace("-", "").replace("/", "")
        if len(s) != 8 or not s.isdigit():
            raise ValueError(f"日期格式無法解析: {d!r}")
        return s
    raise TypeError(f"不支援的日期型別: {type(d)!r}")


def is_weekend(d: str | date | datetime) -> bool:
    """判斷是否為週末(週六或週日)。

    Args:
        d: 日期。

    Returns:
        週末為 True。
    """
    yyyymmdd = _to_yyyymmdd(d)
    dt = datetime.strptime(yyyymmdd, "%Y%m%d")
    return dt.weekday() >= 5


def is_holiday(d: str | date | datetime) -> bool:
    """判斷是否為已登錄的國定假日。

    Args:
        d: 日期。

    Returns:
        屬於 TW_HOLIDAYS 為 True。
    """
    return _to_yyyymmdd(d) in TW_HOLIDAYS


def is_trading_day(d: str | date | datetime) -> bool:
    """判斷指定日期是否為台灣股市交易日。

    Args:
        d: 日期。

    Returns:
        交易日為 True;週末或國定假日為 False。
    """
    return not (is_weekend(d) or is_holiday(d))


def previous_trading_day(d: str | date | datetime) -> str:
    """取得前一個交易日(YYYYMMDD)。

    Args:
        d: 起始日期。

    Returns:
        前一個交易日的 YYYYMMDD 字串。
    """
    dt = datetime.strptime(_to_yyyymmdd(d), "%Y%m%d")
    while True:
        dt -= timedelta(days=1)
        if is_trading_day(dt):
            return dt.strftime("%Y%m%d")


def recent_trading_days(d: str | date | datetime, n: int) -> list[str]:
    """取得指定日期(含)之前的 N 個交易日清單,由舊到新排序。

    Args:
        d: 結束日期(含當日)。
        n: 取幾個交易日。

    Returns:
        N 個交易日的 YYYYMMDD 字串清單,由舊到新排序。
    """
    if n <= 0:
        return []

    days: list[str] = []
    dt = datetime.strptime(_to_yyyymmdd(d), "%Y%m%d")

    if is_trading_day(dt):
        days.append(dt.strftime("%Y%m%d"))

    while len(days) < n:
        dt -= timedelta(days=1)
        if is_trading_day(dt):
            days.append(dt.strftime("%Y%m%d"))

    return list(reversed(days))


def add_holidays(holidays: Iterable[str]) -> None:
    """動態追加休市日(供測試或外部資料來源使用)。

    Args:
        holidays: 多個 YYYYMMDD 字串。
    """
    for h in holidays:
        TW_HOLIDAYS.add(_to_yyyymmdd(h))
