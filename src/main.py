"""台股每日籌碼掃描 — 主流程。

執行順序:
1. 判斷是否為交易日(非交易日直接結束)
2. 籌碼面初篩(投信買賣超 → 候選股 50-100 檔)
3. 對候選股逐一抓技術面 + 基本面
4. 套用三層 filter 並評分
5. 排序取 top N,輸出 JSON

執行方式:
    python -m src.main                          # 真實流程,抓今日資料
    python -m src.main --date 20260424          # 指定日期
    python -m src.main --mock                   # 用內建 mock 資料端到端驗證
    python -m src.main --use-finmind            # 改用 FinMind 取代 Goodinfo
    python -m src.main --output dist/data.json  # 指定 JSON 輸出路徑
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.filters import ChipFilter, FundamentalFilter, MarginFilter, TechFilter, VolumeFilter
from src.filters.tech_filter import bollinger_position, ma_glued_ratio
from src.scrapers import histock, twse_fund, twse_margin, twse_volume
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.utils.trading_calendar import (
    is_trading_day,
    previous_trading_day,
    recent_trading_days,
)

# update by Leo 2026-04-28 & 台北時區常數
TZ_TPE = timezone(timedelta(hours=8))

logger = setup_logger("stock_radar")


# ----------------------------------------------------------------------
# 評分組合
# ----------------------------------------------------------------------
def calculate_total_score(
    chip_score: float,
    tech_score: float,
    fundamental_score: float,
    weights: dict[str, float],
    margin_score: float = 0,
    volume_score: float = 0,
) -> float:
    """依權重組合五項分數。"""  # update by Leo 2026-04-29 & 加入融資融券+成交量
    total = (
        chip_score * weights.get("chip_weight", 0.30)
        + margin_score * weights.get("margin_weight", 0.15)
        + tech_score * weights.get("tech_weight", 0.25)
        + volume_score * weights.get("volume_weight", 0.10)
        + fundamental_score * weights.get("fundamental_weight", 0.20)
    )
    return round(total, 2)


# ----------------------------------------------------------------------
# Enrichment:對單一候選股抓技術面 + 基本面
# ----------------------------------------------------------------------
def enrich_stock(
    stock_id: str,
    date: str,
    use_finmind: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """抓取單一個股的技術面 + 基本面 + 成交量資料。"""
    # update by Leo 2026-04-29 & 新增成交量抓取
    tech = histock.get_technical(stock_id)
    volume = twse_volume.get_volume_stats(stock_id, date)

    if use_finmind:
        from src.scrapers import finmind

        revenue = finmind.get_monthly_revenue(stock_id)
        eps = finmind.get_quarterly_eps(stock_id)
    else:
        from src.scrapers import goodinfo

        revenue = goodinfo.get_monthly_revenue(stock_id)
        eps = goodinfo.get_quarterly_eps(stock_id)

    return tech, revenue, eps, volume


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def run(
    date: str | None = None,
    use_finmind: bool = False,
    mock: bool = False,
    output: str | None = None,
) -> list[dict[str, Any]]:
    """執行完整掃描流程。

    Args:
        date: YYYYMMDD;為 None 時自動取今日(非交易日則取前一個交易日)。
        use_finmind: 改用 FinMind 取代 Goodinfo。
        mock: 用內建 mock 資料測試端到端流程,不打外部網路。
        output: JSON 輸出路徑;為 None 時預設 dist/data.json。

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
    # Step 1: 籌碼面初篩 + 融資融券  # update by Leo 2026-04-29
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info(f"Step 1: 抓取投信買賣超 + 融資融券({today})")
    if mock:
        fund_today, fund_history = _mock_fund_data(today)
        margin_df = _mock_margin_data()
    else:
        fund_today = twse_fund.get_investment_trust_buy(today)
        fund_history = _fetch_history_fund(
            today, days=int(config.get("chip_filter", {}).get("consecutive_buy_days", 1))
        )
        margin_df = twse_margin.get_margin_data(today)

    logger.info(f"融資融券資料: {len(margin_df)} 檔")

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
    # Step 2: 抓技術面 + 基本面 + 成交量  # update by Leo 2026-04-29
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info(f"Step 2: 抓取候選股技術面 + 基本面 + 成交量(共 {len(candidates_df)} 檔)")
    tech_filter = TechFilter(config.get("tech_filter", {}))
    fund_filter = FundamentalFilter(config.get("fundamental_filter", {}))
    margin_filter = MarginFilter(config.get("margin_filter", {}))
    volume_filter = VolumeFilter(config.get("volume_filter", {}))

    enriched: list[dict[str, Any]] = []
    for _, row in candidates_df.iterrows():
        stock_id = str(row["stock_id"])
        try:
            if mock:
                tech, revenue, eps = _mock_stock_detail(stock_id)
                volume = _mock_volume_data(stock_id)
            else:
                tech, revenue, eps, volume = enrich_stock(
                    stock_id, date=today, use_finmind=use_finmind,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{stock_id} 抓取失敗,略過: {exc}")
            continue

        # 合併融資融券資料
        margin_row = margin_df[margin_df["stock_id"] == stock_id]
        margin = margin_row.iloc[0].to_dict() if not margin_row.empty else None

        # 外資連續買超天數
        foreign_consec = _count_consecutive_foreign(stock_id, fund_history) + (
            1 if row.get("foreign_net_buy", 0) > 0 else 0
        )

        enriched.append(
            {
                "stock_id": stock_id,
                "name": row["name"],
                "chip": row.to_dict(),
                "tech": tech,
                "revenue": revenue,
                "eps": eps,
                "volume": volume,
                "margin": margin,
                "foreign_consecutive": foreign_consec,
            }
        )

    # ------------------------------------------------------------------
    # Step 3: 五層篩選與評分  # update by Leo 2026-04-29
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Step 3: 五層篩選與評分（籌碼+融資融券+技術+成交量+基本面）")
    final: list[dict[str, Any]] = []
    for stock in enriched:
        if not tech_filter.is_low_basis(stock["tech"]):
            logger.debug(f"  {stock['stock_id']} 技術面未過")
            continue
        if not fund_filter.is_healthy(stock["revenue"], stock["eps"]):
            logger.debug(f"  {stock['stock_id']} 基本面未過")
            continue

        chip = stock["chip"]
        chip_s = float(chip.get("chip_score", 0))
        tech_s = tech_filter.score(stock["tech"])
        fund_s = fund_filter.score(stock["revenue"], stock["eps"])

        foreign_lots = float(chip.get("foreign_net_buy", 0)) / 1000
        inv_lots = float(chip.get("net_buy_lots", 0))
        inv_consec = int(chip.get("consecutive_days", 1))
        margin_s = margin_filter.score(
            stock["margin"],
            foreign_net_lots=foreign_lots,
            inv_net_lots=inv_lots,
            foreign_consecutive=stock.get("foreign_consecutive", 0),
            inv_consecutive=inv_consec,
        )
        volume_s = volume_filter.score(stock["volume"])

        total = calculate_total_score(
            chip_s, tech_s, fund_s, weights,
            margin_score=margin_s, volume_score=volume_s,
        )

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
                "margin_score": margin_s,
                "volume_score": volume_s,
                "score": total,
            }
        )

    final.sort(key=lambda x: x["score"], reverse=True)
    top = final[:top_n]
    logger.info(f"最終候選 {len(final)} 檔,輸出前 {len(top)} 檔")

    # ------------------------------------------------------------------
    # Step 4: 輸出 JSON  # update by Leo 2026-04-28 & 改為純 JSON 輸出
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Step 4: 輸出 JSON")

    # 簡短摘要  # update by Leo 2026-04-29 & 加入新欄位
    for i, c in enumerate(top, 1):
        tech = c["tech"] or {}
        chip = c["chip"] or {}
        inv_lots = chip.get("net_buy_lots")
        main_lots = chip.get("main_force_lots")
        logger.info(
            f"  #{i} {c['stock_id']} {c['name']} "
            f"price={tech.get('price')} 投信={inv_lots} 主力={main_lots} "
            f"score={c['score']} "
            f"(chip={c['chip_score']} margin={c.get('margin_score',0)} "
            f"tech={c['tech_score']} vol={c.get('volume_score',0)} "
            f"fund={c['fundamental_score']})"
        )

    # update by Leo 2026-04-28 & 組裝攤平 JSON 並寫檔
    json_payload = build_json_output(top, scan_date=today, config=config)
    out_path = Path(output) if output else Path("dist/data.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"已寫出 JSON → {out_path}")

    return top


# ----------------------------------------------------------------------
# JSON 輸出建構  # update by Leo 2026-04-28 & 攤平結構供前端消費
# ----------------------------------------------------------------------
def build_json_output(
    candidates: list[dict[str, Any]],
    scan_date: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """將候選股清單組裝成前端可直接消費的攤平 JSON。"""
    chip_cfg = config.get("chip_filter", {})
    display_date = f"{scan_date[:4]}-{scan_date[4:6]}-{scan_date[6:]}"
    return {
        "updated_at": datetime.now(TZ_TPE).isoformat(timespec="seconds"),
        "scan_date": scan_date,
        "scan_date_display": display_date,
        "count": len(candidates),
        "filters": {
            "min_investment_trust_buy": chip_cfg.get("min_investment_trust_buy", 1000),
            "min_main_force_buy": chip_cfg.get("min_main_force_buy", 3000),
            "consecutive_buy_days": chip_cfg.get("consecutive_buy_days", 1),
            "chip_match_mode": chip_cfg.get("chip_match_mode", "any"),
        },
        "stocks": [
            _flatten_stock(i, c) for i, c in enumerate(candidates, 1)
        ],
    }


def _flatten_stock(rank: int, c: dict[str, Any]) -> dict[str, Any]:
    """將單一候選股的巢狀結構攤平為一層 dict。"""
    # update by Leo 2026-04-29 & 加入融資融券+外資+成交量欄位
    tech = c.get("tech") or {}
    chip = c.get("chip") or {}
    revenue = c.get("revenue") or {}
    eps = c.get("eps") or {}
    margin = c.get("margin") or {}
    volume = c.get("volume") or {}

    ma_vals = [tech.get(k) for k in ("ma5", "ma10", "ma20")]
    glued = ma_glued_ratio(*ma_vals)
    boll_pos = bollinger_position(
        tech.get("price"),
        tech.get("boll_lower"),
        tech.get("boll_mid"),
        tech.get("boll_upper"),
    )

    return {
        "rank": rank,
        "stock_id": c.get("stock_id", ""),
        "name": c.get("name", ""),
        "price": tech.get("price"),
        "change": tech.get("change"),
        # 籌碼面
        "inv_buy_lots": _safe_round(chip.get("net_buy_lots"), 0),
        "main_force_lots": _safe_round(chip.get("main_force_lots"), 0),
        "foreign_buy_lots": _safe_round(float(chip.get("foreign_net_buy", 0)) / 1000, 0),
        "consecutive_days": chip.get("consecutive_days", 1),
        "foreign_consecutive": c.get("foreign_consecutive", 0),
        # 融資融券
        "margin_change": margin.get("margin_change", 0),
        "short_change": margin.get("short_change", 0),
        "short_margin_ratio": _safe_round(margin.get("short_margin_ratio"), 2),
        # 技術面
        "gain_20d": _safe_round(tech.get("gain_20d"), 4),
        "ma_glued": _safe_round(glued, 4),
        "boll_position": boll_pos,
        # 成交量
        "today_volume": _safe_round(volume.get("today_volume"), 0),
        "vol_ratio_5": _safe_round(volume.get("vol_ratio_5"), 2),
        "vol_ratio_20": _safe_round(volume.get("vol_ratio_20"), 2),
        # 基本面
        "revenue_month": revenue.get("month"),
        "revenue_yoy": _safe_round(revenue.get("yoy"), 2),
        "eps_quarter": eps.get("quarter"),
        "eps": _safe_round(eps.get("eps"), 2),
        # 五項分數
        "chip_score": _safe_round(c.get("chip_score"), 2),
        "margin_score": _safe_round(c.get("margin_score"), 2),
        "tech_score": _safe_round(c.get("tech_score"), 2),
        "volume_score": _safe_round(c.get("volume_score"), 2),
        "fundamental_score": _safe_round(c.get("fundamental_score"), 2),
        "total_score": _safe_round(c.get("score"), 2),
    }


def _safe_round(value: Any, digits: int) -> Any:
    """安全 round；None 回傳 None。"""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# 外資連續買超計算  # update by Leo 2026-04-29
# ----------------------------------------------------------------------
def _count_consecutive_foreign(
    stock_id: str, history_dfs: list[pd.DataFrame],
) -> int:
    """從歷史 DataFrame 計算外資連續買超天數。"""
    count = 0
    for hist_df in reversed(history_dfs):
        if hist_df is None or hist_df.empty:
            break
        if "foreign_net_buy" not in hist_df.columns:
            break
        row = hist_df[hist_df["stock_id"] == stock_id]
        if row.empty:
            break
        if row["foreign_net_buy"].iloc[0] > 0:
            count += 1
        else:
            break
    return count


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
    """產生 mock 投信買賣超 + 主力(三大法人)資料(8 檔股票)。"""
    today_data = [
        # stock_id, name, buy(股), sell(股), 投信net(股), 外資net(股),
        # 自營商net(股), 主力合計(股)
        ("2330", "台積電",   5_000_000, 1_000_000, 4_000_000,
         15_000_000, 1_000_000, 20_000_000),
        ("2454", "聯發科",   3_500_000,   500_000, 3_000_000,
          8_000_000,   500_000, 11_500_000),
        ("2317", "鴻海",     2_500_000,   500_000, 2_000_000,
          6_000_000,   200_000,  8_200_000),
        ("3711", "日月光投控", 1_800_000,  300_000, 1_500_000,
          2_500_000,   100_000,  4_100_000),
        ("2891", "中信金",   1_200_000,   200_000, 1_000_000,
          1_500_000,   -50_000,  2_450_000),  # 主力 < 3000 張
        ("2603", "長榮",       800_000,    50_000,   750_000,
          5_000_000,   200_000,  5_950_000),  # 已大漲(技術面會擋)
        ("0050", "元大台灣50", 9_000_000,         0, 9_000_000,
              0,         0,  9_000_000),  # exclude_stocks 中
        ("9999", "虧損股",   1_500_000,   200_000, 1_300_000,
          2_000_000,         0,  3_300_000),  # 基本面會擋
    ]
    today_df = pd.DataFrame(
        today_data,
        columns=[
            "stock_id", "name", "buy", "sell", "net_buy",
            "foreign_net_buy", "dealer_net_buy", "main_force_net_buy",
        ],
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
        empty_tech = {
            k: None
            for k in [
                "price", "change", "ma5", "ma10", "ma20", "ma60",
                "boll_upper", "boll_mid", "boll_lower", "gain_20d",
            ]
        }
        return empty_tech, None, None
    return profile["tech"], profile["revenue"], profile["eps"]


# update by Leo 2026-04-29 & 新增融資融券與成交量 mock 資料
def _mock_margin_data() -> pd.DataFrame:
    """mock 融資融券資料。"""
    data = [
        ("2330", "台積電",   100, 200, 50000, -100, 50, 80, 3000,  50, 6.0),
        ("2454", "聯發科",    80, 150, 30000,  -70, 30, 40, 2000,  10, 6.7),
        ("2317", "鴻海",     200, 100, 80000,  100, 20, 50, 5000,  30, 6.3),
        ("3711", "日月光投控", 50,  30, 20000,  20, 60, 20, 8000,  40, 40.0),
        ("2891", "中信金",    30,  50, 15000,  -20, 10, 15, 1000, -5,  6.7),
        ("2603", "長榮",     300, 100, 60000,  200, 10, 30, 4000,  20, 6.7),
        ("9999", "虧損股",    80,  40, 10000,   40, 20, 10, 1500,  10, 15.0),
    ]
    return pd.DataFrame(data, columns=[
        "stock_id", "name",
        "margin_buy", "margin_sell", "margin_balance", "margin_change",
        "short_buy", "short_sell", "short_balance", "short_change",
        "short_margin_ratio",
    ])


def _mock_volume_data(stock_id: str) -> dict[str, Any]:
    """mock 成交量資料。"""
    profiles = {
        "2330": {"today_volume": 25000, "vol_5ma": 30000, "vol_20ma": 28000,
                 "vol_ratio_5": 0.83, "vol_ratio_20": 0.89},
        "2454": {"today_volume": 8000,  "vol_5ma": 18000, "vol_20ma": 15000,
                 "vol_ratio_5": 0.44, "vol_ratio_20": 0.53},
        "2317": {"today_volume": 50000, "vol_5ma": 25000, "vol_20ma": 22000,
                 "vol_ratio_5": 2.0,  "vol_ratio_20": 2.27},
        "3711": {"today_volume": 12000, "vol_5ma": 15000, "vol_20ma": 14000,
                 "vol_ratio_5": 0.8,  "vol_ratio_20": 0.86},
        "2891": {"today_volume": 20000, "vol_5ma": 22000, "vol_20ma": 20000,
                 "vol_ratio_5": 0.91, "vol_ratio_20": 1.0},
        "2603": {"today_volume": 80000, "vol_5ma": 30000, "vol_20ma": 25000,
                 "vol_ratio_5": 2.67, "vol_ratio_20": 3.2},
        "9999": {"today_volume": 5000,  "vol_5ma": 6000,  "vol_20ma": 5500,
                 "vol_ratio_5": 0.83, "vol_ratio_20": 0.91},
    }
    return profiles.get(stock_id, {
        "today_volume": None, "vol_5ma": None, "vol_20ma": None,
        "vol_ratio_5": None, "vol_ratio_20": None,
    })


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
    # update by Leo 2026-04-28 & 新增 --output 參數指定 JSON 輸出路徑
    parser.add_argument(
        "--output",
        help="JSON 輸出路徑(預設 dist/data.json)",
    )
    args = parser.parse_args()

    run(
        date=args.date,
        use_finmind=args.use_finmind,
        mock=args.mock,
        output=args.output,
    )


if __name__ == "__main__":
    main()
