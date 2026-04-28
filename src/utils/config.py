"""設定檔載入工具。

讀取 ``config/filters.yaml`` 並提供型別友善的存取介面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "filters.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """讀取 YAML 設定檔。

    Args:
        path: 設定檔路徑;為 None 時使用 ``config/filters.yaml``。

    Returns:
        解析後的 dict。

    Raises:
        FileNotFoundError: 找不到設定檔。
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"找不到設定檔: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data
