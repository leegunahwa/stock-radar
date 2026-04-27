"""寫入 Google Sheet 通知模組。

Stage 3:暫時 fallback 為「存 JSON 到 output/」,讓 main.py 可端到端跑通。
Stage 4:接上 gspread + Service Account,真正寫入 Google Sheet。

用環境變數判斷:若 ``GOOGLE_SERVICE_ACCOUNT_JSON`` 與 ``GOOGLE_SHEET_ID``
皆存在則嘗試真寫入(此邏輯於 Stage 4 完成);否則只存檔。
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


def write_results(candidates: list[dict[str, Any]], date: str) -> Path:
    """將候選股結果寫出。

    Stage 3 行為:存成 ``output/{date}.json``,並在 logger 提示。
    Stage 4 將擴充為真正寫入 Google Sheet。

    Args:
        candidates: 候選股列表(每個 dict 含 stock_id, name, score 等)。
        date: YYYYMMDD。

    Returns:
        實際寫出的 JSON 檔路徑。
    """
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
    logger.info(f"已寫出 {len(candidates)} 檔候選股 → {out_path}")

    if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_SHEET_ID"):
        logger.info("(Stage 4 將在此處寫入 Google Sheet)")

    return out_path
