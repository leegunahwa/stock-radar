# 📋 Stock Radar 部署與操作指南

> 這份文件包含完整的部署步驟與所有必要 context。
> **新對話時把這份貼給 Claude 就能無縫接續。**

---

## 🎯 專案現況

- **Repo**: `leegunahwa/stock-radar`
- **開發分支**: `claude/taiwan-stock-screening-stage1-XINBg`
- **完成階段**: Stage 1-4 全部完成,39 項單元測試全通過
- **功能**: 每日台股收盤後自動篩選「投信 / 主力買超 + 低基期 + 基本面正向」候選股,寫 Google Sheet + 寄 Email
- **詳細規格**: 見 `SPEC.md`
- **完整安裝/部署說明**: 見 `README.md`

### 已實作模組
```
src/scrapers/   T86 投信+主力 / BFIAUU / Goodinfo / HiStock / PTT / FinMind 後援
src/filters/    chip(投信+主力+連續+PTT) / tech(MA糾結+布林+漲幅+季線) / fundamental
src/notifiers/  gsheet(每日新增 worksheet) / email_sender(SMTP+HTML)
src/main.py     完整流程 + --mock / --date / --use-finmind 旗標
.github/workflows/daily_scan.yml  排程 + 手動觸發
config/filters.yaml               全部篩選參數可調
```

---

## ⚠️ 部署前必做:把分支合到 main

GitHub Actions 的 `workflow_dispatch`(手動觸發)**只看預設分支(main)**。
目前 main 是空的,所以 Actions tab 還看不到 Daily Stock Scan。

### 操作
1. 開 https://github.com/leegunahwa/stock-radar/pulls
2. **New pull request**
3. base: `main` ← compare: `claude/taiwan-stock-screening-stage1-XINBg`
4. **Create pull request** → 標題填 `Initial release` → 再按一次 **Create pull request**
5. 下一頁 **Merge pull request** → **Confirm merge**

合完後,Actions tab 就會出現 **Daily Stock Scan**。

---

## 🚦 Step 1:用 Mock 確認部署成功(零 API,5 分鐘)

**目的**:不需任何 credentials,確認 GitHub Actions 跑得起來、整個 pipeline 沒爛。

### 操作
1. 開 https://github.com/leegunahwa/stock-radar/actions
2. 左邊點 **Daily Stock Scan**
3. 右邊 **Run workflow**(綠色按鈕)
4. 跳出選單:
   - **Use workflow from**: `main`(預設)
   - **指定日期**: 留空
   - **改用 FinMind**: 不勾
   - **使用內建 mock 資料**: ✅ **勾**
5. 按 **Run workflow**

### 等約 1 分鐘後驗證
- 點剛跑那一筆 run
- ✓ 綠色 → 拉到底 **Artifacts** 下載 `scan-result-XXX`,解壓看到 `20260424.json` 與 `.html` 即成功
- ✗ 紅色 → 點失敗的 step 看 log,把錯誤訊息貼給 Claude

---

## 🚦 Step 2:加 Google Sheet(15 分鐘,推薦)

**目的**:把每日結果寫到 Google Sheet,自動保留歷史,免費無流量限制。

### 2-1. Google Cloud 建 Service Account
1. https://console.cloud.google.com/ 登入
2. 上方選單 **新增專案** → 名字 `stock-radar` → 建立
3. 左選單 **API 與服務 → 程式庫** → 搜尋 **Google Sheets API** → **啟用**
4. 左選單 **IAM 與管理 → 服務帳戶 → 建立服務帳戶**
   - 名字 `stock-radar-bot` → **建立並繼續** → **完成**
5. 點剛建的服務帳戶 → **金鑰 → 新增金鑰 → 建立新的金鑰 → JSON → 建立**
6. 自動下載一個 `.json` 檔(等下要用)

### 2-2. 建 Google Sheet 並分享
1. https://sheets.google.com/ 建空白試算表 → 標題 `台股籌碼掃描`
2. 從網址複製 ID:`docs.google.com/spreadsheets/d/【這串就是 ID】/edit`
3. 右上 **共用** → 貼**剛剛 JSON 檔裡 `client_email` 欄位的 email**
   (像 `stock-radar-bot@xxx.iam.gserviceaccount.com`)
4. 角色選 **編輯者** → **傳送**

### 2-3. 加 GitHub Secrets
到 repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `GOOGLE_SHEET_ID` | 步驟 2-2 第 2 點的 ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 用文字編輯器打開 2-1 的 JSON 檔,**整段內容**(含 `{...}`)貼上 |

### 2-4. 再跑一次 mock workflow
回 Step 1 操作,跑完去看 Google Sheet — **應該多一個 `2026-04-24` 工作表**,裡面 4 檔 mock 資料 ✅

