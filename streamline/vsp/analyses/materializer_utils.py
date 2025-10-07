from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


__all__ = [
    "df_to_split_dict",
    "store_dataframe",
]


def df_to_split_dict(df: Optional["pd.DataFrame"]) -> Dict[str, Any]:
    """Convert an optional DataFrame into the orient="split" mapping expected by receipts."""
    if df is None:
        return {"index": [], "columns": [], "data": []}
    return df.to_dict(orient="split")


def store_dataframe(df: Optional["pd.DataFrame"], path: Path) -> None:
    """Persist a DataFrame to CSV if provided."""
    if df is not None:
        df.to_csv(path, index=False)