# streamline/vsp/contracts/stability.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal, Tuple

import pandas as pd
from pydantic import Field

from .base import Ticket, Receipt


class StabilityTicket(Ticket):
    # flight condition (single point in stability mode)
    alpha_deg: float
    beta_deg: float = 0.0
    mach: Optional[float] = None
    vinf_mps: Optional[float] = None
    rho_kgpm3: Optional[float] = None
    re_cref: Optional[float] = None
    mach_ref: Optional[float] = None
    vref_mps: Optional[float] = None  # if set, ManualVrefFlag=1

    # CG / ref options
    xcg_m: Optional[float] = None
    ycg_m: Optional[float] = None
    zcg_m: Optional[float] = None
    ref_flag: Optional[int] = None
    mac_flag: Optional[int] = None
    scurve_flag: Optional[int] = None

    # solver setup
    analysis_method: Literal["VLM"] = "VLM"
    unsteady_type: Literal["STABILITY_DEFAULT"] = "STABILITY_DEFAULT"
    ncpu: Optional[int] = None
    redirect_file: Optional[str] = "stdout"


@dataclass
class StabilityPayload:
    analysis_name: str
    set_index: Optional[int]
    set_name: Optional[str]
    mode_id: Optional[str]
    use_mode_flag: Optional[bool]
    applied_var_presets: List[Tuple[str, str]] = field(default_factory=list)
    parm_overrides: Dict[str, float] = field(default_factory=dict)
    operating_point: Dict[str, Any] = field(default_factory=dict)
    results_id: Optional[str] = None
    static_margin: Optional[float] = None
    x_np_m: Optional[float] = None
    flight_condition: Dict[str, Any] = field(default_factory=dict)
    control_groups: List[str] = field(default_factory=list)
    base_stab: Optional[pd.DataFrame] = None
    base_body: Optional[pd.DataFrame] = None
    derivs_stab: Optional[pd.DataFrame] = None
    derivs_body: Optional[pd.DataFrame] = None
    ncpu: Optional[int] = None


class StabilityReceipt(Receipt):
    vsp_results_id: Optional[str] = None
    static_margin: Optional[float] = None
    x_np_m: Optional[float] = None

    base_stab: Dict[str, Any]
    base_body: Dict[str, Any]
    derivs_stab: Dict[str, Any]
    derivs_body: Dict[str, Any]

    flight_condition: Dict[str, Any]
    control_groups: List[str]
    operating_point: Dict[str, Any] = Field(default_factory=dict)

    # convenience
    def df_base_stab(self) -> pd.DataFrame:
        return pd.DataFrame(**self.base_stab)

    def df_base_body(self) -> pd.DataFrame:
        return pd.DataFrame(**self.base_body)

    def df_derivs_stab(self) -> pd.DataFrame:
        return pd.DataFrame(**self.derivs_stab)

    def df_derivs_body(self) -> pd.DataFrame:
        return pd.DataFrame(**self.derivs_body)
