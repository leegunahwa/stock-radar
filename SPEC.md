# 📈 台股每日籌碼掃描專案 SPEC

> 給 Claude Code 的開發規格文件
> 專案目標:每日台股收盤後,自動篩選「籌碼進駐 + 低基期 + 基本面正向」的候選股
> 作者:LLLeo
> 版本:v1.0

---

## 📋 目錄

1. [專案目標](#專案目標)
2. [技術棧](#技術棧)
3. [專案結構](#專案結構)
4. [資料來源](#資料來源)
5. [Stage 1:專案初始化](#stage-1專案初始化)
6. [Stage 2:爬蟲實作](#stage-2爬蟲實作)
7. [Stage 3:篩選邏輯](#stage-3篩選邏輯)
8. [Stage 4:排程與通知](#stage-4排程與通知)
9. [部署指引](#部署指引)
10. [常見問題](#常見問題)

---

## 專案目標

每天台股收盤後 (15:30),自動執行下列流程:

1. **籌碼面初篩** — 從證交所抓投信買賣超、TWSE 分點買賣超
2. **技術面過濾** — 排除已大漲、留下均線糾結未發動的標的
3. **基本面驗證** — 月營收年增 OR Q EPS 為正,排除虧損股
4. **產出結果** — 寫入 Google Sheet + 寄送 Email 通知

---

## 技術棧

| 類別 | 工具 |
|------|------|
| 語言 | Python 3.11+ |
| 爬蟲 | `requests`, `beautifulsoup4`, `lxml` |
| 資料處理 | `pandas`, `numpy` |
| Google API | `gspread`, `google-auth` |
| 排程 | GitHub Actions (cron) |
| 環境變數 | `python-dotenv` |
| 重試機制 | `tenacity` |
| 程式碼品質 | `black`, `flake8`, `mypy` |

---

## 專案結構

```
stock-radar/
├── README.md
├── SPEC.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/
│   └── workflows/
│       └── daily_scan.yml       # GitHub Actions 排程
├── config/
│   └── filters.yaml             # 篩選條件參數化
├── src/
│   ├── __init__.py
│   ├── main.py                  # 主流程
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py              # 共用 Session/Retry/UA
│   │   ├── twse_fund.py         # 證交所投信買賣超
│   │   ├── twse_broker.py       # 證交所分點買賣超
│   │   ├── goodinfo.py          # 月營收/EPS
│   │   ├── histock.py           # 技術面(均線/布林)
│   │   └── ptt_stock.py         # PTT 籌碼討論關鍵字
│   ├── filters/
│   │   ├── __init__.py
│   │   ├── chip_filter.py       # 籌碼面條件
│   │   ├── tech_filter.py       # 技術面條件
│   │   └── fundamental_filter.py
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── gsheet.py
│   │   └── email_sender.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── retry.py
│       └── trading_calendar.py
├── output/                      # 每日結果(.gitignore)
└── tests/
    ├── __init__.py
    ├── test_scrapers.py
    └── test_filters.py
```

---

## 資料來源

### 公開免費資料

| 來源 | URL | 提供資料 | 反爬難度 |
|------|-----|---------|---------|
| TWSE 投信買賣超 | `https://www.twse.com.tw/rwd/zh/fund/T86` | 全市場投信進出 | 低(JSON API) |
| TWSE 分點買賣超 | `https://www.twse.com.tw/rwd/zh/afterTrading/BFIAUU_d` | 每日前 30 大買超個股 | 低 |
| TWSE 個股分點 | `https://bsr.twse.com.tw/bshtm/bsMenu.aspx` | 個股分點明細(需驗證碼) | 高 |
| Goodinfo | `https://goodinfo.tw/tw/StockDetail.asp` | 月營收/EPS/籌碼 | 中(UA 檢查) |
| HiStock | `https://histock.tw/stock/{code}` | 技術面/均線 | 低 |
| PTT Stock | `https://www.ptt.cc/bbs/Stock/` | 文字討論 | 低(over18 cookie) |
| FinMind API | `https://finmindtrade.com/` | 整合性資料 | 無(免費 600 次/天) |

> **重要**:免費的 TWSE 分點資料只有「每日全市場前 30 大買超個股」與
> 「特定個股的當日所有分點明細(需驗證碼)」,**無法做到「特定贏家分點
> 連續買超」這種跨股票追蹤**。本專案會用「TWSE 投信買賣超 + 個股當日
> 前 5 大分點」作為替代指標。

---

## Stage 1:專案初始化

**任務範圍**:目錄結構、空檔案、設定檔模板,不實作任何爬蟲或業務邏輯。

**建立清單**:
1. 目錄結構
2. `requirements.txt` 套件版本鎖定
3. `.env.example` 範例環境變數
4. `.gitignore`(Python 標準 + `output/` + `.env`)
5. `README.md` 含完整安裝/部署說明
6. `config/filters.yaml` 篩選參數設定檔
7. `src/utils/logger.py` 共用 logger
8. `src/utils/trading_calendar.py` 交易日判斷
9. `.github/workflows/daily_scan.yml` GitHub Actions 框架

---

## Stage 2:爬蟲實作

實作 `src/scrapers/` 下的所有爬蟲:`base`、`twse_fund`、`twse_broker`、
`goodinfo`、`histock`、`ptt_stock`。

每個 scraper 必須附 `if __name__ == "__main__"` 範例執行,
測試資料格式正確後才能進入 Stage 3。

若 Goodinfo 反爬蟲擋太兇,改用 FinMind API。

---

## Stage 3:篩選邏輯

實作三層 filter(`chip` / `tech` / `fundamental`)與 `src/main.py` 主流程。

詳細條件與評分權重見 `config/filters.yaml`。

---

## Stage 4:排程與通知

完成 `.github/workflows/daily_scan.yml`、Google Sheet 寫入、Email 寄送。

---

## 部署指引

詳見 [README.md](./README.md) 的「部署指引」章節。

---

## 常見問題

### Q1:Goodinfo 一直被擋怎麼辦?
切換到 FinMind:註冊 https://finmindtrade.com/ 取得 token,
加入 GitHub Secret `FINMIND_TOKEN`,改用 `src/scrapers/finmind.py`。

### Q2:GitHub Actions 沒在排程時間執行?
- GitHub cron 不保證準時(可能延遲 5-30 分鐘)
- 台北 15:30 = UTC 07:30 = `30 7 * * 1-5`
- repo 連續 60 天無 commit 會自動停用 schedule

### Q3:每天爬 100 檔股票會被 ban 嗎?
- 投信初篩後通常剩 30-60 檔
- 每檔請求 3 個來源 × 5 秒間隔 = 15 秒
- 60 檔 × 15 秒 = 15 分鐘,GitHub Actions 30 分鐘 timeout 內可完成

### Q4:LINE Notify 還能用嗎?
LINE Notify 已於 2025/03/31 終止,改用 LINE Messaging API 或 Telegram Bot。

### Q5:免費版能撐多久?
| 資源 | 免費額度 | 本專案用量 |
|------|---------|-----------|
| GitHub Actions | 2000 分鐘/月 | 約 600 分鐘/月 |
| Google Sheets API | 60 req/min | 1 req/天 |
| FinMind | 600 req/天 | 約 200 req/天 |
| Gmail SMTP | 500 封/天 | 1 封/天 |

---

## 版本紀錄

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-04-25 | 初版 |
