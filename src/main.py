"""主流程入口。

執行順序:
1. 判斷是否為交易日
2. 籌碼面初篩(投信買賣超 + 分點)
3. 對候選股逐一抓技術面 + 基本面
4. 套用三層 filter 並評分
5. 排序取 top N,寫入 Google Sheet 並寄送 Email

實作將於 Stage 3 完成。
"""

from __future__ import annotations

from src.utils.logger import setup_logger


def main() -> None:
    """主流程進入點(Stage 3 將完整實作)。"""
    logger = setup_logger()
    logger.info("Stock Radar 主流程尚未實作,請見 SPEC.md Stage 3。")


if __name__ == "__main__":
    main()
