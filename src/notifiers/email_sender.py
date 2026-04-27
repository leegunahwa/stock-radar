"""Email 寄送模組。

Stage 3:暫時 fallback 為「把 HTML 報表存到 output/」,讓 main.py 可端到端跑通。
Stage 4:接上 SMTP 真正寄送。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("notifier.email")

OUTPUT_DIR = Path("output")


def send_report(candidates: list[dict[str, Any]], date: str) -> Path:
    """產出 Email 報表。

    Stage 3 行為:把 HTML 寫到 ``output/{date}.html``,並在 logger 提示。
    Stage 4 將擴充為真正透過 SMTP 寄送。

    Args:
        candidates: 候選股列表。
        date: YYYYMMDD。

    Returns:
        實際寫出的 HTML 檔路徑。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.html"

    html = _build_html(candidates, date)
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"已寫出 HTML 報表 → {out_path}")

    if os.getenv("EMAIL_SMTP_USER") and os.getenv("NOTIFY_EMAIL_TO"):
        logger.info("(Stage 4 將在此處透過 SMTP 寄送)")

    return out_path


def _build_html(candidates: list[dict[str, Any]], date: str) -> str:
    """組 HTML 內容(Stage 4 會增強樣式)。"""
    rows_html = ""
    for i, c in enumerate(candidates, 1):
        tech = c.get("tech") or {}
        chip = c.get("chip") or {}
        inv_lots = chip.get("net_buy_lots", c.get("net_buy_lots", "-"))
        main_lots = chip.get("main_force_lots", c.get("main_force_lots", "-"))
        rows_html += f"""
            <tr>
              <td>{i}</td>
              <td><b>{c.get('stock_id', '')}</b></td>
              <td>{c.get('name', '')}</td>
              <td>{tech.get('price', '-')}</td>
              <td>{_fmt_lots(inv_lots)}</td>
              <td>{_fmt_lots(main_lots)}</td>
              <td>{c.get('score', '-')}</td>
            </tr>"""

    return f"""<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>台股籌碼掃描 {date}</title></head>
<body style="font-family: '微軟正黑體', 'Microsoft JhengHei', sans-serif;">
  <h2>📈 台股籌碼掃描報告 - {date}</h2>
  <p>本日共篩出 <b>{len(candidates)}</b> 檔候選股</p>
  <table border="1" cellpadding="8" style="border-collapse: collapse;">
    <thead style="background: #f0f0f0;">
      <tr>
        <th>排名</th><th>代號</th><th>名稱</th>
        <th>現價</th><th>投信買超(張)</th><th>主力買超(張)</th><th>總分</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  <hr>
  <p style="color: #888; font-size: 12px;">
    ⚠️ 本資訊純為籌碼分析整理,不構成投資建議。
  </p>
</body>
</html>
"""


def _fmt_lots(value: Any) -> str:
    """格式化「張」數值;非數字維持原樣。"""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)
