# 📈 Stock Radar — 台股每日籌碼掃描

每日台股收盤後,自動篩選「**籌碼進駐 + 低基期 + 基本面正向**」的候選股,
寫入 Google Sheet 並寄送 Email 報告。

> 作者:LLLeo  ·  版本:v1.0
> 詳細規格請見 [SPEC.md](./SPEC.md)

---

## ✨ 功能特色

- **籌碼面初篩**:從證交所抓投信買賣超、TWSE 分點買賣超
- **技術面過濾**:排除已大漲、留下均線糾結未發動的標的
- **基本面驗證**:月營收年增 OR Q EPS 為正,排除虧損股
- **自動產出**:寫入 Google Sheet + 寄送 Email 通知
- **GitHub Actions 排程**:每個交易日 15:30 (UTC+8) 自動執行

---

## 🛠 技術棧

| 類別 | 工具 |
|------|------|
| 語言 | Python 3.11+ |
| 爬蟲 | `requests`, `beautifulsoup4`, `lxml` |
| 資料處理 | `pandas`, `numpy` |
| Google API | `gspread`, `google-auth` |
| 排程 | GitHub Actions (cron) |
| 環境變數 | `python-dotenv` |
| 重試機制 | `tenacity` |

---

## 📂 專案結構

```
stock-radar/
├── README.md
├── SPEC.md                      # 詳細規格
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/
│   └── workflows/
│       └── daily_scan.yml       # GitHub Actions 排程
├── config/
│   └── filters.yaml             # 篩選條件參數化
├── src/
│   ├── main.py                  # 主流程
│   ├── scrapers/                # 各來源爬蟲
│   ├── filters/                 # 三層篩選邏輯
│   ├── notifiers/               # Google Sheet / Email
│   └── utils/                   # logger / 交易日判斷 / retry
├── output/                      # 每日結果(已 .gitignore)
└── tests/
```

---

## 🚀 安裝與快速開始

### 1. Clone 專案

```bash
git clone https://github.com/<你的帳號>/stock-radar.git
cd stock-radar
```

### 2. 建立虛擬環境並安裝套件

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入所有必要值(見下方部署指引)
```

### 4. 本地執行

```bash
python -m src.main                  # 真實流程,抓今日資料
python -m src.main --date 20260424  # 指定日期
python -m src.main --mock           # 用內建 mock 資料端到端驗證,不打外網
python -m src.main --use-finmind    # 改用 FinMind 取代 Goodinfo
```

執行結果**永遠**會寫到 `output/{date}.json` 與 `output/{date}.html`(本機備份)。
若同時設定了 Sheet / SMTP credentials,則額外寫入 Google Sheet 與寄送 Email。

### 部分設定也 OK

- 沒設 Google credentials → 只跳過 Sheet 寫入,本機 JSON 仍保留。
- 沒設 SMTP credentials → 只跳過 Email,本機 HTML 仍保留。
- 兩者皆無 → 仍可正常跑,只在 `output/` 看結果。
- 寫入 / 寄送過程任何錯誤都只 log warning,不會中斷流程。

---

## 🔐 部署指引(雲端排程)

### 步驟 1:建立 Google Service Account

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立新專案(或用既有專案)
3. 啟用 **Google Sheets API**
4. 「IAM 與管理」→「服務帳戶」→「建立服務帳戶」
5. 完成建立後,點該帳戶 →「金鑰」→「新增金鑰」→「JSON」
6. 下載 JSON 檔(這就是 `GOOGLE_SERVICE_ACCOUNT_JSON` 的值)

### 步驟 2:準備 Google Sheet

1. 建立新的 Google Sheet
2. 複製網址中的 ID:`docs.google.com/spreadsheets/d/{這段就是 ID}/edit`
3. 點右上「共用」→ 把 Service Account 的 email
   (JSON 裡 `client_email` 欄位)加入,給「**編輯者**」權限

### 步驟 3:Gmail App Password

1. 前往 [Google 帳戶設定](https://myaccount.google.com/security)
2. 開啟「兩步驟驗證」(必要)
3. 「應用程式密碼」→ 建立 → 取得 16 碼密碼
4. 此密碼即 `EMAIL_SMTP_PASS`(**不是**你的 Gmail 登入密碼)

### 步驟 4:設定 GitHub Secrets

在 repo 點 **Settings → Secrets and variables → Actions → New repository secret**,
逐一新增:

| Name | Value |
|------|-------|
| `GOOGLE_SHEET_ID` | 步驟 2 的 ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 步驟 1 的整個 JSON 內容 |
| `EMAIL_SMTP_HOST` | `smtp.gmail.com` |
| `EMAIL_SMTP_USER` | 你的 Gmail |
| `EMAIL_SMTP_PASS` | 步驟 3 的 16 碼密碼 |
| `NOTIFY_EMAIL_TO` | 收件 Email |
| `FINMIND_TOKEN` | (選用)FinMind API Token |

### 步驟 5:測試運作

到 GitHub repo 的 **Actions** 頁籤 → **Daily Stock Scan** → **Run workflow**,
可帶以下參數:

- **date**:留空 = 今日;或填 `YYYYMMDD` 跑歷史日期。
- **use_finmind**:勾選 → 改用 FinMind API。
- **mock**:勾選 → 用內建 mock 資料,不打外網(用來驗證流程與 Sheet/SMTP 設定)。

> 💡 **建議第一次驗證**:勾 `mock` 跑一次,確認 Google Sheet 真的會新增工作表、
> 收件信箱真的收到信。確認後再正常跑真實資料。

### 失敗自動通知

定時排程(`schedule`)失敗時會自動在 repo 開一個 issue
(label: `bug`、`auto-generated`),不需要每天上 Actions 看狀態。
手動 `workflow_dispatch` 失敗則不會開 issue,避免測試時刷洗。

---

## ⏰ 排程說明

- 預設於台北時間 **每週一至週五 15:30** 執行(收盤後 30 分鐘)
- GitHub Actions 使用 UTC,對應 cron:`30 7 * * 1-5`
- 國定假日由 `src/utils/trading_calendar.py` 判斷自動跳過
- 也可手動觸發(`workflow_dispatch`)

---

## 🧪 開發

### 程式碼風格

- 遵循 PEP 8
- 全程使用 type hints
- 函式/類別需有 docstring
- 註解使用繁體中文,變數命名使用英文

### 執行測試

```bash
pytest tests/
```

### 格式化

```bash
black src/ tests/
flake8 src/ tests/
mypy src/
```

---

## ❓ 常見問題

### Q: Goodinfo 被擋怎麼辦?
切換到 FinMind API,在 `.env` 中填入 `FINMIND_TOKEN` 即可。

### Q: GitHub Actions 沒在排程時間執行?
- GitHub cron 不保證準時(可能延遲 5-30 分鐘)
- repo 連續 60 天無 commit 會自動停用 schedule

### Q: 想加 Telegram / Discord 通知?
在 `src/notifiers/` 新增對應檔案,於 `src/main.py` 註冊即可。

---

## ⚠️ 免責聲明

本專案僅供學習與個人研究使用,**不構成任何投資建議**。
投資有賴自行判斷,風險自負。

---

## 📜 授權

MIT License
