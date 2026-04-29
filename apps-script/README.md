# Apps Script Web App 部署指南

## 前置條件

- Google 帳號
- 本專案已啟用 GitHub Pages（`dist/` 目錄可透過 `https://<username>.github.io/stock-radar/data.json` 存取）

## 部署步驟

### 1. 建立 Apps Script 專案

1. 前往 [script.google.com](https://script.google.com/)
2. 點擊「新專案」
3. 將預設的 `程式碼.gs` 內容替換為 `Code.gs` 的內容
4. 點擊「+」新增 HTML 檔案，命名為 `Index`，貼入 `Index.html` 的內容

### 2. 修改 BASE_URL

在 `Code.gs` 第 8 行，將 `BASE_URL` 改為你的 GitHub Pages URL：

```javascript
var BASE_URL = 'https://你的帳號.github.io/stock-radar';
```

### 3. 部署為 Web App

1. 點擊右上角「部署」→「新增部署」
2. 類型選「網頁應用程式」
3. 設定：
   - **說明**：台股籌碼掃描雷達
   - **以下身分執行**：我自己
   - **誰可以存取**：
     - 只有自己 → 選「只有我自己」
     - 想分享給其他人 → 選「所有人」
4. 點擊「部署」
5. 複製產生的 Web App URL

### 4. 開始使用

在瀏覽器開啟 Web App URL 即可看到掃描結果。

## 功能說明

- **自動載入**：開啟頁面自動載入最新掃描結果
- **切換日期**：右上角下拉選單可切換近 7 個交易日的歷史資料
- **表格功能**：排序（點欄位標頭）、搜尋（左上搜尋框）、分頁、欄位顯示/隱藏
- **快取機制**：CacheService 快取 5 分鐘，避免重複請求 GitHub Pages

## 注意事項

- GitHub Pages 有 ~10 分鐘 CDN 快取，掃描完成後可能需要等待才看到最新資料
- Apps Script 每日 UrlFetchApp 配額為 20,000 次，正常使用不會超過
- CacheService 單一 key 上限 100KB，5 檔候選股的 JSON 遠小於此限制
