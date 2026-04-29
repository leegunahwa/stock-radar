// update by Leo 2026-04-28 & Apps Script Web App 後端：抓 GitHub Pages JSON + CacheService

/**
 * GitHub Pages 上的 JSON 基底 URL。
 * 部署前請改成你自己的 GitHub Pages URL。
 */
var BASE_URL = 'https://<YOUR_GITHUB_USERNAME>.github.io/stock-radar';

/** CacheService TTL（秒），5 分鐘 */
var CACHE_TTL = 300;

/**
 * Web App 進入點：回傳 HTML 頁面。
 */
function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('台股籌碼掃描雷達')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * 供前端呼叫：取得可用日期清單。
 * @return {string[]} 日期陣列，新到舊，例如 ["2026-04-28","2026-04-25"]
 */
function getDates() {
  var cacheKey = 'dates_json';
  var cache = CacheService.getScriptCache();
  var cached = cache.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }

  var url = BASE_URL + '/dates.json';
  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) {
    return [];
  }
  var data = resp.getContentText('UTF-8');
  cache.put(cacheKey, data, CACHE_TTL);
  return JSON.parse(data);
}

/**
 * 供前端呼叫：取得指定日期的掃描結果。
 * @param {string|null} date - 日期字串如 "2026-04-28"；null 或空字串表示最新。
 * @return {object} 掃描結果 JSON 物件
 */
function getScanData(date) {
  var cacheKey = date ? 'scan_' + date : 'scan_latest';
  var cache = CacheService.getScriptCache();
  var cached = cache.get(cacheKey);
  if (cached) {
    return JSON.parse(cached);
  }

  var url;
  if (date) {
    url = BASE_URL + '/history/' + date + '.json';
  } else {
    url = BASE_URL + '/data.json';
  }

  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) {
    return { error: '無法取得資料 (' + resp.getResponseCode() + ')', stocks: [] };
  }
  var data = resp.getContentText('UTF-8');
  cache.put(cacheKey, data, CACHE_TTL);
  return JSON.parse(data);
}
