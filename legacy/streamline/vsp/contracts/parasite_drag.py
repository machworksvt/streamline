# streamline/vsp/contracts/parasite_drag.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal, List, Tuple
from pydantic import Field
import pandas as pd
from .base import Ticket, Receipt

class ParasiteDragTicket(Ticket):
    """Inputs for the VSPAERO 'ParasiteDrag' analysis."""
    # Set / Mode selection (inherits set_index/set_name + udp_overrides)

    # Freestream entry (choose what you provide; you may set freestream_prop_choice explicitly)
    freestream_prop_choice: Optional[int] = None   # if you know the exact enum
    altitude_m: Optional[float] = None
    delta_temp_K: Optional[float] = None
    rho_kgpm3: Optional[float] = None
    pressure_Pa: Optional[float] = None
    temperature_K: Optional[float] = None
    vinf_mps: Optional[float] = None
    mach: Optional[float] = None
    re_per_length: Optional[float] = None
    dynamic_visc_Pas: Optional[float] = None
    kinematic_visc_m2ps: Optional[float] = None
    specific_heat_ratio: Optional[float] = None

    # Reference choices
    ref_flag: Optional[int] = None
    sref_m2: Optional[float] = None
    wing_id: Optional[str] = None

    # Recompute geometry inside the analysis
    recompute_geom: Optional[bool] = None

    # Units/enums (all optional; pass through if set)
    length_unit: Optional[int] = None
    alt_length_unit: Optional[int] = None
    temp_unit: Optional[int] = None
    pres_unit: Optional[int] = None
    velocity_unit: Optional[int] = None

    # Skin friction equations
    lam_cf_eqn_choice: Optional[int] = None
    turb_cf_eqn_choice: Optional[int] = None

    # Export behavior
    export_subcomp_flag: Optional[int] = None
    file_name: Optional[str] = None  # if you want VSP to emit its own file

@dataclass
class ParasiteDragPayload:
    analysis_name: str
    set_index: Optional[int]
    set_name: Optional[str]
    mode_id: Optional[str]
    use_mode_flag: Optional[bool]
    applied_var_presets: List[Tuple[str, str]] = field(default_factory=list)
    parm_overrides: Dict[str, float] = field(default_factory=dict)
    operating_point: Dict[str, Any] = field(default_factory=dict)
    results_id: Optional[str] = None
    totals: Dict[str, Optional[float]] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    flight_condition: Dict[str, Any] = field(default_factory=dict)
    components: Optional[pd.DataFrame] = None
    excrescence: Optional[pd.DataFrame] = None

class ParasiteDragReceipt(Receipt):
    vsp_results_id: Optional[str] = None
    total_cd: Optional[float] = None
    total_f: Optional[float] = None
    geom_cd_total: Optional[float] = None
    geom_f_total: Optional[float] = None
    excres_cd_total: Optional[float] = None
    excres_f_total: Optional[float] = None

    # Labels/echo (nice for reporting)
    labels: Dict[str, str] = Field(default_factory=dict)
    flight_condition: Dict[str, float] = Field(default_factory=dict)

    # Tables
    components: Dict[str, Any]
    excrescence: Dict[str, Any]

    def df_components(self) -> pd.DataFrame:
        return pd.DataFrame(**self.components)

    def df_excrescence(self) -> pd.DataFrame:
        return pd.DataFrame(**self.excrescence)

