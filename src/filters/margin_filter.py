"""融資融券 + 外資動向篩選與評分。
# update by Leo 2026-04-29 & 新增融資融券 + 外資訊號評分

評分邏輯（權證小哥風格）:

融資融券訊號（0-40）:
- 融資減少 + 法人買超 → 籌碼集中，+15
- 融資持平或微增       → 中性，+0
- 券資比 > 30%         → 軋空潛力，+10
- 券資比 > 20%         → 空方壓力，+5
- 融券增加 + 法人買超  → 軋空題材，+5
- 融資大增（> 10%）    → 散戶追買，-5

外資動向訊號（0-30）:
- 外資連買 + 投信連買  → 雙主力同步，+15
- 外資單獨買超         → 偏多，+5
- 外資淨買超量大（> 主力門檻）→ +10
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("filter.margin")


class MarginFilter:
    """融資融券 + 外資動向評分器。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.margin_decrease_bonus: float = float(cfg.get("margin_decrease_bonus", 15))
        self.high_short_ratio_threshold: float = float(cfg.get("high_short_ratio", 30))
        self.mid_short_ratio_threshold: float = float(cfg.get("mid_short_ratio", 20))
        self.margin_surge_pct: float = float(cfg.get("margin_surge_pct", 10))
        self.foreign_large_threshold: float = float(cfg.get("foreign_large_lots", 3000))

    def score(
        self,
        margin: dict[str, Any] | None,
        foreign_net_lots: float = 0,
        inv_net_lots: float = 0,
        foreign_consecutive: int = 0,
        inv_consecutive: int = 0,
    ) -> float:
        """計算融資融券 + 外資綜合分數（0-70）。"""
        margin_s = self._score_margin(margin, inv_net_lots)
        foreign_s = self._score_foreign(
            foreign_net_lots, inv_net_lots, foreign_consecutive, inv_consecutive,
        )
        return round(min(70.0, margin_s + foreign_s), 2)

    def _score_margin(
        self, margin: dict[str, Any] | None, inv_net_lots: float,
    ) -> float:
        """融資融券分數（0-40）。"""
        if not margin:
            return 0.0

        score = 0.0
        m_change = margin.get("margin_change", 0)
        m_balance = margin.get("margin_balance", 1)
        s_change = margin.get("short_change", 0)
        ratio = margin.get("short_margin_ratio", 0)

        # 融資減少 + 法人買超 = 籌碼集中
        if m_change < 0 and inv_net_lots > 0:
            score += self.margin_decrease_bonus

        # 融資大增（散戶追買）= 扣分
        if m_balance > 0:
            m_change_pct = abs(m_change) / m_balance * 100
            if m_change > 0 and m_change_pct > self.margin_surge_pct:
                score -= 5

        # 券資比高 = 軋空潛力
        if ratio >= self.high_short_ratio_threshold:
            score += 10
        elif ratio >= self.mid_short_ratio_threshold:
            score += 5

        # 融券增加 + 法人買超 = 軋空題材
        if s_change > 0 and inv_net_lots > 0:
            score += 5

        return max(0.0, min(40.0, score))

    def _score_foreign(
        self,
        foreign_net_lots: float,
        inv_net_lots: float,
        foreign_consecutive: int,
        inv_consecutive: int,
    ) -> float:
        """外資動向分數（0-30）。"""
        score = 0.0

        # 外資連買 + 投信連買 = 雙主力同步
        if foreign_consecutive >= 2 and inv_consecutive >= 2:
            score += 15
        elif foreign_net_lots > 0 and inv_net_lots > 0:
            score += 8

        # 外資單獨買超
        if foreign_net_lots > 0 and inv_net_lots <= 0:
            score += 5

        # 外資大量買超
        if foreign_net_lots >= self.foreign_large_threshold:
            score += 10

        return min(30.0, score)
