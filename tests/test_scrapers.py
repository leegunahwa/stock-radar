"""scrapers 單元測試 — 用 fixture 驗證解析邏輯(不打外部網路)。

Stage 2 在 sandbox 環境無法直接連 TWSE / Goodinfo / HiStock / PTT
(對外 HTTP 全被 allowlist 擋),因此這裡用「真實格式的最小範本」
驗證每個解析器的 happy path 與失敗 fallback。

實際的網路測試請在本機或 GitHub Actions 上跑各 scraper 的 ``__main__``。
"""

from __future__ import annotations

from lxml import html as lxml_html

from src.scrapers import goodinfo, histock, ptt_stock, twse_broker, twse_fund

# =============================================================================
# T86 投信買賣超
# =============================================================================
T86_PAYLOAD = {
    "stat": "OK",
    "date": "20260424",
    "fields": [
        "證券代號",
        "證券名稱",
        "外陸資買賣超股數(不含外資自營商)",
        "外資自營商買賣超股數",
        "投信買進股數",
        "投信賣出股數",
        "投信買賣超股數",
        "自營商買賣超股數",
    ],
    "data": [
        ["2330", "台積電", "1,234,000", "0", "5,000,000", "1,000,000", "4,000,000", "0"],
        ["2454", "聯發科", "0", "0", "200,000", "300,000", "-100,000", "0"],
    ],
}


def test_t86_parse_happy_path() -> None:
    df = twse_fund.parse_t86_payload(T86_PAYLOAD)
    assert list(df.columns) == ["stock_id", "name", "buy", "sell", "net_buy"]
    assert len(df) == 2
    row = df[df["stock_id"] == "2330"].iloc[0]
    assert row["name"] == "台積電"
    assert row["buy"] == 5_000_000
    assert row["sell"] == 1_000_000
    assert row["net_buy"] == 4_000_000
    assert df[df["stock_id"] == "2454"].iloc[0]["net_buy"] == -100_000


def test_t86_payload_ok_check() -> None:
    assert twse_fund._is_payload_ok(T86_PAYLOAD)
    assert not twse_fund._is_payload_ok({"stat": "ERROR"})
    assert not twse_fund._is_payload_ok({})


def test_t86_to_int() -> None:
    assert twse_fund._to_int("1,234") == 1234
    assert twse_fund._to_int("--") == 0
    assert twse_fund._to_int(None) == 0
    assert twse_fund._to_int(42) == 42


# =============================================================================
# BFIAUU 全市場彙總
# =============================================================================
def test_bfiauu_parse_handles_2d_fields() -> None:
    payload = {
        "stat": "OK",
        "fields": [["項目", "買進金額", "賣出金額", "買賣差額"]],
        "data": [
            ["外資及陸資", "100,000", "80,000", "20,000"],
            ["投信", "50,000", "30,000", "20,000"],
        ],
    }
    df = twse_broker.parse_bfiauu_payload(payload)
    assert df.shape == (2, 4)
    assert df.iloc[1]["買賣差額"] == 20000


def test_bfiauu_parse_handles_1d_fields() -> None:
    payload = {
        "stat": "OK",
        "fields": ["項目", "買進金額", "賣出金額"],
        "data": [["外資", "1,000", "500"]],
    }
    df = twse_broker.parse_bfiauu_payload(payload)
    assert list(df.columns) == ["項目", "買進金額", "賣出金額"]
    assert df.iloc[0]["買進金額"] == 1000


# =============================================================================
# Goodinfo 月營收
# =============================================================================
GOODINFO_REVENUE_HTML = """
<html><body>
<table class="solid_1_padding_4_4_tbl">
  <tr>
    <td>月別</td><td>單月營收</td><td>月增(%)</td><td>年增(%)</td>
    <td>累計營收</td><td>累計年增(%)</td>
  </tr>
  <tr>
    <td>2026/03</td><td>17,844</td><td>10.55</td><td>-11.94</td>
    <td>56,257</td><td>5.07</td>
  </tr>
  <tr>
    <td>2026/02</td><td>16,123</td><td>-3.21</td><td>2.10</td>
    <td>38,413</td><td>4.50</td>
  </tr>
</table>
</body></html>
"""


def test_goodinfo_monthly_revenue_parse() -> None:
    tree = lxml_html.fromstring(GOODINFO_REVENUE_HTML)
    result = goodinfo.parse_monthly_revenue_html(tree)
    assert result["month"] == "2026/03"
    assert result["revenue"] == 17844.0
    assert result["mom"] == 10.55
    assert result["yoy"] == -11.94
    assert result["ytd_revenue"] == 56257.0
    assert result["ytd_yoy"] == 5.07


