"""台股每日籌碼掃描 — 主流程。

執行順序:
1. 判斷是否為交易日(非交易日直接結束)
2. 籌碼面初篩(投信買賣超 → 候選股 50-100 檔)
3. 對候選股逐一抓技術面 + 基本面
4. 套用三層 filter 並評分
5. 排序取 top N,寫入 output / Google Sheet / Email

執行方式:
    python -m src.main                  # 真實流程,抓今日資料
    python -m src.main --date 20260424  # 指定日期
    python -m src.main --mock           # 用內建 mock 資料端到端驗證
    python -m src.main --use-finmind    # 改用 FinMind 取代 Goodinfo
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

import pandas as pd

from src.filters import ChipFilter, FundamentalFilter, TechFilter
from src.notifiers import email_sender, gsheet
from src.scrapers import histock, twse_fund
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.utils.trading_calendar import (
    is_trading_day,
    previous_trading_day,
    recent_trading_days,
)

logger = setup_logger("stock_radar")


# ----------------------------------------------------------------------
# 評分組合
# ----------------------------------------------------------------------
def calculate_total_score(
    chip_score: float,
    tech_score: float,
    fundamental_score: float,
    weights: dict[str, float],
) -> float:
    """依權重組合三項分數。"""
    total = (
        chip_score * weights.get("chip_weight", 0.4)
        + tech_score * weights.get("tech_weight", 0.3)
        + fundamental_score * weights.get("fundamental_weight", 0.3)
    )
    return round(total, 2)


# ----------------------------------------------------------------------
# Enrichment:對單一候選股抓技術面 + 基本面
# ----------------------------------------------------------------------
def enrich_stock(
    stock_id: str,
    use_finmind: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """抓取單一個股的技術面 + 基本面資料。"""
    tech = histock.get_technical(stock_id)

    if use_finmind:
        from src.scrapers import finmind

        revenue = finmind.get_monthly_revenue(stock_id)
        eps = finmind.get_quarterly_eps(stock_id)
    else:
        from src.scrapers import goodinfo

        revenue = goodinfo.get_monthly_revenue(stock_id)
        eps = goodinfo.get_quarterly_eps(stock_id)

    return tech, revenue, eps


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def run(
    date: str | None = None,
    use_finmind: bool = False,
    mock: bool = False,
) -> list[dict[str, Any]]:
    """執行完整掃描流程。

    Args:
        date: YYYYMMDD;為 None 時自動取今日(非交易日則取前一個交易日)。
        use_finmind: 改用 FinMind 取代 Goodinfo。
        mock: 用內建 mock 資料測試端到端流程,不打外部網路。

    Returns:
        最終候選股清單(含 chip / tech / revenue / eps / 各分數 / 總分)。
    """
    config = load_config()
    weights = config.get("scoring", {})
    output_cfg = config.get("output", {})
    top_n = int(output_cfg.get("top_n", 5))
    min_total = float(output_cfg.get("min_total_score", 60))
    exclude_stocks = config.get("exclude_stocks", []) or []

    today = date or datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        prev = previous_trading_day(today)
        logger.info(f"{today} 非交易日,改用前一個交易日 {prev}")
        today = prev

    # ------------------------------------------------------------------
    # Step 1: 籌碼面初篩
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info(f"Step 1: 抓取投信買賣超({today})")
    if mock:
        fund_today, fund_history = _mock_fund_data(today)
    else:
        fund_today = twse_fund.get_investment_trust_buy(today)
        fund_history = _fetch_history_fund(
            today, days=int(config.get("chip_filter", {}).get("consecutive_buy_days", 1))
        )

    chip_filter = ChipFilter(
        config=config.get("chip_filter", {}),
        exclude_stocks=exclude_stocks,
    )
    candidates_df = chip_filter.initial_screening(
        fund_df_today=fund_today,
        fund_dfs_history=fund_history,
    )
    logger.info(f"籌碼面初篩後剩 {len(candidates_df)} 檔")
    if candidates_df.empty:
        logger.info("沒有符合條件的標的,流程結束")
        return []

    # ------------------------------------------------------------------
    # Step 2: 抓技術面 + 基本面
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info(f"Step 2: 抓取候選股技術面 + 基本面(共 {len(candidates_df)} 檔)")
    tech_filter = TechFilter(config.get("tech_filter", {}))
    fund_filter = FundamentalFilter(config.get("fundamental_filter", {}))

    enriched: list[dict[str, Any]] = []
    for _, row in candidates_df.iterrows():
        stock_id = str(row["stock_id"])
        try:
            if mock:
                tech, revenue, eps = _mock_stock_detail(stock_id)
            else:
                tech, revenue, eps = enrich_stock(stock_id, use_finmind=use_finmind)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{stock_id} 抓取失敗,略過: {exc}")
            continue

        enriched.append(
            {
                "stock_id": stock_id,
                "name": row["name"],
                "chip": row.to_dict(),
                "tech": tech,
                "revenue": revenue,
                "eps": eps,
            }
        )

    # ------------------------------------------------------------------
    # Step 3: 套用 tech / fundamental filter,計算總分
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Step 3: 技術面 + 基本面篩選與評分")
    final: list[dict[str, Any]] = []
    for stock in enriched:
        if not tech_filter.is_low_basis(stock["tech"]):
            logger.debug(f"  {stock['stock_id']} 技術面未過")
            continue
        if not fund_filter.is_healthy(stock["revenue"], stock["eps"]):
            logger.debug(f"  {stock['stock_id']} 基本面未過")
            continue

        chip_s = float(stock["chip"].get("chip_score", 0))
        tech_s = tech_filter.score(stock["tech"])
        fund_s = fund_filter.score(stock["revenue"], stock["eps"])
        total = calculate_total_score(chip_s, tech_s, fund_s, weights)

        if total < min_total:
            logger.debug(
                f"  {stock['stock_id']} 總分 {total} < {min_total},略過"
            )
            continue

        final.append(
            {
                **stock,
                "chip_score": chip_s,
                "tech_score": tech_s,
                "fundamental_score": fund_s,
                "score": total,
            }
        )

    final.sort(key=lambda x: x["score"], reverse=True)
    top = final[:top_n]
    logger.info(f"最終候選 {len(final)} 檔,輸出前 {len(top)} 檔")

    # ------------------------------------------------------------------
    # Step 4: 輸出
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Step 4: 寫入結果")
    if top:
        gsheet.write_results(top, date=today)
        email_sender.send_report(top, date=today)

    # 簡短摘要
    for i, c in enumerate(top, 1):
        tech = c["tech"] or {}
        logger.info(
            f"  #{i} {c['stock_id']} {c['name']} "
            f"price={tech.get('price')} score={c['score']} "
            f"(chip={c['chip_score']} tech={c['tech_score']} fund={c['fundamental_score']})"
        )

    return top


# ----------------------------------------------------------------------
# 歷史資料抓取輔助
# ----------------------------------------------------------------------
def _fetch_history_fund(date: str, days: int) -> list[pd.DataFrame]:
    """抓 date 之前(不含 date)共 days-1 個交易日的 T86。"""
    if days <= 1:
        return []
    history_days = recent_trading_days(date, days)
    history_days = [d for d in history_days if d != date]
    out: list[pd.DataFrame] = []
    for d in history_days:
        out.append(twse_fund.get_investment_trust_buy(d))
    return out


# ----------------------------------------------------------------------
# Mock 資料(端到端驗證用,不打外部網路)
# ----------------------------------------------------------------------
def _mock_fund_data(date: str) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """產生 mock 投信買賣超資料(8 檔股票)。"""
    today_data = [
        # stock_id, name, buy(股), sell(股), net_buy(股)
        ("2330", "台積電", 5_000_000, 1_000_000, 4_000_000),
        ("2454", "聯發科", 3_500_000, 500_000, 3_000_000),
        ("2317", "鴻海", 2_500_000, 500_000, 2_000_000),
        ("3711", "日月光投控", 1_800_000, 300_000, 1_500_000),
        ("2891", "中信金", 1_200_000, 200_000, 1_000_000),
        ("2603", "長榮", 800_000, 50_000, 750_000),  # 已大漲(技術面會擋)
        ("0050", "元大台灣50", 9_000_000, 0, 9_000_000),  # exclude_stocks 中
        ("9999", "虧損股", 1_500_000, 200_000, 1_300_000),  # 基本面會擋
    ]
    today_df = pd.DataFrame(
        today_data, columns=["stock_id", "name", "buy", "sell", "net_buy"]
    )

    # 歷史:大部分股票連續買超,2603 中斷
    history_df = today_df.copy()
    history_df.loc[history_df["stock_id"] == "2603", "net_buy"] = -100_000
    return today_df, [history_df, history_df]


def _mock_stock_detail(
    stock_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """為 mock 模式提供假的技術面 + 基本面資料。"""
    profiles = {
        "2330": {
            "tech": {
                "price": 985, "change": 5, "ma5": 980, "ma10": 975, "ma20": 970,
                "ma60": 950, "boll_upper": 1010, "boll_mid": 970,
                "boll_lower": 930, "gain_20d": 0.05,
            },
            "revenue": {"month": "2026/03", "revenue": 250000, "yoy": 25.5,
                        "mom": 8.0, "ytd_revenue": 720000, "ytd_yoy": 22.0},
            "eps": {"quarter": "2025Q4", "eps": 12.5, "yoy": 30,
                    "ytd_eps": 45.0, "ytd_yoy": 28},
        },
        "2454": {
            "tech": {
                "price": 1120, "change": 10, "ma5": 1110, "ma10": 1105, "ma20": 1100,
                "ma60": 1080, "boll_upper": 1180, "boll_mid": 1100,
                "boll_lower": 1020, "gain_20d": 0.08,
            },
            "revenue": {"month": "2026/03", "revenue": 50000, "yoy": 12.0,
                        "mom": 5.0, "ytd_revenue": 145000, "ytd_yoy": 10.5},
            "eps": {"quarter": "2025Q4", "eps": 18.0, "yoy": 22,
                    "ytd_eps": 65.0, "ytd_yoy": 20},
        },
        "2317": {
            "tech": {
                "price": 215, "change": 1, "ma5": 213, "ma10": 212, "ma20": 210,
                "ma60": 200, "boll_upper": 230, "boll_mid": 210,
                "boll_lower": 190, "gain_20d": 0.04,
            },
            "revenue": {"month": "2026/03", "revenue": 600000, "yoy": 8.0,
                        "mom": 12.0, "ytd_revenue": 1700000, "ytd_yoy": 5.5},
            "eps": {"quarter": "2025Q4", "eps": 3.2, "yoy": 15,
                    "ytd_eps": 12.5, "ytd_yoy": 12},
        },
        "3711": {
            "tech": {
                "price": 168, "change": 2, "ma5": 165, "ma10": 164, "ma20": 162,
                "ma60": 155, "boll_upper": 180, "boll_mid": 165,
                "boll_lower": 150, "gain_20d": 0.06,
            },
            "revenue": {"month": "2026/03", "revenue": 60000, "yoy": 5.0,
                        "mom": 3.0, "ytd_revenue": 175000, "ytd_yoy": 4.0},
            "eps": {"quarter": "2025Q4", "eps": 2.5, "yoy": 10,
                    "ytd_eps": 9.5, "ytd_yoy": 8},
        },
        "2891": {
            "tech": {
                "price": 39.5, "change": 0.1, "ma5": 39, "ma10": 38.8, "ma20": 38.5,
                "ma60": 37, "boll_upper": 42, "boll_mid": 38.5,
                "boll_lower": 35, "gain_20d": 0.02,
            },
            "revenue": {"month": "2026/03", "revenue": 25000, "yoy": 2.0,
                        "mom": 1.5, "ytd_revenue": 72000, "ytd_yoy": 1.5},
            "eps": {"quarter": "2025Q4", "eps": 0.8, "yoy": 5,
                    "ytd_eps": 3.0, "ytd_yoy": 4},
        },
        # 已大漲(20 日漲幅 25%,會被技術面擋)
        "2603": {
            "tech": {
                "price": 220, "change": 8, "ma5": 200, "ma10": 190, "ma20": 180,
                "ma60": 160, "boll_upper": 230, "boll_mid": 195,
                "boll_lower": 160, "gain_20d": 0.25,
            },
            "revenue": {"month": "2026/03", "revenue": 30000, "yoy": 10.0,
                        "mom": 5.0, "ytd_revenue": 90000, "ytd_yoy": 8.0},
            "eps": {"quarter": "2025Q4", "eps": 5.0, "yoy": 50,
                    "ytd_eps": 18.0, "ytd_yoy": 40},
        },
        # 虧損(會被基本面擋)
        "9999": {
            "tech": {
                "price": 50, "change": 0, "ma5": 49.5, "ma10": 49, "ma20": 48,
                "ma60": 45, "boll_upper": 55, "boll_mid": 48,
                "boll_lower": 41, "gain_20d": 0.03,
            },
            "revenue": {"month": "2026/03", "revenue": 5000, "yoy": -15.0,
                        "mom": -5.0, "ytd_revenue": 14000, "ytd_yoy": -12.0},
            "eps": {"quarter": "2025Q4", "eps": -1.5, "yoy": -200,
                    "ytd_eps": -4.0, "ytd_yoy": -150},
        },
    }
    profile = profiles.get(stock_id)
    if not profile:
        # 未列出的標的給空殼
        empty_tech = {
            k: None
            for k in [
                "price", "change", "ma5", "ma10", "ma20", "ma60",
                "boll_upper", "boll_mid", "boll_lower", "gain_20d",
            ]
        }
        return empty_tech, None, None
    return profile["tech"], profile["revenue"], profile["eps"]


# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="台股每日籌碼掃描")
    parser.add_argument("--date", help="指定日期 YYYYMMDD")
    parser.add_argument(
        "--use-finmind",
        action="store_true",
        help="使用 FinMind 取代 Goodinfo",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用內建 mock 資料(端到端驗證,不打外部網路)",
    )
    args = parser.parse_args()

    run(date=args.date, use_finmind=args.use_finmind, mock=args.mock)


if __name__ == "__main__":
    main()
