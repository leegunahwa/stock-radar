"""成交量型態篩選與評分。
# update by Leo 2026-04-29 & 新增成交量訊號評分

評分邏輯:

量縮洗盤（搭配低基期最強）:
- 當日量 < 5 日均量 50% → 極度縮量，洗盤尾聲，+15
- 當日量 < 5 日均量 70% → 縮量，+8

量增突破:
- 當日量 > 20 日均量 200% → 爆量啟動，+10
- 當日量 > 20 日均量 150% → 溫和放量，+5

合計 0-25 分。
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("filter.volume")


class VolumeFilter:
    """成交量型態評分器。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.shrink_extreme: float = float(cfg.get("shrink_extreme_ratio", 0.5))
        self.shrink_mild: float = float(cfg.get("shrink_mild_ratio", 0.7))
        self.surge_extreme: float = float(cfg.get("surge_extreme_ratio", 2.0))
        self.surge_mild: float = float(cfg.get("surge_mild_ratio", 1.5))

    def score(self, volume: dict[str, Any] | None) -> float:
        """計算成交量分數（0-25）。"""
        if not volume:
            return 0.0

        score = 0.0
        ratio_5 = volume.get("vol_ratio_5")
        ratio_20 = volume.get("vol_ratio_20")

        # 量縮訊號（用 5 日均量比）
        if ratio_5 is not None:
            if ratio_5 <= self.shrink_extreme:
                score += 15
            elif ratio_5 <= self.shrink_mild:
                score += 8

        # 量增訊號（用 20 日均量比）
        if ratio_20 is not None:
            if ratio_20 >= self.surge_extreme:
                score += 10
            elif ratio_20 >= self.surge_mild:
                score += 5

        return min(25.0, score)

    def get_signal(self, volume: dict[str, Any] | None) -> str:
        """回傳成交量訊號文字描述。"""
        if not volume:
            return "無資料"

        ratio_5 = volume.get("vol_ratio_5")
        ratio_20 = volume.get("vol_ratio_20")

        if ratio_5 is not None and ratio_5 <= self.shrink_extreme:
            return "極度縮量"
        if ratio_5 is not None and ratio_5 <= self.shrink_mild:
            return "縮量"
        if ratio_20 is not None and ratio_20 >= self.surge_extreme:
            return "爆量"
        if ratio_20 is not None and ratio_20 >= self.surge_mild:
            return "溫和放量"
        return "量平"