# =============================================================================
# Goodinfo 季度 EPS
# =============================================================================
GOODINFO_EPS_HTML = """
<html><body>
<table class="solid_1_padding_4_4_tbl">
  <tr>
    <td>季別</td><td>EPS(元)</td><td>EPS年增(%)</td>
    <td>累計EPS</td><td>累計年增(%)</td>
  </tr>
  <tr>
    <td>2025Q4</td><td>1.93</td><td>251</td><td>6.8</td><td>-15</td>
  </tr>
</table>
</body></html>
"""


def test_goodinfo_eps_parse() -> None:
    tree = lxml_html.fromstring(GOODINFO_EPS_HTML)
    result = goodinfo.parse_quarterly_eps_html(tree)
    assert result["quarter"] == "2025Q4"
    assert result["eps"] == 1.93
    assert result["yoy"] == 251
    assert result["ytd_eps"] == 6.8
    assert result["ytd_yoy"] == -15


def test_goodinfo_to_float() -> None:
    assert goodinfo._to_float("1,234.56") == 1234.56
    assert goodinfo._to_float("-12.3%") == -12.3
    assert goodinfo._to_float("--") is None
    assert goodinfo._to_float("N/A") is None
    assert goodinfo._to_float(None) is None


# =============================================================================
# HiStock 技術面
# =============================================================================
HISTOCK_HTML = """
<html><body>
<span id="Price1_lbTPrice">97.5</span>
<span id="Price1_lbChange">-0.5</span>
<div>
  5日均: 95.2
  10日均: 94.8
  20日均: 95.5
  60日均: 96.1
  布林上軌: 102.0
  布林中軌: 95.5
  布林下軌: 89.0
  20日漲幅: 2.3
</div>
</body></html>
"""


def test_histock_parse() -> None:
    tree = lxml_html.fromstring(HISTOCK_HTML)
    data = histock.parse_histock_html(tree)
    assert data["price"] == 97.5
    assert data["change"] == -0.5
    assert data["ma5"] == 95.2
    assert data["ma10"] == 94.8
    assert data["ma20"] == 95.5
    assert data["ma60"] == 96.1
    assert data["boll_upper"] == 102.0
    assert data["boll_lower"] == 89.0
    # 2.3 > 1 → 視為百分比 → 0.023
    assert abs(data["gain_20d"] - 0.023) < 1e-9


def test_histock_empty_html() -> None:
    tree = lxml_html.fromstring("<html><body></body></html>")
    data = histock.parse_histock_html(tree)
    # 全部欄位都應該存在(值為 None)
    expected_keys = {
        "price", "change", "ma5", "ma10", "ma20", "ma60",
        "boll_upper", "boll_mid", "boll_lower", "gain_20d",
    }
    assert set(data.keys()) == expected_keys
    assert all(v is None for v in data.values())


# =============================================================================
# PTT
# =============================================================================
PTT_INDEX_HTML = """
<html><body>
<div class="r-list-container">
  <div class="r-ent">
    <div class="title"><a href="/bbs/Stock/M.1.html">[新聞] 2330 台積電 主力佈局</a></div>
    <div class="meta"><div class="author">user1</div><div class="date"> 4/24</div></div>
  </div>
  <div class="r-ent">
    <div class="title"><a href="/bbs/Stock/M.2.html">[心得] 2454 聯發科 連續買超</a></div>
    <div class="meta"><div class="author">user2</div><div class="date"> 4/23</div></div>
  </div>
  <div class="r-ent">
    <div class="title">(本文已被刪除)</div>
    <div class="meta"><div class="author">-</div><div class="date"> 4/22</div></div>
  </div>
</div>
<div class="btn-group btn-group-paging">
  <a class="btn wide" href="/bbs/Stock/index100.html">‹ 上頁</a>
</div>
</body></html>
"""


def test_ptt_parse_index() -> None:
    tree = lxml_html.fromstring(PTT_INDEX_HTML)
    articles, prev_link = ptt_stock.parse_index_page(tree)
    assert len(articles) == 2  # 已刪文章被跳過
    assert articles[0]["title"] == "[新聞] 2330 台積電 主力佈局"
    assert articles[0]["url"].endswith("/bbs/Stock/M.1.html")
    assert articles[0]["date_str"] == "4/24"
    assert prev_link is not None and "index100" in prev_link
