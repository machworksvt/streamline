from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from ..core.tables import (
    new_stability_derivs_table, new_parasite_component_table, new_parasite_total_table,
    new_trim_table, new_op_summary_table
)

def assemble_op_summary_row(meta: Dict[str, Any], trim: Dict[str, float], control_groups: List[str]) -> pd.DataFrame:
    """
    Build a one-row op summary frame matching our schema (caller passes (set,config,op) keys).
    """
    df = new_op_summary_table(control_groups)
    # caller will fill and index; this is here as a typed constructor
    return df
