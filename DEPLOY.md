# 部署指南（DEPLOY.md）

<!-- update by Leo 2026-04-28 & 一步步部署「Python 爬蟲 → JSON → Apps Script Web App」架構 -->

本文件將引導你完成從零到上線的完整部署流程。

---

## 總覽

```
GitHub Actions (cron 15:30 TWD)
    ↓ python -m src.main --output dist/data.json
    ↓ git commit + push
    ↓ deploy to GitHub Pages
GitHub Pages
    ↓ https://<username>.github.io/stock-radar/data.json
Apps Script Web App
    ↓ UrlFetchApp 抓 JSON → 渲染表格
瀏覽器
```

---

## Step 1：GitHub 設定

### 1.1 啟用 GitHub Pages

1. 進入 repo → **Settings** → **Pages**
2. **Source** 選 **GitHub Actions**（不是 Deploy from a branch）
3. 儲存

### 1.2 設定 GitHub Secrets（選用）

若要使用 FinMind API 取代 Goodinfo：

| Name | Value |
|------|-------|
| `FINMIND_TOKEN` | 你的 FinMind API Token（[註冊](https://finmindtrade.com/)） |

> 其他 secrets（Google Sheet、SMTP）已不再需要。

### 1.3 確認 Workflow 權限

1. **Settings** → **Actions** → **General**
2. **Workflow permissions** 選 **Read and write permissions**
3. 勾選 **Allow GitHub Actions to create and approve pull requests**（非必要但建議）

---

## Step 2：首次測試

### 2.1 手動觸發 Workflow

1. 進入 repo → **Actions** → **Scrape & Publish JSON**
2. 點擊 **Run workflow**
3. 勾選 **mock**（用假資料測試，不打外網）
4. 點擊 **Run workflow**

### 2.2 檢查結果

- Workflow 成功後，進入 **Code** 頁面，確認 `dist/` 目錄出現：
  - `data.json`
  - `dates.json`
  - `history/YYYY-MM-DD.json`
- 進入 **Settings** → **Pages**，確認 GitHub Pages 已部署
- 開啟 `https://<username>.github.io/stock-radar/data.json` 確認能看到 JSON

### 2.3 測試真實資料

1. 再次手動觸發 workflow，這次**不勾** mock
2. 等待完成後，確認 `data.json` 內容為真實掃描結果

---

## Step 3：部署 Apps Script Web App

### 3.1 建立 Apps Script 專案

1. 前往 [script.google.com](https://script.google.com/)
2. 點擊「新專案」
3. 重新命名為「台股籌碼掃描雷達」

### 3.2 貼入程式碼

1. 將預設的 `程式碼.gs` 內容**全部替換**為 `apps-script/Code.gs` 的內容
2. **修改第 8 行** `BASE_URL`：
   ```javascript
   var BASE_URL = 'https://<你的帳號>.github.io/stock-radar';
   ```
3. 點擊左側「+」→「HTML」→ 命名為 `Index`
4. 貼入 `apps-script/Index.html` 的完整內容

### 3.3 部署

1. 點擊右上角「**部署**」→「**新增部署**」
2. 左側齒輪選「**網頁應用程式**」
3. 設定：
   - **說明**：v1.0
   - **以下身分執行**：我自己
   - **誰可以存取**：依需求選擇
     - 只有自己 → 「只有我自己」
     - 要分享 → 「所有人」
4. 點擊「**部署**」
5. 第一次會要求授權，點「審查權限」→ 選帳號 → 「允許」
6. 複製產生的 **Web App URL**

### 3.4 驗證

在瀏覽器開啟 Web App URL，應該看到：
- 掃描日期 + 更新時間
- 篩選條件 badge
- 候選股表格（支援排序、搜尋）
- 右上角可切換歷史日期

---

## Step 4：日常運作

一切就緒後，系統每個交易日 15:30 自動：
1. GitHub Actions 跑 Python 爬蟲
2. 產出 `dist/data.json` + 歷史快照
3. Commit & push 回 main
4. 部署到 GitHub Pages
5. Apps Script Web App 自動讀取最新 JSON

**你只需要開啟 Web App URL 看結果。**

---

## 故障排除

### Workflow 失敗

1. 進入 Actions → 點選失敗的 run → 看 log
2. 常見原因：
   - Goodinfo 反爬蟲（考慮加 `--use-finmind`）
   - 網路逾時（通常重跑即可）
   - GitHub Pages 尚未啟用

### Web App 顯示錯誤

1. 確認 `BASE_URL` 正確（結尾不要有 `/`）
2. 在瀏覽器直接開啟 `BASE_URL + '/data.json'` 確認能存取
3. Apps Script 編輯器 → 「執行」→ 手動跑 `getDates()` 看有無錯誤

### 資料延遲

- GitHub Pages CDN 快取：~10 分鐘
- Apps Script CacheService：5 分鐘
- 最多等 15 分鐘即可看到最新資料

---

## 更新 Web App

修改 `Code.gs` 或 `Index.html` 後：

1. 在 Apps Script 編輯器點「**部署**」→「**管理部署作業**」
2. 點鉛筆圖示 → 版本選「**新版本**」
3. 點「**部署**」

> 注意：URL 不變，但新版本需要手動發布才生效。
