"""基本面篩選邏輯。

條件:
- 月營收年增 >= 0 OR Q EPS >= 0
- 排除虧損股
- 排除累積虧損 > 1/2 資本額

具體實作將於 Stage 3 完成。
"""

from __future__ import annotations
