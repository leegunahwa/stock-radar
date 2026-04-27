"""基本面篩選邏輯。

條件(讀自 ``config/filters.yaml`` 的 ``fundamental_filter`` 區塊):

通過(任一即可):
- 月營收年增 >= ``monthly_revenue_yoy_min``(預設 0)
- 季度 EPS >= ``quarterly_eps_min``(預設 0)

排除(任一即排除):
- 近一年虧損(``loss_recent_year``):若有累計 EPS 為負則排除。
- 累積虧損 > 1/2 資本額(``capital_deficit_over_half``):
  本資料目前在 Goodinfo / FinMind 月營收 + EPS 取得不到,
  暫保留條件接口,實際資料來源完備時再啟用。

評分(0-100):
- 月營收年增分:0% → 0,30% 以上 → 50;線性映射(0-50)。
- EPS 分:EPS 0 元 → 0,3 元以上 → 50;線性映射(0-50)。
- 兩者加總,上限 100。
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("filter.fundamental")


class FundamentalFilter:
    """基本面篩選器。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        # SPEC 採取 list of single-key dict 寫法,展平為單一 dict 方便取值
        cond_list: list[dict[str, Any]] = cfg.get("conditions", []) or []
        excl_list: list[dict[str, Any]] = cfg.get("exclude", []) or []
        cond = _flatten_kv_list(cond_list)
        excl = _flatten_kv_list(excl_list)

        self.min_revenue_yoy: float = float(
            cond.get("monthly_revenue_yoy_min", 0.0)
        )
        self.min_eps: float = float(cond.get("quarterly_eps_min", 0.0))
        self.exclude_loss_recent_year: bool = bool(
            excl.get("loss_recent_year", True)
        )
        self.exclude_capital_deficit: bool = bool(
            excl.get("capital_deficit_over_half", False)
        )

    # ------------------------------------------------------------------
    def is_healthy(
        self,
        revenue: dict[str, Any] | None,
        eps: dict[str, Any] | None,
    ) -> bool:
        """判斷基本面是否健康。"""
        # 排除條件優先
        if self.exclude_loss_recent_year and self._is_loss_recent(eps):
            return False

        # 通過條件:任一達標即可
        rev_pass = (
            revenue is not None
            and revenue.get("yoy") is not None
            and revenue["yoy"] >= self.min_revenue_yoy
        )
        eps_pass = (
            eps is not None
            and eps.get("eps") is not None
            and eps["eps"] >= self.min_eps
        )
        return rev_pass or eps_pass

    # ------------------------------------------------------------------
    def score(
        self,
        revenue: dict[str, Any] | None,
        eps: dict[str, Any] | None,
    ) -> float:
        """基本面分數(0-100)。"""
        # 月營收年增分:0~30% 線性映射 0~50
        yoy = (revenue or {}).get("yoy")
        if yoy is None:
            rev_score = 0.0
        else:
            rev_score = max(0.0, min(50.0, yoy / 30.0 * 50.0))

        # EPS 分:0~3 元線性映射 0~50
        eps_val = (eps or {}).get("eps")
        if eps_val is None:
            eps_score = 0.0
        else:
            eps_score = max(0.0, min(50.0, eps_val / 3.0 * 50.0))

        return round(min(100.0, rev_score + eps_score), 2)

    # ------------------------------------------------------------------
    def _is_loss_recent(self, eps: dict[str, Any] | None) -> bool:
        """近期是否虧損。優先看 ytd_eps,沒有就看單季 eps。"""
        if not eps:
            return False
        ytd = eps.get("ytd_eps")
        if ytd is not None:
            return ytd < 0
        single = eps.get("eps")
        return single is not None and single < 0


# ----------------------------------------------------------------------
def _flatten_kv_list(items: list[dict[str, Any]]) -> dict[str, Any]:
    """將 [{"a": 1}, {"b": 2}] 展平為 {"a": 1, "b": 2}。"""
    out: dict[str, Any] = {}
    for d in items or []:
        if isinstance(d, dict):
            out.update(d)
    return out
