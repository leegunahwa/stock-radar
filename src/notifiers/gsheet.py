"""寫入 Google Sheet 通知模組。

行為:
1. 一律先寫一份 JSON 到 ``output/{date}.json`` 作為本機備份。
2. 若環境變數 ``GOOGLE_SHEET_ID`` 與 ``GOOGLE_SERVICE_ACCOUNT_JSON``
   皆存在,則進一步透過 ``gspread`` 寫入 Google Sheet。
   每日新增一個 worksheet(名稱為 ``YYYY-MM-DD``)。
3. Google Sheet 寫入失敗時記錄 warning,不 raise(本機 JSON 仍保留)。

對外介面:
- ``write_results(candidates, date)`` — 模組級函式。
- ``GoogleSheetNotifier`` — 物件導向版本,可注入測試用 client。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("notifier.gsheet")

OUTPUT_DIR = Path("output")

# 延遲 / 容錯式匯入:有些環境(包含部分 sandbox)gspread 的依賴鏈
# (cryptography → cffi)在 import 時就會 panic,故此處保護一下。
# 真實生產環境會正常匯入。
try:
    import gspread as _gspread
    _WorksheetNotFound: type[BaseException] = _gspread.WorksheetNotFound
    _GSPREAD_AVAILABLE = True
except BaseException as _exc:  # noqa: BLE001  (含 pyo3 PanicException)
    _gspread = None  # type: ignore[assignment]

    class _WorksheetNotFound(Exception):  # type: ignore[no-redef]
        """gspread 不可用時的 placeholder。"""

    _GSPREAD_AVAILABLE = False
    logger.debug(f"gspread 匯入失敗(將跳過 Sheet 寫入): {_exc}")

# Google Sheet 的表頭
HEADERS: list[str] = [
    "排名",
    "股票代號",
    "股票名稱",
    "現價",
    "投信買超(張)",
    "主力買超(張)",
    "連續買超(天)",
    "近20日漲幅",
    "均線糾結度",
    "月營收年增(%)",
    "季EPS",
    "PTT提及",
    "籌碼分",
    "技術分",
    "基本面分",
    "總分",
]

# Google Sheets API scope
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


# ----------------------------------------------------------------------
# 物件導向:可注入 client 方便測試
# ----------------------------------------------------------------------
class GoogleSheetNotifier:
    """封裝 gspread 客戶端與寫入邏輯。"""

    def __init__(
        self,
        sheet_id: str,
        service_account_json: str,
        client: Any = None,
    ) -> None:
        self.sheet_id = sheet_id
        self.service_account_json = service_account_json
        self._client = client  # 測試時可注入
        self._sheet = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client(self.service_account_json)
        return self._client

    @property
    def sheet(self) -> Any:
        if self._sheet is None:
            self._sheet = self.client.open_by_key(self.sheet_id)
        return self._sheet

    # ------------------------------------------------------------------
    def write_results(self, candidates: list[dict[str, Any]], date: str) -> None:
        """新增一個 worksheet 並寫入候選股清單。"""
        ws_name = _date_to_ws_name(date)
        try:
            ws = self.sheet.worksheet(ws_name)
            ws.clear()  # 同日重跑時清空
            logger.info(f"覆寫既有 worksheet: {ws_name}")
        except _WorksheetNotFound:
            ws = self.sheet.add_worksheet(
                title=ws_name, rows=max(100, len(candidates) + 5), cols=len(HEADERS) + 2
            )
            logger.info(f"新增 worksheet: {ws_name}")

        rows = [HEADERS] + [build_row(i, c) for i, c in enumerate(candidates, 1)]
        ws.update(range_name="A1", values=rows)
        logger.info(
            f"已寫入 Google Sheet: {ws_name}({len(candidates)} 檔)"
        )


# ----------------------------------------------------------------------
# 工具函式
# ----------------------------------------------------------------------
def _date_to_ws_name(date: str) -> str:
    """``20260424`` → ``2026-04-24``;其他格式維持原樣。"""
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return date


def _build_client(service_account_json: str) -> Any:
    """根據 service account JSON 字串建立 gspread client。"""
    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _fmt(value: Any, default: str = "-") -> Any:
    if value is None:
        return default
    return value


def _round(value: Any, digits: int = 2, default: str = "-") -> Any:
    """安全 round;非數字回 default。"""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return default


def build_row(rank: int, c: dict[str, Any]) -> list[Any]:
    """把單一候選股 dict 攤平成 Sheet 一列。"""
    tech = c.get("tech") or {}
    chip = c.get("chip") or {}
    revenue = c.get("revenue") or {}
    eps = c.get("eps") or {}

    inv_lots = chip.get("net_buy_lots", c.get("net_buy_lots"))
    main_lots = chip.get("main_force_lots", c.get("main_force_lots"))

    # 均線糾結度 = max(MA5,MA10,MA20)/min - 1
    ma_vals = [tech.get(k) for k in ("ma5", "ma10", "ma20")]
    ma_vals = [v for v in ma_vals if isinstance(v, (int, float)) and v > 0]
    if len(ma_vals) >= 3:
        glued = max(ma_vals) / min(ma_vals) - 1
    else:
        glued = None

    return [
        rank,
        c.get("stock_id", ""),
        c.get("name", ""),
        _fmt(tech.get("price")),
        _round(inv_lots, 0),
        _round(main_lots, 0),
        chip.get("consecutive_days", "-"),
        f"{_round(tech.get('gain_20d'), 4)}",
        f"{_round(glued, 4)}",
        _round(revenue.get("yoy")),
        _round(eps.get("eps")),
        chip.get("ptt_mentions", 0),
        _round(c.get("chip_score")),
        _round(c.get("tech_score")),
        _round(c.get("fundamental_score")),
        _round(c.get("score")),
    ]


def _save_json(candidates: list[dict[str, Any]], date: str) -> Path:
    """把結果存成本機 JSON(備份用)。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.json"
    payload = {
        "date": date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(candidates),
        "candidates": candidates,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out_path


def _has_credentials() -> bool:
    return bool(
        os.getenv("GOOGLE_SHEET_ID") and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    )


# ----------------------------------------------------------------------
# 對外:模組級函式
# ----------------------------------------------------------------------
def write_results(candidates: list[dict[str, Any]], date: str) -> Path:
    """寫出候選股結果。

    1. 一律先存 ``output/{date}.json``。
    2. 若 credentials 齊全,額外寫入 Google Sheet。
    3. Google Sheet 失敗不影響回傳值(仍回傳 JSON 路徑)。
    """
    out_path = _save_json(candidates, date)
    logger.info(f"已寫出 {len(candidates)} 檔候選股 → {out_path}")

    if not _has_credentials():
        logger.info("未設定 Google Sheet credentials,僅寫入本機 JSON")
        return out_path

    try:
        notifier = GoogleSheetNotifier(
            sheet_id=os.environ["GOOGLE_SHEET_ID"],
            service_account_json=os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        )
        notifier.write_results(candidates, date)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Google Sheet 寫入失敗(本機 JSON 已保留): {exc}"
        )

    return out_path
