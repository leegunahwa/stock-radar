"""Email 寄送模組。

行為:
1. 一律先把 HTML 報表寫到 ``output/{date}.html`` 作為本機備份。
2. 若 SMTP 環境變數齊全,則進一步透過 ``smtplib`` 寄出。
3. 寄送失敗時記錄 warning,不 raise(本機 HTML 仍保留)。

需要的環境變數:
- ``EMAIL_SMTP_HOST``(預設 ``smtp.gmail.com``)
- ``EMAIL_SMTP_PORT``(預設 ``587``)
- ``EMAIL_SMTP_USER``、``EMAIL_SMTP_PASS``、``NOTIFY_EMAIL_TO``
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("notifier.email")

OUTPUT_DIR = Path("output")


# ----------------------------------------------------------------------
class EmailSender:
    """SMTP 寄送器。"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        user: str,
        password: str,
        to: str,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.user = user
        self.password = password
        self.to = to

    def send(self, subject: str, html: str) -> None:
        """送出單封 HTML mail(內含 plaintext fallback)。"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.to
        # 純文字 fallback(避免某些 client 看不到 HTML)
        msg.attach(MIMEText("請以 HTML 模式檢視本封郵件。", "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.user, self.password)
            server.send_message(msg)


# ----------------------------------------------------------------------
# HTML 構築
# ----------------------------------------------------------------------
def _fmt_lots(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _build_html(candidates: list[dict[str, Any]], date: str) -> str:
    """產出 HTML 報表內容。"""
    sheet_url = (
        f"https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}"
        if os.getenv("GOOGLE_SHEET_ID")
        else None
    )

    rows_html = ""
    for i, c in enumerate(candidates, 1):
        tech = c.get("tech") or {}
        chip = c.get("chip") or {}
        revenue = c.get("revenue") or {}
        eps = c.get("eps") or {}
        rows_html += f"""
            <tr>
              <td style="text-align:center">{i}</td>
              <td><b>{c.get('stock_id', '')}</b></td>
              <td>{c.get('name', '')}</td>
              <td style="text-align:right">{_fmt_num(tech.get('price'))}</td>
              <td style="text-align:right">{_fmt_lots(chip.get('net_buy_lots'))}</td>
              <td style="text-align:right">{_fmt_lots(chip.get('main_force_lots'))}</td>
              <td style="text-align:right">{_fmt_pct(tech.get('gain_20d'))}</td>
              <td style="text-align:right">{_fmt_num(revenue.get('yoy'))}%</td>
              <td style="text-align:right">{_fmt_num(eps.get('eps'))}</td>
              <td style="text-align:center"><b>{_fmt_num(c.get('score'))}</b></td>
            </tr>"""

    sheet_link = (
        f'<p><a href="{sheet_url}">查看完整 Google Sheet →</a></p>'
        if sheet_url
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>台股籌碼掃描 {date}</title></head>
<body style="font-family: '微軟正黑體', 'Microsoft JhengHei', sans-serif;">
  <h2>📈 台股籌碼掃描報告 - {date}</h2>
  <p>本日共篩出 <b>{len(candidates)}</b> 檔候選股</p>
  <table border="1" cellpadding="8" style="border-collapse: collapse; min-width: 760px;">
    <thead style="background: #f0f0f0;">
      <tr>
        <th>排名</th><th>代號</th><th>名稱</th><th>現價</th>
        <th>投信買超(張)</th><th>主力買超(張)</th>
        <th>近20日漲幅</th><th>月營收YoY</th><th>季EPS</th>
        <th>總分</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  {sheet_link}
  <hr>
  <p style="color: #888; font-size: 12px;">
    ⚠️ 本資訊純為籌碼分析整理,不構成投資建議。
  </p>
</body>
</html>
"""


# ----------------------------------------------------------------------
def _save_html(html: str, date: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _has_credentials() -> bool:
    return bool(
        os.getenv("EMAIL_SMTP_USER")
        and os.getenv("EMAIL_SMTP_PASS")
        and os.getenv("NOTIFY_EMAIL_TO")
    )


# ----------------------------------------------------------------------
# 對外:模組級函式
# ----------------------------------------------------------------------
def send_report(candidates: list[dict[str, Any]], date: str) -> Path:
    """產出 + 寄送 Email 報表。

    1. 一律存 ``output/{date}.html``。
    2. 若 SMTP credentials 齊全,則寄送 Email。
    3. 寄送失敗只記 warning,不 raise(本機 HTML 仍保留)。
    """
    html = _build_html(candidates, date)
    out_path = _save_html(html, date)
    logger.info(f"已寫出 HTML 報表 → {out_path}")

    if not _has_credentials():
        logger.info("未設定 SMTP credentials,僅寫入本機 HTML")
        return out_path

    try:
        sender = EmailSender(
            smtp_host=os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "587")),
            user=os.environ["EMAIL_SMTP_USER"],
            password=os.environ["EMAIL_SMTP_PASS"],
            to=os.environ["NOTIFY_EMAIL_TO"],
        )
        subject = f"[台股籌碼掃描] {date} - 共 {len(candidates)} 檔候選"
        sender.send(subject, html)
        logger.info(
            f"已寄送 Email → {os.environ['NOTIFY_EMAIL_TO']}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Email 寄送失敗(本機 HTML 已保留): {exc}"
        )

    return out_path
