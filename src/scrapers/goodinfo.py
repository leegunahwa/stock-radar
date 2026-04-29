"""Goodinfo 月營收 / 季度 EPS 爬蟲。

頁面:
- 月營收: https://goodinfo.tw/tw/ShowSaleMonChart.asp?STOCK_ID={code}
- 經營績效: https://goodinfo.tw/tw/StockBzPerformance.asp?STOCK_ID={code}

反爬蟲注意事項:
- User-Agent 必須是真實瀏覽器
- Referer 必填
- Accept-Language: zh-TW,zh;q=0.9
- Cookie 帶隨機 ``CLIENT_ID``
- 每次請求間隔 5-8 秒(本模組統一使用 BaseScraper 的節流,
  並於 init 時放寬到 5-8 秒)
- 用 lxml.html 解析

失敗策略:
- 抓取失敗 / 解析失敗 → 回傳 None,log warning,不 raise。
- 連續多次失敗時建議切換 ``finmind`` 後援(SPEC.md 提及)。
"""

from __future__ import annotations

import random
import re
import string
from typing import Any

from lxml import html as lxml_html

from src.scrapers.base import BaseScraper, ScraperError

REVENUE_URL = "https://goodinfo.tw/tw/ShowSaleMonChart.asp"
EPS_URL = "https://goodinfo.tw/tw/StockBzPerformance.asp"
REFERER = "https://goodinfo.tw/tw/index.asp"


def _random_client_id() -> str:
    """模擬 Goodinfo 的 CLIENT_ID cookie(隨機英數字)。"""
    return "".join(random.choices(string.ascii_letters + string.digits, k=24))


class GoodinfoScraper(BaseScraper):
    """Goodinfo 反爬蟲擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        # Goodinfo 對請求頻率較敏感,放寬節流到 5-8 秒
        kwargs.setdefault("throttle", (5.0, 8.0))
        kwargs.setdefault(
            "extra_headers",
            {
                "Referer": REFERER,
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
        super().__init__(name="goodinfo", **kwargs)
        # 隨機 CLIENT_ID cookie
        self.session.cookies.set(
            "CLIENT%5FID", _random_client_id(), domain="goodinfo.tw"
        )

    # ------------------------------------------------------------------
    # 月營收
    # ------------------------------------------------------------------
    def get_monthly_revenue(self, code: str) -> dict[str, Any] | None:
        """擷取最新月份的月營收資料。

        Args:
            code: 股票代號(如 "2330")。

        Returns:
            dict,key 為:
            ``month`` (str, 如 "2026/03")
            ``revenue`` (float, 單位百萬元)
            ``yoy`` (float, 年增 %)
            ``mom`` (float, 月增 %)
            ``ytd_revenue`` (float)
            ``ytd_yoy`` (float)
            失敗時回傳 ``None``。
        """
        try:
            resp = self.get(REVENUE_URL, params={"STOCK_ID": code})
            tree = lxml_html.fromstring(resp.content)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"Goodinfo 月營收抓取失敗 {code}: {exc}")
            return None

        try:
            return parse_monthly_revenue_html(tree)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"Goodinfo 月營收解析失敗 {code}: {exc}")
            return None

    # ------------------------------------------------------------------
    # 季度 EPS
    # ------------------------------------------------------------------
    def get_quarterly_eps(self, code: str) -> dict[str, Any] | None:
        """擷取最新季度的 EPS 資料。

        Args:
            code: 股票代號。

        Returns:
            dict,key 為:
            ``quarter`` (str, 如 "2025Q4")
            ``eps`` (float)
            ``yoy`` (float, 年增 %)
            ``ytd_eps`` (float)
            ``ytd_yoy`` (float)
            失敗時回傳 ``None``。
        """
        try:
            resp = self.get(
                EPS_URL,
                params={"STOCK_ID": code, "RPT_CAT": "M_QUAR"},
            )
            tree = lxml_html.fromstring(resp.content)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"Goodinfo EPS 抓取失敗 {code}: {exc}")
            return None

        try:
            return parse_quarterly_eps_html(tree)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"Goodinfo EPS 解析失敗 {code}: {exc}")
            return None


# ----------------------------------------------------------------------
# 解析工具(純函式,可單測)
# ----------------------------------------------------------------------
def _to_float(value: Any) -> float | None:
    """將「1,234.56%」「-12.34」「N/A」等字串轉 float;失敗回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in {"--", "-", "N/A", "n/a"}:
        return None
    # 全形負號
    s = s.replace("−", "-").replace("－", "-")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None


def _table_to_rows(table) -> list[list[str]]:  # type: ignore[no-untyped-def]
    """把 <table> 轉成 2D list(已 strip)。"""
    rows: list[list[str]] = []
    for tr in table.iterfind(".//tr"):
        cells = [
            (td.text_content() or "").strip() for td in tr.findall("./td")
        ]
        if cells:
            rows.append(cells)
    return rows


def _find_header_index(headers: list[str], keywords: list[str]) -> int | None:
    """在 headers 中找包含任一 keyword 的欄位 index。"""
    for i, h in enumerate(headers):
        cleaned = h.replace(" ", "").replace("　", "")
        for kw in keywords:
            if kw in cleaned:
                return i
    return None


