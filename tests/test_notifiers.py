"""notifiers 單元測試 — 用 mock 驗證 Sheet / Email 路徑。

不打真實 Google API / SMTP,以 unittest.mock 驗證:
- 沒設 credentials 時只寫本機檔(JSON / HTML)
- 設了 credentials 時呼叫對應 client / SMTP
- 寫入失敗時不 raise(本機檔仍保留)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from src.notifiers import email_sender, gsheet


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def candidates() -> list[dict]:
    return [
        {
            "stock_id": "2330", "name": "台積電",
            "chip": {
                "net_buy_lots": 4000, "main_force_lots": 20000,
                "consecutive_days": 3, "ptt_mentions": 2,
            },
            "tech": {
                "price": 985, "ma5": 980, "ma10": 975, "ma20": 970,
                "gain_20d": 0.05,
            },
            "revenue": {"yoy": 25.5},
            "eps": {"eps": 12.5},
            "chip_score": 80, "tech_score": 70,
            "fundamental_score": 90, "score": 80.5,
        },
        {
            "stock_id": "2454", "name": "聯發科",
            "chip": {
                "net_buy_lots": 3000, "main_force_lots": 11500,
                "consecutive_days": 2, "ptt_mentions": 0,
            },
            "tech": {
                "price": 1120, "ma5": 1110, "ma10": 1105, "ma20": 1100,
                "gain_20d": 0.08,
            },
            "revenue": {"yoy": 12.0},
            "eps": {"eps": 18.0},
            "chip_score": 75, "tech_score": 65,
            "fundamental_score": 80, "score": 73.5,
        },
    ]


@pytest.fixture
def tmp_output(monkeypatch, tmp_path: Path) -> Path:
    """暫時把 OUTPUT_DIR 切到 tmp_path,測試結束自動清掉。"""
    monkeypatch.setattr(gsheet, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(email_sender, "OUTPUT_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _no_env(monkeypatch) -> None:
    """預設清掉所有相關 env,讓「無 credentials」變成預設行為。"""
    for k in [
        "GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON",
        "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT",
        "EMAIL_SMTP_USER", "EMAIL_SMTP_PASS", "NOTIFY_EMAIL_TO",
    ]:
        monkeypatch.delenv(k, raising=False)


# =============================================================================
# gsheet
# =============================================================================
def test_gsheet_no_credentials_writes_local_json(tmp_output, candidates) -> None:
    """無 credentials → 只寫 JSON,不嘗試 gspread。"""
    with mock.patch.object(gsheet, "_build_client") as mock_build:
        path = gsheet.write_results(candidates, "20260424")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["count"] == 2
    assert data["candidates"][0]["stock_id"] == "2330"
    mock_build.assert_not_called()


def test_gsheet_with_credentials_creates_worksheet(
    tmp_output, candidates, monkeypatch
) -> None:
    """有 credentials → 呼叫 gspread,新增 worksheet 並寫入 headers + rows。"""
    monkeypatch.setenv("GOOGLE_SHEET_ID", "fake-sheet-id")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')

    fake_ws = mock.MagicMock()
    fake_sheet = mock.MagicMock()
    # 第一次呼叫 worksheet 拋 WorksheetNotFound,觸發 add_worksheet
    fake_sheet.worksheet.side_effect = gsheet._WorksheetNotFound
    fake_sheet.add_worksheet.return_value = fake_ws
    fake_client = mock.MagicMock()
    fake_client.open_by_key.return_value = fake_sheet

    with mock.patch.object(gsheet, "_build_client", return_value=fake_client):
        gsheet.write_results(candidates, "20260424")

    # JSON 仍保留
    assert (tmp_output / "20260424.json").exists()
    # Sheet 路徑被觸發
    fake_client.open_by_key.assert_called_once_with("fake-sheet-id")
    fake_sheet.add_worksheet.assert_called_once()
    args, kwargs = fake_sheet.add_worksheet.call_args
    assert kwargs["title"] == "2026-04-24"
    fake_ws.update.assert_called_once()
    update_kwargs = fake_ws.update.call_args.kwargs
    rows = update_kwargs["values"]
    assert rows[0] == gsheet.HEADERS
    assert rows[1][1] == "2330"  # 第一檔 stock_id


def test_gsheet_existing_worksheet_is_overwritten(
    tmp_output, candidates, monkeypatch
) -> None:
    """同日重跑 → 現有 worksheet 會被 clear() 後重寫。"""
    monkeypatch.setenv("GOOGLE_SHEET_ID", "fake-sheet-id")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')

    fake_ws = mock.MagicMock()
    fake_sheet = mock.MagicMock()
    fake_sheet.worksheet.return_value = fake_ws
    fake_client = mock.MagicMock()
    fake_client.open_by_key.return_value = fake_sheet

    with mock.patch.object(gsheet, "_build_client", return_value=fake_client):
        gsheet.write_results(candidates, "20260424")

    fake_ws.clear.assert_called_once()
    fake_sheet.add_worksheet.assert_not_called()


def test_gsheet_failure_does_not_raise(tmp_output, candidates, monkeypatch) -> None:
    """gspread 寫入失敗 → log warning,不 raise,JSON 仍保留。"""
    monkeypatch.setenv("GOOGLE_SHEET_ID", "fake-sheet-id")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')

    with mock.patch.object(
        gsheet, "_build_client", side_effect=RuntimeError("API down")
    ):
        path = gsheet.write_results(candidates, "20260424")
    assert path.exists()  # JSON 仍存在


def test_build_row_shape(candidates) -> None:
    row = gsheet.build_row(1, candidates[0])
    assert len(row) == len(gsheet.HEADERS)
    assert row[0] == 1
    assert row[1] == "2330"
    assert row[2] == "台積電"


# =============================================================================
# email_sender
# =============================================================================
def test_email_no_credentials_writes_local_html(tmp_output, candidates) -> None:
    """無 credentials → 只寫 HTML,不嘗試 SMTP。"""
    with mock.patch("smtplib.SMTP") as mock_smtp:
        path = email_sender.send_report(candidates, "20260424")
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "2330" in html and "台積電" in html
    assert "投信買超" in html and "主力買超" in html
    mock_smtp.assert_not_called()


def test_email_with_credentials_calls_smtp(
    tmp_output, candidates, monkeypatch
) -> None:
    """有 credentials → 呼叫 SMTP starttls + login + send_message。"""
    monkeypatch.setenv("EMAIL_SMTP_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_SMTP_PASS", "secretpass")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "you@example.com")

    fake_server = mock.MagicMock()
    fake_smtp = mock.MagicMock()
    fake_smtp.__enter__.return_value = fake_server

    with mock.patch("smtplib.SMTP", return_value=fake_smtp) as mock_smtp_ctor:
        path = email_sender.send_report(candidates, "20260424")

    assert path.exists()
    mock_smtp_ctor.assert_called_once()
    fake_server.starttls.assert_called_once()
    fake_server.login.assert_called_once_with("me@example.com", "secretpass")
    fake_server.send_message.assert_called_once()
    sent_msg = fake_server.send_message.call_args.args[0]
    assert "[台股籌碼掃描]" in sent_msg["Subject"]
    assert sent_msg["To"] == "you@example.com"


def test_email_failure_does_not_raise(tmp_output, candidates, monkeypatch) -> None:
    """SMTP 失敗 → log warning,不 raise,HTML 仍保留。"""
    monkeypatch.setenv("EMAIL_SMTP_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_SMTP_PASS", "secretpass")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "you@example.com")

    with mock.patch("smtplib.SMTP", side_effect=ConnectionError("boom")):
        path = email_sender.send_report(candidates, "20260424")
    assert path.exists()
