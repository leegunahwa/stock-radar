"""filters 單元測試。"""

from __future__ import annotations

import pandas as pd

from src.filters.chip_filter import ChipFilter, _count_consecutive_buy
from src.filters.fundamental_filter import FundamentalFilter
from src.filters.tech_filter import (
    TechFilter,
    bollinger_position,
    ma_glued_ratio,
)


# =============================================================================
# ChipFilter
# =============================================================================
def _sample_fund_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # 買超 5000 張(台積電),通過
            {"stock_id": "2330", "name": "台積電", "buy": 5_000_000,
             "sell": 1_000_000, "net_buy": 4_000_000},
            # 買超 100 張(< 1000),不通過
            {"stock_id": "2317", "name": "鴻海", "buy": 200_000,
             "sell": 100_000, "net_buy": 100_000},
            # 0050 在 exclude 名單中
            {"stock_id": "0050", "name": "元大台灣50", "buy": 9_000_000,
             "sell": 0, "net_buy": 9_000_000},
        ]
    )


def test_chip_filter_threshold() -> None:
    cf = ChipFilter(
        config={"min_investment_trust_buy": 1000, "consecutive_buy_days": 1},
        exclude_stocks=["0050"],
    )
    out = cf.initial_screening(_sample_fund_df())
    assert list(out["stock_id"]) == ["2330"]
    assert out.iloc[0]["net_buy_lots"] == 4000.0
    assert out.iloc[0]["chip_score"] > 0


def test_chip_filter_consecutive_days() -> None:
    today = _sample_fund_df()
    # 歷史:2330 連續買超,2317 沒買超
    history = pd.DataFrame(
        [
            {"stock_id": "2330", "name": "台積電", "buy": 1_000_000,
             "sell": 0, "net_buy": 1_000_000},
            {"stock_id": "2317", "name": "鴻海", "buy": 0,
             "sell": 100_000, "net_buy": -100_000},
        ]
    )
    cf = ChipFilter(
        config={"min_investment_trust_buy": 1000, "consecutive_buy_days": 2},
        exclude_stocks=["0050"],
    )
    out = cf.initial_screening(today, fund_dfs_history=[history])
    assert list(out["stock_id"]) == ["2330"]
    assert out.iloc[0]["consecutive_days"] >= 2


def test_chip_filter_empty_input() -> None:
    cf = ChipFilter(config={"min_investment_trust_buy": 1000})
    out = cf.initial_screening(pd.DataFrame())
    assert out.empty
    assert "chip_score" in out.columns


def test_count_consecutive_buy() -> None:
    h1 = pd.DataFrame([{"stock_id": "2330", "net_buy": 100}])
    h2 = pd.DataFrame([{"stock_id": "2330", "net_buy": 200}])
    h3 = pd.DataFrame([{"stock_id": "2330", "net_buy": -50}])
    # h1, h2, h3(由舊到新) → 倒數從 h3 開始,首日 -50 立刻中斷
    assert _count_consecutive_buy("2330", [h1, h2, h3]) == 0
    # h3, h2, h1 → 倒數從 h1 開始,連續 2 天有買超
    assert _count_consecutive_buy("2330", [h3, h2, h1]) == 2


def test_chip_score_components() -> None:
    cf = ChipFilter(
        config={
            "min_investment_trust_buy": 1000,
            "consecutive_buy_days": 1,
            "use_ptt_score": True,
            "ptt_mention_weight": 0.2,
        }
    )
    # 達門檻 30,連續 4 天 30,PTT 命中 1 篇 → 0.2*1*100=20 → cap 10
    s = cf.score(net_buy_lots=1000, consecutive_days=4, ptt_mentions=1)
    assert 60 <= s <= 100


# =============================================================================
# TechFilter
# =============================================================================
GOOD_TECH = {
    "price": 100, "change": 1, "ma5": 100, "ma10": 99, "ma20": 98,
    "ma60": 95, "boll_upper": 110, "boll_mid": 100, "boll_lower": 90,
    "gain_20d": 0.05,
}

OVERHEATED_TECH = {**GOOD_TECH, "gain_20d": 0.25}  # 已大漲
BELOW_MA60_TECH = {**GOOD_TECH, "price": 90, "ma60": 95}
LOOSE_MA_TECH = {**GOOD_TECH, "ma5": 100, "ma10": 105, "ma20": 110}  # 不糾結


def test_tech_filter_pass() -> None:
    tf = TechFilter()
    assert tf.is_low_basis(GOOD_TECH) is True


def test_tech_filter_block_overheated() -> None:
    tf = TechFilter()
    assert tf.is_low_basis(OVERHEATED_TECH) is False


def test_tech_filter_block_below_ma60() -> None:
    tf = TechFilter()
    assert tf.is_low_basis(BELOW_MA60_TECH) is False


def test_tech_filter_block_loose_ma() -> None:
    tf = TechFilter()
    assert tf.is_low_basis(LOOSE_MA_TECH) is False


def test_tech_filter_none_input() -> None:
    tf = TechFilter()
    assert tf.is_low_basis(None) is False
    assert tf.score(None) == 0.0


def test_ma_glued_ratio() -> None:
    assert ma_glued_ratio(100, 100, 100) == 0
    assert abs(ma_glued_ratio(100, 105, 110) - 0.10) < 1e-9
    assert ma_glued_ratio(None, 100, 100) is None


def test_bollinger_position() -> None:
    # price 90 (lower), 100 (mid), 110 (upper)
    assert bollinger_position(85, 80, 100, 120) == "lower"
    assert bollinger_position(95, 80, 100, 120) == "middle"
    assert bollinger_position(115, 80, 100, 120) == "upper"
    assert bollinger_position(None, 80, 100, 120) is None


def test_tech_score_in_range() -> None:
    tf = TechFilter()
    s = tf.score(GOOD_TECH)
    assert 0 <= s <= 100


# =============================================================================
# FundamentalFilter
# =============================================================================
DEFAULT_FUND_CFG = {
    "conditions": [
        {"monthly_revenue_yoy_min": 0},
        {"quarterly_eps_min": 0},
    ],
    "exclude": [
        {"loss_recent_year": True},
    ],
}


def test_fundamental_pass_revenue() -> None:
    ff = FundamentalFilter(DEFAULT_FUND_CFG)
    rev = {"yoy": 5.0, "revenue": 100}
    eps = {"eps": 1.0, "ytd_eps": 3.0}
    assert ff.is_healthy(rev, eps) is True


def test_fundamental_pass_eps_only() -> None:
    ff = FundamentalFilter(DEFAULT_FUND_CFG)
    rev = {"yoy": -5.0}
    eps = {"eps": 1.0, "ytd_eps": 3.0}
    assert ff.is_healthy(rev, eps) is True  # EPS 正即可


def test_fundamental_block_loss() -> None:
    ff = FundamentalFilter(DEFAULT_FUND_CFG)
    rev = {"yoy": 10.0}
    eps = {"eps": -1.0, "ytd_eps": -4.0}
    assert ff.is_healthy(rev, eps) is False


def test_fundamental_score_in_range() -> None:
    ff = FundamentalFilter(DEFAULT_FUND_CFG)
    s = ff.score({"yoy": 30}, {"eps": 3.0})
    assert s == 100.0
    s2 = ff.score({"yoy": 0}, {"eps": 0})
    assert s2 == 0.0
    s3 = ff.score(None, None)
    assert s3 == 0.0