def parse_monthly_revenue_html(tree) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """解析月營收頁的最新一筆資料。

    Goodinfo 頁面有多個 ``table.solid_1_padding_4_4_tbl`` 表格,
    其中一張是月營收明細(欄位含「月別/單月營收/年增/月增/累計營收/累計年增」)。
    本函式尋找此表並取第一列(最新月份)。
    """
    tables = tree.xpath("//table[contains(@class, 'solid_1_padding_4_4_tbl')]")

    for table in tables:
        rows = _table_to_rows(table)
        if len(rows) < 2:
            continue
        headers = rows[0]
        joined = "".join(headers)
        # 月營收表特徵:含「月別」與「單月營收」或「合併營收」
        if ("月別" in joined or "月份" in joined) and (
            "營收" in joined or "合併" in joined
        ):
            idx_month = _find_header_index(headers, ["月別", "月份"])
            idx_rev = _find_header_index(headers, ["單月營收", "合併營收", "營收"])
            idx_yoy = _find_header_index(headers, ["年增", "YoY"])
            idx_mom = _find_header_index(headers, ["月增", "MoM"])
            idx_ytd = _find_header_index(headers, ["累計營收", "累計"])
            idx_ytd_yoy = _find_header_index(
                headers, ["累計年增", "累計 年增", "累計YoY"]
            )

            if idx_month is None or idx_rev is None:
                continue

            data_row = rows[1]
            return {
                "month": data_row[idx_month] if idx_month < len(data_row) else None,
                "revenue": _to_float(data_row[idx_rev])
                if idx_rev is not None and idx_rev < len(data_row)
                else None,
                "yoy": _to_float(data_row[idx_yoy])
                if idx_yoy is not None and idx_yoy < len(data_row)
                else None,
                "mom": _to_float(data_row[idx_mom])
                if idx_mom is not None and idx_mom < len(data_row)
                else None,
                "ytd_revenue": _to_float(data_row[idx_ytd])
                if idx_ytd is not None and idx_ytd < len(data_row)
                else None,
                "ytd_yoy": _to_float(data_row[idx_ytd_yoy])
                if idx_ytd_yoy is not None and idx_ytd_yoy < len(data_row)
                else None,
            }

    raise ScraperError("找不到月營收表(table.solid_1_padding_4_4_tbl)")


def parse_quarterly_eps_html(tree) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """解析經營績效頁的最新一季 EPS 資料。

    類似月營收頁,有多個表格;EPS 表通常含「年度/季別」與「EPS」欄。
    """
    tables = tree.xpath("//table[contains(@class, 'solid_1_padding_4_4_tbl')]")

    for table in tables:
        rows = _table_to_rows(table)
        if len(rows) < 2:
            continue
        headers = rows[0]
        joined = "".join(headers)
        if "EPS" in joined.upper() and ("季" in joined or "年度" in joined):
            idx_q = _find_header_index(headers, ["季", "年度", "期別"])
            idx_eps = _find_header_index(headers, ["EPS", "稅後 EPS", "每股盈餘"])
            idx_yoy = _find_header_index(headers, ["年增", "YoY"])
            idx_ytd_eps = _find_header_index(
                headers, ["累計EPS", "累計 EPS", "全年 EPS"]
            )
            idx_ytd_yoy = _find_header_index(
                headers, ["累計年增", "累計 年增"]
            )

            if idx_q is None or idx_eps is None:
                continue

            data_row = rows[1]
            return {
                "quarter": data_row[idx_q] if idx_q < len(data_row) else None,
                "eps": _to_float(data_row[idx_eps])
                if idx_eps < len(data_row)
                else None,
                "yoy": _to_float(data_row[idx_yoy])
                if idx_yoy is not None and idx_yoy < len(data_row)
                else None,
                "ytd_eps": _to_float(data_row[idx_ytd_eps])
                if idx_ytd_eps is not None and idx_ytd_eps < len(data_row)
                else None,
                "ytd_yoy": _to_float(data_row[idx_ytd_yoy])
                if idx_ytd_yoy is not None and idx_ytd_yoy < len(data_row)
                else None,
            }

    raise ScraperError("找不到 EPS 表(table.solid_1_padding_4_4_tbl)")


# ----------------------------------------------------------------------
# 模組級捷徑函式
# ----------------------------------------------------------------------
def get_monthly_revenue(code: str) -> dict[str, Any] | None:
    with GoodinfoScraper() as s:
        return s.get_monthly_revenue(code)


def get_quarterly_eps(code: str) -> dict[str, Any] | None:
    with GoodinfoScraper() as s:
        return s.get_quarterly_eps(code)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from src.utils.logger import setup_logger

    setup_logger()
    code = "2330"

    print(f"=== {code} 月營收 ===")
    rev = get_monthly_revenue(code)
    print(rev)

    print(f"\n=== {code} 季度 EPS ===")
    eps = get_quarterly_eps(code)
    print(eps)
