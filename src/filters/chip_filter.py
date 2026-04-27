"""籌碼面篩選邏輯。

訊號來源:
- 投信(``net_buy``):買超門檻 ``min_investment_trust_buy`` 張
- 主力(三大法人合計,``main_force_net_buy``):門檻 ``min_main_force_buy`` 張

通過模式 ``chip_match_mode``:
- ``"any"`` (預設):投信買超 OR 主力買超 任一達標即可
- ``"all"``:兩者都需達標

其他條件:
- 連續 N 日買超(``consecutive_buy_days``)— 以「投信」為基準,
  與既有行為一致;若想針對主力檢查可另行擴充。
- ``exclude_stocks`` 黑名單。
- (選用)PTT 提及次數加分。

評分(0-100):
- base_score(0-60):
  ratio = max(投信買超/投信門檻, 主力買超/主力門檻)
  → 達門檻 30 分,4 倍門檻給滿 60 分。
- consecutive_score(0-30):
  (consecutive_days - 1) * 10,連 4 天滿 30 分。
- ptt_score(0-10):
  mention_count * weight * 100,封頂 10。

注意:T86 ``net_buy`` / ``main_force_net_buy`` 單位是「股」,
本模組轉換為「張」(/1000)後比對門檻。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("filter.chip")

# 投信買賣超單位轉換:1 張 = 1000 股
SHARES_PER_LOT = 1000

_VALID_MATCH_MODES = ("any", "all")


class ChipFilter:
    """籌碼面篩選器。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        exclude_stocks: list[str] | None = None,
    ) -> None:
        cfg = config or {}
        self.min_inv_lots: float = float(cfg.get("min_investment_trust_buy", 1000))
        self.min_main_lots: float = float(cfg.get("min_main_force_buy", 3000))
        self.match_mode: str = str(cfg.get("chip_match_mode", "any")).lower()
        if self.match_mode not in _VALID_MATCH_MODES:
            logger.warning(
                f"未知 chip_match_mode={self.match_mode!r},改用預設 'any'"
            )
            self.match_mode = "any"
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
            fund_df_today: 今日 T86 DataFrame(欄位需含 stock_id, name,
                buy, sell, net_buy, main_force_net_buy)。
            fund_dfs_history: 過去 N-1 天的 T86 DataFrame 清單(由舊到新)。
            ptt_results: PTT 搜尋結果(可選)。

        Returns:
            符合條件的 DataFrame,新增欄位:
            - ``net_buy_lots``      : 投信買超(張)
            - ``main_force_lots``   : 主力(三大法人)買超(張)
            - ``consecutive_days``  : 連續(投信)買超天數
            - ``ptt_mentions``      : PTT 提及篇數
            - ``chip_score``        : 籌碼分(0-100)
            按 chip_score 降序排序。
        """
        if fund_df_today is None or fund_df_today.empty:
            logger.warning("ChipFilter: 今日 T86 為空,跳過初篩")
            return _empty_result()

        df = fund_df_today.copy()
        # 向下相容:若舊版 T86 沒有 main_force_net_buy 欄位,補 0
        if "main_force_net_buy" not in df.columns:
            df["main_force_net_buy"] = 0

        # 1) 排除黑名單
        if self.exclude_stocks:
            df = df[~df["stock_id"].isin(self.exclude_stocks)]

        # 2) 換算為「張」
        df["net_buy_lots"] = df["net_buy"] / SHARES_PER_LOT
        df["main_force_lots"] = df["main_force_net_buy"] / SHARES_PER_LOT

        # 3) 投信 / 主力門檻過濾
        inv_pass = df["net_buy_lots"] >= self.min_inv_lots
        main_pass = df["main_force_lots"] >= self.min_main_lots
        if self.match_mode == "all":
            df = df[inv_pass & main_pass]
        else:  # any
            df = df[inv_pass | main_pass]

        if df.empty:
            logger.info(
                f"ChipFilter: 沒有標的達買超門檻"
                f"(投信 >= {self.min_inv_lots} 張 / 主力 >= {self.min_main_lots} 張,"
                f"mode={self.match_mode})"
            )
            return _empty_result()

        # 4) 連續買超檢查(以投信為基準,維持既有語意)
        if self.consecutive_days > 1 and fund_dfs_history:
            df["consecutive_days"] = df["stock_id"].apply(
                lambda sid: _count_consecutive_buy(sid, fund_dfs_history) + 1
            )
            df = df[df["consecutive_days"] >= self.consecutive_days]
            if df.empty:
                logger.info(
                    f"ChipFilter: 沒有標的達連續 {self.consecutive_days} 日(投信)買超"
                )
                return _empty_result()
        else:
            df["consecutive_days"] = 1

        # 5) PTT 加分
        if self.use_ptt and ptt_results:
            df["ptt_mentions"] = df["stock_id"].apply(
                lambda sid: len(ptt_results.get(sid, {}).get("titles", []))
            )
        else:
            df["ptt_mentions"] = 0

        # 6) 評分
        df["chip_score"] = df.apply(
            lambda row: self.score(
                net_buy_lots=row["net_buy_lots"],
                main_force_lots=row["main_force_lots"],
                consecutive_days=row["consecutive_days"],
                ptt_mentions=row["ptt_mentions"],
            ),
            axis=1,
        )

        df = df.sort_values("chip_score", ascending=False).reset_index(drop=True)

        preferred = [
            "stock_id", "name", "buy", "sell", "net_buy",
            "foreign_net_buy", "dealer_net_buy", "main_force_net_buy",
            "net_buy_lots", "main_force_lots",
            "consecutive_days", "ptt_mentions", "chip_score",
        ]
        return df[[c for c in preferred if c in df.columns]]

    # ------------------------------------------------------------------
    def score(
        self,
        net_buy_lots: float,
        main_force_lots: float = 0.0,
        consecutive_days: int = 1,
        ptt_mentions: int = 0,
    ) -> float:
        """計算籌碼分(0-100)。

        base_score 取「投信達標度」與「主力達標度」較高者,
        確保不論是哪一邊強都能反映在分數上。
        """
        inv_ratio = net_buy_lots / max(self.min_inv_lots, 1)
        main_ratio = main_force_lots / max(self.min_main_lots, 1)
        ratio = max(inv_ratio, main_ratio)

        # 量能分(0-60)
        base = min(60.0, max(0.0, ratio) * 30.0)
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
    stock_id: str,
    history_dfs: list[pd.DataFrame],
    column: str = "net_buy",
) -> int:
    """從歷史 DataFrame(由舊到新)倒數,計算連續買超天數。

    從最新一天往前數,只要 ``column`` 值 <= 0 或股票不在當天的資料中
    就停止。
    """
    count = 0
    for hist_df in reversed(history_dfs):
        if hist_df is None or hist_df.empty or column not in hist_df.columns:
            break
        row = hist_df[hist_df["stock_id"] == stock_id]
        if row.empty:
            break
        net_buy = row[column].iloc[0]
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
            "foreign_net_buy",
            "dealer_net_buy",
            "main_force_net_buy",
            "net_buy_lots",
            "main_force_lots",
            "consecutive_days",
            "ptt_mentions",
            "chip_score",
        ]
    )