---

## 🚦 Step 3:加 Email(5 分鐘,可跳過)

**只看 Sheet 的話可跳過。** 想每天信箱收到報表才需要。

### 3-1. Gmail App Password
1. https://myaccount.google.com/security
2. 開啟 **兩步驟驗證**(必要)
3. 開啟後拉到底 **應用程式密碼** → 點進去
4. 名稱 `Stock Radar` → 建立 → 取得 16 碼密碼

### 3-2. GitHub Secrets 加 4 個

| Name | Value |
|------|-------|
| `EMAIL_SMTP_HOST` | `smtp.gmail.com` |
| `EMAIL_SMTP_USER` | 你的 Gmail |
| `EMAIL_SMTP_PASS` | 步驟 3-1 的 16 碼 |
| `NOTIFY_EMAIL_TO` | 收件信箱(可同 SMTP_USER) |

### 3-3. 跑 mock workflow → 應收到信
標題:`[台股籌碼掃描] 20260424 - 共 4 檔候選`

---

## 🚦 Step 4:跑真實資料(正式上線)

mock 都通了之後,Run workflow:
- **指定日期**: 留空(自動取今天 / 最近交易日)
- **使用內建 mock 資料**: **不勾**
- **改用 FinMind**: 不勾(預設先用 Goodinfo)

按 Run。會去爬 TWSE / Goodinfo / HiStock / PTT。

### 可能狀況
- ✅ **跑成功** → Sheet 多一個今日工作表的真實資料
- ❌ **Goodinfo 一直 fail** → 改勾 `use_finmind`(需先做 Step 5)
- ❌ **TWSE 抓不到** → 可能是還沒收盤(15:30 後才有資料)/ 今日不交易 / 欄位變動,把 log 貼給 Claude

---

## 🚦 Step 5(選用):FinMind Token

只有 Goodinfo 一直被擋才需要。

1. 註冊 https://finmindtrade.com/
2. 會員中心找 **API Token** → 複製
3. GitHub Secrets 新增:

| Name | Value |
|------|-------|
| `FINMIND_TOKEN` | 那串 token |

4. Run workflow 時勾 `use_finmind`

---

## 🚦 Step 6:開啟自動排程

Step 4 確認真實資料 OK 後,什麼都不用做,**cron 自動跑**:
- 台北時間每週一至五 **15:30** 觸發(GitHub cron 可能延遲 5-30 分鐘)
- 失敗會自動在 repo 開 issue(label: `bug`, `auto-generated`)

> 💡 GitHub repo 連續 60 天無 commit 會自動停用 schedule,記得偶爾推一下。

---

## 🛠 本機跑(進階,選用)

```bash
git clone https://github.com/leegunahwa/stock-radar.git
cd stock-radar
git checkout main  # 或 claude/...

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest

# 跑單元測試(最快驗證)
pytest tests/ -v        # 應該 39 passed

# 端到端 mock(不打外網)
python -m src.main --mock --date 20260424

# 真實流程(需 .env 設好 credentials,參考 .env.example)
cp .env.example .env
# 編輯 .env
python -m src.main
```

---

## ❓ 遇到問題怎麼辦

把以下資訊貼給 Claude:
1. **這份 SETUP.md 的內容**(讓 Claude 知道整個 context)
2. **你卡在哪一步**(Step X)
3. **錯誤訊息 / 截圖**(Actions log 或本機 stdout)

### 常見問題

| 問題 | 原因 | 解法 |
|------|------|------|
| Actions 看不到 Daily Stock Scan | workflow 不在 main | 合併分支到 main |
| Sheet 沒寫入 | Service Account 沒被加為協作者 | 把 JSON 裡的 `client_email` 加到 Sheet 共用 |
| 信沒收到 | 用了 Gmail 登入密碼而非 App Password | 改用 App Password(16 碼) |
| TWSE 403 | TWSE 有頻率限制 | 看 retry log,通常重跑就 OK |
| Goodinfo 一直擋 | 反爬蟲偵測 | 切換到 FinMind(Step 5) |
| 跑很久才結束 | Goodinfo 5-8s 節流 × N 檔 | 正常,30 分鐘 timeout 內可完成 |

---

## 📂 完成階段

- ✅ Stage 1: 專案骨架
- ✅ Stage 2: 6 個 scrapers + FinMind 後援
- ✅ Stage 3: 三層 filter + 主流程
- ✅ Stage 3.5: 加入主力(三大法人)買超條件
- ✅ Stage 4: Google Sheet + SMTP + Workflow 完整化

39/39 單元測試 PASSED。

---

> 🎯 **建議路徑**:合併分支 → Step 1 (mock) → Step 2 (Sheet) → 跳過 Step 3 → Step 4 (真實) → Step 6 (自動)
