"""技術面篩選邏輯。

條件(讀自 ``config/filters.yaml`` 的 ``tech_filter`` 區塊):
1. 均線糾結:max(MA5,MA10,MA20)/min(...) - 1 <= ``ma_glued_threshold``
2. 股價位於布林中軌或以下(可設 lower / middle / upper)
3. 近 20 日漲幅 <= ``recent_gain_max``
4. 股價 > 季線(MA60),若 ``price_above_ma60`` 為 True

「未發動的低基期 + 多頭結構」是核心精神:
- 均線糾結 → 即將發動
- 在布林中軌附近 → 沒有過熱
- 漲幅小 → 還沒漲
- 站上季線 → 多頭結構

任一欄位為 None 時,以「保守跳過」原則處理:
- 是否通過(``is_low_basis``):缺資料不通過(避免誤判)。
- 評分(``score``):缺項以 0 計算對應子分。
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("filter.tech")

_BOLL_POSITION_RANK = {"lower": 0, "middle": 1, "upper": 2}


class TechFilter:
    """技術面篩選器。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.ma_glued_threshold: float = float(cfg.get("ma_glued_threshold", 0.05))
        self.boll_position_max: str = str(
            cfg.get("bollinger_position_max", "middle")
        ).lower()
        self.recent_gain_max: float = float(cfg.get("recent_gain_max", 0.15))
        self.require_above_ma60: bool = bool(cfg.get("price_above_ma60", True))

    # ------------------------------------------------------------------
    def is_low_basis(self, tech: dict[str, Any] | None) -> bool:
        """判斷是否為「低基期 + 多頭」標的。

        Args:
            tech: ``histock.get_technical()`` 的回傳 dict。

        Returns:
            通過全部條件為 True。任一欄位為 None 視為失敗。
        """
        if not tech:
            return False

        # 1) 均線糾結
        glued = ma_glued_ratio(tech.get("ma5"), tech.get("ma10"), tech.get("ma20"))
        if glued is None or glued > self.ma_glued_threshold:
            return False

        # 2) 布林位置
        price = tech.get("price")
        boll_pos = bollinger_position(
            price,
            tech.get("boll_lower"),
            tech.get("boll_mid"),
            tech.get("boll_upper"),
        )
        if boll_pos is None:
            return False
        if _BOLL_POSITION_RANK[boll_pos] > _BOLL_POSITION_RANK[self.boll_position_max]:
            return False

        # 3) 近 20 日漲幅
        gain = tech.get("gain_20d")
        if gain is None or gain > self.recent_gain_max:
            return False

        # 4) 站上季線
        if self.require_above_ma60:
            ma60 = tech.get("ma60")
            if ma60 is None or price is None or price <= ma60:
                return False

        return True

    # ------------------------------------------------------------------
    def score(self, tech: dict[str, Any] | None) -> float:
        """技術面分數(0-100)。

        子分:
        - 均線糾結度:越糾結越高分(0-30)
        - 布林位置:越接近下軌越高分(0-25)
        - 近 20 日漲幅:越小越高分(0-25)
        - 站上季線:站上得 20 分,沒站上 0 分
        """
        if not tech:
            return 0.0

        # 均線糾結:0% → 30 分;>= threshold → 0 分
        glued = ma_glued_ratio(tech.get("ma5"), tech.get("ma10"), tech.get("ma20"))
        if glued is None:
            ma_score = 0.0
        else:
            ma_score = max(0.0, 30.0 * (1 - glued / max(self.ma_glued_threshold, 1e-9)))

        # 布林位置:lower → 25,middle → 12,upper → 0
        boll_pos = bollinger_position(
            tech.get("price"),
            tech.get("boll_lower"),
            tech.get("boll_mid"),
            tech.get("boll_upper"),
        )
        boll_score = {"lower": 25.0, "middle": 12.0, "upper": 0.0}.get(
            boll_pos or "", 0.0
        )

        # 近 20 日漲幅:越小越高,0% → 25,>= recent_gain_max → 0
        gain = tech.get("gain_20d")
        if gain is None:
            gain_score = 0.0
        else:
            gain_score = max(
                0.0, 25.0 * (1 - max(gain, 0) / max(self.recent_gain_max, 1e-9))
            )

        # 季線:站上 20 分
        price = tech.get("price")
        ma60 = tech.get("ma60")
        ma60_score = 20.0 if (price and ma60 and price > ma60) else 0.0

        return round(min(100.0, ma_score + boll_score + gain_score + ma60_score), 2)


# ----------------------------------------------------------------------
# 純函式工具
# ----------------------------------------------------------------------
def ma_glued_ratio(
    ma5: float | None, ma10: float | None, ma20: float | None
) -> float | None:
    """計算均線糾結度 = max/min - 1。任一為 None 或非正數回傳 None。"""
    vals = [v for v in (ma5, ma10, ma20) if v is not None and v > 0]
    if len(vals) < 3:
        return None
    return max(vals) / min(vals) - 1


def bollinger_position(
    price: float | None,
    lower: float | None,
    mid: float | None,
    upper: float | None,
) -> str | None:
    """判斷股價位於布林通道哪個區段:lower / middle / upper。"""
    if price is None:
        return None
    # 三軌都有時用三軌判斷
    if lower is not None and mid is not None and upper is not None:
        if price <= mid:
            # 進一步區分 lower / middle:更靠近下軌的算 lower
            return "lower" if price <= (lower + mid) / 2 else "middle"
        return "upper" if price >= (mid + upper) / 2 else "middle"
    # 退而求其次:只用中軌
    if mid is not None:
        return "middle" if price <= mid else "upper"
    return None
