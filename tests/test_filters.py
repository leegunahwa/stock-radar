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
    """fixture:含投信 + 主力欄位的 T86 mock。"""
    return pd.DataFrame(
        [
            # 投信買 4000 張、主力 15500 張 → 兩者皆達標
            {"stock_id": "2330", "name": "台積電", "buy": 5_000_000,
             "sell": 1_000_000, "net_buy": 4_000_000,
             "foreign_net_buy": 11_000_000, "dealer_net_buy": 500_000,
             "main_force_net_buy": 15_500_000},
            # 投信 100 張 < 門檻;主力 4500 張 → 主力達標(any 模式可過)
            {"stock_id": "2317", "name": "鴻海", "buy": 200_000,
             "sell": 100_000, "net_buy": 100_000,
             "foreign_net_buy": 4_400_000, "dealer_net_buy": 0,
             "main_force_net_buy": 4_500_000},
            # 投信 9000 張(達標)、主力 9000 張 → 但在 exclude 名單
            {"stock_id": "0050", "name": "元大台灣50", "buy": 9_000_000,
             "sell": 0, "net_buy": 9_000_000,
             "foreign_net_buy": 0, "dealer_net_buy": 0,
             "main_force_net_buy": 9_000_000},
            # 投信 50 張 < 門檻;主力 1500 張 < 門檻 → 不過
            {"stock_id": "2603", "name": "長榮", "buy": 100_000,
             "sell": 50_000, "net_buy": 50_000,
             "foreign_net_buy": 1_400_000, "dealer_net_buy": 50_000,
             "main_force_net_buy": 1_500_000},
        ]
    )


def test_chip_filter_any_mode() -> None:
    """any 模式:投信 OR 主力 任一達標即可。"""
    cf = ChipFilter(
        config={
            "min_investment_trust_buy": 1000,
            "min_main_force_buy": 3000,
            "chip_match_mode": "any",
            "consecutive_buy_days": 1,
        },
        exclude_stocks=["0050"],
    )
    out = cf.initial_screening(_sample_fund_df())
    # 2330(兩者皆過) + 2317(主力過) → 排除 0050、2603 不過
    assert set(out["stock_id"]) == {"2330", "2317"}
    # 2330 主力分數較高,排序在前
    assert out.iloc[0]["stock_id"] == "2330"


def test_chip_filter_all_mode() -> None:
    """all 模式:投信 + 主力 都需達標。"""
    cf = ChipFilter(
        config={
            "min_investment_trust_buy": 1000,
            "min_main_force_buy": 3000,
            "chip_match_mode": "all",
            "consecutive_buy_days": 1,
        },
        exclude_stocks=["0050"],
    )
    out = cf.initial_screening(_sample_fund_df())
    # 只有 2330 兩邊都達標
    assert list(out["stock_id"]) == ["2330"]


def test_chip_filter_consecutive_days() -> None:
    today = _sample_fund_df()
    # 歷史:2330 連續(投信)買超,2317 投信負(中斷)
    history = pd.DataFrame(
        [
            {"stock_id": "2330", "name": "台積電", "buy": 1_000_000,
             "sell": 0, "net_buy": 1_000_000,
             "foreign_net_buy": 0, "dealer_net_buy": 0,
             "main_force_net_buy": 1_000_000},
            {"stock_id": "2317", "name": "鴻海", "buy": 0,
             "sell": 100_000, "net_buy": -100_000,
             "foreign_net_buy": 5_000_000, "dealer_net_buy": 0,
             "main_force_net_buy": 4_900_000},
        ]
    )
    cf = ChipFilter(
        config={
            "min_investment_trust_buy": 1000,
            "min_main_force_buy": 3000,
            "chip_match_mode": "any",
            "consecutive_buy_days": 2,
        },
        exclude_stocks=["0050"],
    )
    out = cf.initial_screening(today, fund_dfs_history=[history])
    # 2317 雖然主力過,但投信連續中斷 → 被連續檢查擋下
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


def test_chip_score_uses_max_of_inv_and_main_force() -> None:
    """評分時 base 取投信達標度與主力達標度較高者。"""
    cf = ChipFilter(
        config={
            "min_investment_trust_buy": 1000,
            "min_main_force_buy": 3000,
        }
    )
    # 投信 0 張、主力 12000 張(= 4 倍門檻 → 滿分 60)
    s = cf.score(net_buy_lots=0, main_force_lots=12000, consecutive_days=1)
    assert s >= 60
    # 投信 1000 張(剛達標 → base 30)、主力 0 張
    s2 = cf.score(net_buy_lots=1000, main_force_lots=0, consecutive_days=1)
    assert 25 <= s2 <= 35


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
