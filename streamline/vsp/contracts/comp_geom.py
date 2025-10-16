# streamline/vsp/contracts/comp_geom.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from ...analysis.contracts import Receipt, Ticket

class CompGeomTicket(Ticket):
    """Inputs for running the OpenVSP ``CompGeom`` analysis."""

    half_mesh_flag: Optional[bool] = None
    write_csv_flag: Optional[bool] = None
    file_export_types: Optional[int | List[int]] = None
    write_flags: Dict[str, bool] = Field(default_factory=dict)
    cleanup_mesh_geoms: bool = True


@dataclass
class CompGeomPayload:
    analysis_name: str
    set_index: Optional[int]
    set_name: Optional[str]
    half_mesh_flag: Optional[bool]
    write_csv_flag: Optional[bool]
    file_export_mask: Optional[int]
    results_available: Dict[str, str] = field(default_factory=dict)
    summary: Dict[str, float] = field(default_factory=dict)
    results_data: Dict[str, Any] = field(default_factory=dict)
    mesh_geom_ids: List[str] = field(default_factory=list)
    applied_var_presets: List[Tuple[str, str]] = field(default_factory=list)
    parm_overrides: Dict[str, float] = field(default_factory=dict)


class CompGeomReceipt(Receipt):
    settings: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, float] = Field(default_factory=dict)
    available_results: Dict[str, str] = Field(default_factory=dict)
