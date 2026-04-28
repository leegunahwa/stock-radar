"""PTT Stock 版籌碼討論關鍵字搜尋。

頁面:
- 列表頁: https://www.ptt.cc/bbs/Stock/index.html / index{N}.html
- 文章頁: https://www.ptt.cc/bbs/Stock/M.{ts}.A.XXX.html

PTT 18 禁需要 cookie ``over18=1``。

提供:
- ``search_keywords(stock_codes, keywords, days=7)``: 搜尋近 N 天文章
  中,標題或內文是否提及指定股票代號 + 關鍵字組合。

回傳結構:
    {
        "2330": {
            "主力": 3,
            "吃貨": 1,
            "titles": ["[新聞] ...", "[心得] ...", ...],
        },
        ...
    }
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from src.scrapers.base import BaseScraper, ScraperError

PTT_BASE = "https://www.ptt.cc"
PTT_BOARD_INDEX = "https://www.ptt.cc/bbs/Stock/index.html"

DEFAULT_KEYWORDS: list[str] = [
    "主力",
    "吃貨",
    "佈局",
    "默默",
    "進駐",
    "贏家分點",
    "籌碼集中",
    "連續買超",
    "地緣券商",
]


class PttStockScraper(BaseScraper):
    """PTT Stock 版搜尋器。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(name="ptt_stock", **kwargs)
        # PTT 18 禁
        self.session.cookies.set("over18", "1", domain=".ptt.cc")

    # ------------------------------------------------------------------
    def list_recent_articles(
        self, days: int = 7, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """蒐集近 ``days`` 天內的文章標題 + URL。

        透過反向翻頁(index.html → 上一頁)直到觸及超過 ``days`` 天前的文章。

        Args:
            days: 要回溯幾天。
            max_pages: 最多回溯幾頁(避免無限迴圈)。

        Returns:
            list of dict: [{"title": str, "url": str, "author": str,
            "date_str": str}, ...]
        """
        cutoff = datetime.now() - timedelta(days=days)
        articles: list[dict[str, Any]] = []

        url: str | None = PTT_BOARD_INDEX
        page = 0
        while url and page < max_pages:
            try:
                resp = self.get(url)
                tree = lxml_html.fromstring(resp.content)
            except (ScraperError, Exception) as exc:  # noqa: BLE001
                self.logger.warning(f"PTT 抓取列表失敗 {url}: {exc}")
                break

            page_articles, prev_link = parse_index_page(tree)
            # 加入文章
            should_stop = False
            for art in page_articles:
                # 嘗試解析日期
                if _is_older_than(art.get("date_str"), cutoff):
                    should_stop = True
                articles.append(art)

            if should_stop:
                break
            url = urljoin(PTT_BASE, prev_link) if prev_link else None
            page += 1

        return articles

    # ------------------------------------------------------------------
    def fetch_article_content(self, article_url: str) -> str:
        """擷取單篇文章內文(失敗回空字串)。"""
        try:
            resp = self.get(article_url)
            tree = lxml_html.fromstring(resp.content)
            main = tree.xpath("//div[@id='main-content']")
            if not main:
                return ""
            return main[0].text_content()
        except (ScraperError, Exception) as exc:  # noqa: BLE001
            self.logger.debug(f"PTT 文章抓取失敗 {article_url}: {exc}")
            return ""

    # ------------------------------------------------------------------
    def search_keywords(
        self,
        stock_codes: list[str],
        keywords: list[str] | None = None,
        days: int = 7,
        scan_body: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """在近 N 天文章中,搜尋股票代號 + 關鍵字提及。

        Args:
            stock_codes: 要搜尋的股票代號清單(例如 ["2330", "2454"])。
            keywords: 關鍵字清單;為 None 時使用 ``DEFAULT_KEYWORDS``。
            days: 回溯天數。
            scan_body: 是否進一步抓文章內文(較耗時)。預設只看標題。

        Returns:
            ``{stock_id: {keyword: count, "titles": [...]}}``。
            未提及的股票仍會出現,值為 ``{"titles": [], <kw>: 0, ...}``。
        """
        if not stock_codes:
            return {}
        kw_list = keywords or DEFAULT_KEYWORDS

        # 初始化結果
        result: dict[str, dict[str, Any]] = {
            code: {**{kw: 0 for kw in kw_list}, "titles": []}
            for code in stock_codes
        }

        articles = self.list_recent_articles(days=days)
        self.logger.info(f"PTT 共抓到 {len(articles)} 篇近 {days} 日文章")

        for art in articles:
            title = art.get("title", "")
            text = title
            if scan_body and art.get("url"):
                text = title + "\n" + self.fetch_article_content(art["url"])

            for code in stock_codes:
                if code in text:
                    # 該文章與此 stock_id 有關
                    result[code]["titles"].append(title)
                    for kw in kw_list:
                        if kw in text:
                            result[code][kw] += 1

        return result


# ----------------------------------------------------------------------
# 解析工具(純函式)
# ----------------------------------------------------------------------
def parse_index_page(tree) -> tuple[list[dict[str, Any]], str | None]:  # type: ignore[no-untyped-def]
    """解析 PTT 看板列表頁。

    Returns:
        (articles, previous_page_link)
        articles: list of {"title", "url", "author", "date_str"}
    """
    articles: list[dict[str, Any]] = []
    for entry in tree.xpath("//div[@class='r-ent']"):
        title_a = entry.xpath(".//div[@class='title']/a")
        if not title_a:
            # 已被刪除的文章
            continue
        title = (title_a[0].text_content() or "").strip()
        href = title_a[0].get("href") or ""
        author_nodes = entry.xpath(".//div[@class='author']/text()")
        date_nodes = entry.xpath(".//div[@class='date']/text()")
        articles.append(
            {
                "title": title,
                "url": urljoin(PTT_BASE, href) if href else None,
                "author": (author_nodes[0].strip() if author_nodes else ""),
                "date_str": (date_nodes[0].strip() if date_nodes else ""),
            }
        )

    # 上一頁(較舊)連結
    prev_link = None
    for a in tree.xpath("//div[@class='btn-group btn-group-paging']/a"):
        if "上頁" in (a.text_content() or ""):
            prev_link = a.get("href")
            break

    return articles, prev_link


def _is_older_than(date_str: str | None, cutoff: datetime) -> bool:
    """PTT 列表的 date 欄位是「M/DD」(如 "4/25"),沒有年。

    本函式判斷此日期是否「明顯早於」cutoff(回溯超過 days 天)。
    若無法解析,回傳 False(保守:不停止)。
    """
    if not date_str:
        return False
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})", date_str.strip())
    if not m:
        return False
    month, day = int(m.group(1)), int(m.group(2))
    now = datetime.now()
    # 假設文章是當年;若解析後日期 > 今天,推測是去年
    candidate = datetime(now.year, month, day)
    if candidate > now + timedelta(days=2):
        candidate = candidate.replace(year=now.year - 1)
    return candidate < cutoff


# ----------------------------------------------------------------------
# 模組級捷徑函式
# ----------------------------------------------------------------------
def search_keywords(
    stock_codes: list[str],
    keywords: list[str] | None = None,
    days: int = 7,
) -> dict[str, dict[str, Any]]:
    with PttStockScraper() as s:
        return s.search_keywords(stock_codes, keywords, days=days)


# ----------------------------------------------------------------------
# 範例執行
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from src.utils.logger import setup_logger

    setup_logger()

    print("=== PTT Stock 關鍵字搜尋 ===")
    result = search_keywords(["2330", "2454"], days=3)
    for code, info in result.items():
        total = sum(v for k, v in info.items() if k != "titles")
        print(
            f"\n{code}: 提及 {len(info['titles'])} 篇,關鍵字總命中 {total} 次"
        )
        for kw, count in info.items():
            if kw == "titles":
                continue
            if count > 0:
                print(f"  {kw}: {count}")
        if info["titles"]:
            print("  最近標題:")
            for t in info["titles"][:3]:
                print(f"    - {t}")
