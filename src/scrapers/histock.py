"""HiStock 技術面爬蟲(均線 / 布林通道 / 近 N 日漲幅)。

頁面:https://histock.tw/stock/{code}

回傳資料結構(``get_technical``):
    {
        "price": 97.5,        # 現價
        "change": -0.5,       # 漲跌
        "ma5": 95.2,
        "ma10": 94.8,
        "ma20": 95.5,
        "ma60": 96.1,
        "boll_upper": 102.0,  # 布林上軌(20 日 ±2σ)
        "boll_mid": 95.5,
        "boll_lower": 89.0,
        "gain_20d": 0.023,    # 近 20 日漲幅(小數,2.3% 表為 0.023)
    }

無法擷取的欄位回傳 ``None``,但函式整體仍回傳 dict(不為 None)。
"""

from __future__ import annotations

import re
from typing import Any

from lxml import html as lxml_html

from src.scrapers.base import BaseScraper, ScraperError

HISTOCK_URL = "https://histock.tw/stock/{code}"


class HiStockScraper(BaseScraper):
    """HiStock 技術面擷取器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="histock", **kwargs)

    def get_technical(self, code: str) -> dict[str, Any]:
        """擷取個股技術面摘要。

        Args:
            code: 股票代號。

        Returns:
            技術面 dict;個別欄位失敗時為 ``None``,整體不會 raise。
        """
        url = HISTOCK_URL.format(code=code)
        empty = _empty_dict()
        try:
            resp = self.get(url)
            tree = lxml_html.fromstring(resp.content)
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.warning(f"HiStock 抓取失敗 {code}: {exc}")
            return empty

        try:
            return parse_histock_html(tree)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"HiStock 解析失敗 {code}: {exc}")
            return empty


# ----------------------------------------------------------------------
# 解析工具
# ----------------------------------------------------------------------
def _empty_dict() -> dict[str, Any]:
    return {
        "price": None,
        "change": None,
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "ma60": None,
        "boll_upper": None,
        "boll_mid": None,
        "boll_lower": None,
        "gain_20d": None,
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    s = s.replace("−", "-").replace("－", "-")
    if not s or s in {"--", "-", "N/A"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _find_value_after_label(text: str, label: str) -> str | None:
    """在純文字中尋找 label 後的第一個數字 token。"""
    pattern = re.escape(label) + r"\s*[:：]?\s*(-?[\d,]+\.?\d*)"
    m = re.search(pattern, text)
    return m.group(1) if m else None


def parse_histock_html(tree) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """解析 HiStock 個股頁。

    HiStock 頁面結構複雜且常變,本函式採取「容錯式擷取」:
    1. 找所有 <table> 與技術指標相關 <div>。
    2. 用文字 pattern 找標籤後的數字。
    3. 任一欄位找不到就放 ``None``,整體仍回傳 dict。
    """
    result = _empty_dict()

    page_text = tree.text_content()
    page_text = re.sub(r"\s+", " ", page_text)

    # 現價:HiStock 通常在頁面頂部 <span id="Price1_lbTPrice"> 或類似元素
    price_nodes = tree.xpath(
        "//*[contains(@id, 'Price') and contains(@id, 'lbTPrice')]/text()"
    )
    if price_nodes:
        result["price"] = _to_float(price_nodes[0])
    else:
        # fallback: 找 "現價" / "成交價"
        for label in ["成交價", "現價", "收盤"]:
            v = _find_value_after_label(page_text, label)
            if v:
                result["price"] = _to_float(v)
                break

    # 漲跌
    change_nodes = tree.xpath(
        "//*[contains(@id, 'Price') and contains(@id, 'lbChange')]/text()"
    )
    if change_nodes:
        result["change"] = _to_float(change_nodes[0])

    # 均線 / 布林:用文字標籤 pattern
    ma_labels = {
        "ma5": ["5日均", "MA5", "5日線"],
        "ma10": ["10日均", "MA10", "10日線"],
        "ma20": ["20日均", "MA20", "月線"],
        "ma60": ["60日均", "MA60", "季線"],
    }
    for key, labels in ma_labels.items():
        for label in labels:
            v = _find_value_after_label(page_text, label)
            if v:
                result[key] = _to_float(v)
                break

    boll_labels = {
        "boll_upper": ["布林上軌", "上軌", "Upper"],
        "boll_mid": ["布林中軌", "中軌", "Middle"],
        "boll_lower": ["布林下軌", "下軌", "Lower"],
    }
    for key, labels in boll_labels.items():
        for label in labels:
            v = _find_value_after_label(page_text, label)
            if v:
                result[key] = _to_float(v)
                break

    # 近 20 日漲幅(嘗試多種寫法)
    for label in ["20日漲幅", "近20日漲幅", "近 20 日漲幅", "月漲幅"]:
        v = _find_value_after_label(page_text, label)
        if v:
            f = _to_float(v)
            if f is not None:
                # 若大於 1,假設是百分比格式(e.g. 2.3 表示 2.3%)
                result["gain_20d"] = f / 100 if abs(f) > 1 else f
                break

    # 若找不到 20 日漲幅,嘗試從 ma20 與 price 推估( (price - 20日前) / 20日前 )
    if (
        result["gain_20d"] is None
        and result["price"] is not None
        and result["ma20"] is not None
        and result["ma20"] > 0
    ):
        # 近似估計:(現價 - MA20) / MA20  (僅供參考,非精確)
        result["gain_20d"] = (result["price"] - result["ma20"]) / result["ma20"]

    return result


# ----------------------------------------------------------------------
# 模組級捷徑函式
# ----------------------------------------------------------------------
def get_technical(code: str) -> dict[str, Any]:
    with HiStockScraper() as s:
        return s.get_technical(code)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from src.utils.logger import setup_logger

    setup_logger()
    for code in ("2330",):
        print(f"=== {code} 技術面 ===")
        data = get_technical(code)
        for k, v in data.items():
            print(f"  {k:>12}: {v}")
