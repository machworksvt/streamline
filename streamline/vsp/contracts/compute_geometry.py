# streamline/vsp/contracts/compute_geometry.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal, List, Tuple

from pydantic import Field

from ...analysis.contracts import Receipt, Ticket


class ComputeGeometryTicket(Ticket):
    """Inputs needed to prep the watertight mesh before any VSPAERO run."""
    analysis_method: Literal["VLM"] = "VLM"
    symmetry: Optional[int] = None
    alternate_input_format_flag: Optional[int] = None  # rarely needed


@dataclass
class ComputeGeometryPayload:
    analysis_name: str
    analysis_method: Literal["VLM"]
    set_index: Optional[int]
    set_name: Optional[str]
    mode_id: Optional[str]
    use_mode_flag: Optional[bool]
    applied_var_presets: List[Tuple[str, str]] = field(default_factory=list)
    parm_overrides: Dict[str, float] = field(default_factory=dict)
    symmetry: Optional[int] = None
    alternate_input_format_flag: Optional[int] = None


class ComputeGeometryReceipt(Receipt):
    """No payloads needed; just echo what we did so the run is auditable."""
    settings: Dict[str, Any] = Field(default_factory=dict)
