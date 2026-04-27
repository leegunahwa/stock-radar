"""籌碼面篩選邏輯。

條件(讀自 ``config/filters.yaml`` 的 ``chip_filter`` 區塊):
- 投信當日買超(張)>= ``min_investment_trust_buy``
- 連續買超天數 >= ``consecutive_buy_days``
- (選用)PTT 提及次數加分

注意單位:T86 ``net_buy`` 欄位是「股」,本模組轉換為「張」(/1000)後比對門檻。

評分(0-100):
- base_score = clamp(net_buy_lots / threshold * 30, 0, 60)
  → 達門檻 30 分,4 倍門檻給滿 60 分。
- consecutive_score = clamp((consecutive_days - 1) * 10, 0, 30)
  → 連 4 天滿 30 分。
- ptt_score = clamp(mention_count * weight * 100, 0, 10)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("filter.chip")

# 投信買賣超單位轉換:1 張 = 1000 股
SHARES_PER_LOT = 1000


class ChipFilter:
    """籌碼面篩選器。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        exclude_stocks: list[str] | None = None,
    ) -> None:
        cfg = config or {}
        self.min_buy_lots: float = float(cfg.get("min_investment_trust_buy", 1000))
        self.consecutive_days: int = int(cfg.get("consecutive_buy_days", 1))
        self.use_ptt: bool = bool(cfg.get("use_ptt_score", False))
        self.ptt_weight: float = float(cfg.get("ptt_mention_weight", 0.0))
        self.exclude_stocks: set[str] = set(exclude_stocks or [])

    # ------------------------------------------------------------------
    def initial_screening(
        self,
        fund_df_today: pd.DataFrame,
        fund_dfs_history: list[pd.DataFrame] | None = None,
        ptt_results: dict[str, dict[str, Any]] | None = None,
    ) -> pd.DataFrame:
        """執行籌碼面初篩,並計算每檔的 chip_score。

        Args:
            fund_df_today: 今日 T86 投信買賣超 DataFrame
                (需含欄位 stock_id, name, buy, sell, net_buy)。
            fund_dfs_history: 過去 N-1 天的 T86 DataFrame 清單(由舊到新)。
                為 None 或空時跳過「連續買超」檢查。
            ptt_results: ``{stock_id: {keyword: count, "titles": [...]}}``
                結構;為 None 時跳過 PTT 加分。

        Returns:
            符合條件的 DataFrame,額外欄位:
            - ``net_buy_lots``: 投信當日買超(張)
            - ``consecutive_days``: 連續買超天數
            - ``ptt_mentions``: PTT 提及篇數(若有 ptt_results)
            - ``chip_score``: 籌碼分(0-100)
            按 chip_score 降序排序。
        """
        if fund_df_today is None or fund_df_today.empty:
            logger.warning("ChipFilter: 今日 T86 為空,跳過初篩")
            return _empty_result()

        df = fund_df_today.copy()
        # 過濾排除清單
        if self.exclude_stocks:
            df = df[~df["stock_id"].isin(self.exclude_stocks)]

        # 換算為「張」並過濾門檻
        df["net_buy_lots"] = df["net_buy"] / SHARES_PER_LOT
        df = df[df["net_buy_lots"] >= self.min_buy_lots]
        if df.empty:
            logger.info("ChipFilter: 沒有任何標的達投信買超門檻")
            return _empty_result()

        # 計算連續買超天數
        if self.consecutive_days > 1 and fund_dfs_history:
            df["consecutive_days"] = df["stock_id"].apply(
                lambda sid: _count_consecutive_buy(sid, fund_dfs_history) + 1
            )
            df = df[df["consecutive_days"] >= self.consecutive_days]
            if df.empty:
                logger.info(
                    f"ChipFilter: 沒有標的達連續 {self.consecutive_days} 日買超"
                )
                return _empty_result()
        else:
            df["consecutive_days"] = 1

        # PTT 加分
        if self.use_ptt and ptt_results:
            df["ptt_mentions"] = df["stock_id"].apply(
                lambda sid: len(ptt_results.get(sid, {}).get("titles", []))
            )
        else:
            df["ptt_mentions"] = 0

        # 評分
        df["chip_score"] = df.apply(
            lambda row: self.score(
                net_buy_lots=row["net_buy_lots"],
                consecutive_days=row["consecutive_days"],
                ptt_mentions=row["ptt_mentions"],
            ),
            axis=1,
        )

        df = df.sort_values("chip_score", ascending=False).reset_index(drop=True)
        return df[
            [
                "stock_id",
                "name",
                "buy",
                "sell",
                "net_buy",
                "net_buy_lots",
                "consecutive_days",
                "ptt_mentions",
                "chip_score",
            ]
        ]

    # ------------------------------------------------------------------
    def score(
        self,
        net_buy_lots: float,
        consecutive_days: int = 1,
        ptt_mentions: int = 0,
    ) -> float:
        """計算籌碼分(0-100)。"""
        # 量能分(0-60)
        ratio = net_buy_lots / max(self.min_buy_lots, 1)
        base = min(60.0, ratio * 30.0)
        # 連續天數分(0-30)
        cons = min(30.0, max(0, consecutive_days - 1) * 10.0)
        # PTT 提及分(0-10)
        ptt = (
            min(10.0, ptt_mentions * self.ptt_weight * 100.0)
            if self.use_ptt
            else 0.0
        )
        return round(min(100.0, base + cons + ptt), 2)


# ----------------------------------------------------------------------
# 工具函式
# ----------------------------------------------------------------------
def _count_consecutive_buy(
    stock_id: str, history_dfs: list[pd.DataFrame]
) -> int:
    """從歷史 DataFrame(由舊到新)倒數,計算連續買超天數。

    從最新一天往前數,只要 net_buy <= 0 就停止。
    """
    count = 0
    for hist_df in reversed(history_dfs):
        if hist_df is None or hist_df.empty:
            break
        row = hist_df[hist_df["stock_id"] == stock_id]
        if row.empty:
            break
        net_buy = row["net_buy"].iloc[0]
        if net_buy > 0:
            count += 1
        else:
            break
    return count


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "stock_id",
            "name",
            "buy",
            "sell",
            "net_buy",
            "net_buy_lots",
            "consecutive_days",
            "ptt_mentions",
            "chip_score",
        ]
    )
