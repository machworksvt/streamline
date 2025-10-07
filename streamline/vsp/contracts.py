# streamline/vsp/contracts.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Literal
import pandas as pd
from typing import Any

class VSPStabTicket(BaseModel):
    # ——— What geometry to analyze ———
    set_name: Optional[str] = None        # preferred (e.g., "Shown", "All")
    set_index: Optional[int] = None       # explicit index; wins if populated

    # ——— Configuration to apply before the run ———
    # Values copied from a chosen Configuration at callsite (don’t embed full config object here)
    control_group_deflections_deg: Dict[int, float] = Field(
        default_factory=dict,
        description="Key: ControlSurfaceGroup index, Value: deflection [deg]."
    )
    udp_overrides: Dict[str, float] = Field(
        default_factory=dict,
        description="Parm IDs or Parm-paths -> value (SI)."
    )
    # Optional hinge/payload toggles could be added here later

    # ——— Flight condition (single point) ———
    alpha_deg: float                       # required (single point)
    beta_deg: float = 0.0                  # usually 0 for stab runs
    mach: Optional[float] = None           # preferred if known
    vinf_mps: Optional[float] = None       # or supply flow by velocity/density
    rho_kgpm3: Optional[float] = None
    re_cref: Optional[float] = None        # if you want to set Re explicitly
    mach_ref: Optional[float] = None       # can mirror mach; optional
    vref_mps: Optional[float] = None       # ref speed; set ManualVrefFlag if used

    # ——— Mass / CG (reference for moments) ———
    xcg_m: Optional[float] = None
    ycg_m: Optional[float] = None
    zcg_m: Optional[float] = None

    # ——— Reference quantity policy ———
    ref_flag: Optional[int] = None         # leave None to use OpenVSP default
    mac_flag: Optional[int] = None         # 0: Cave, 1: MAC
    scurve_flag: Optional[int] = None      # 0: Stot, 1: Scurve

    # ——— Solver knobs ———
    analysis_method: Literal["VLM"] = "VLM"    # thin-surface method
    unsteady_type: Literal["STABILITY_DEFAULT"] = "STABILITY_DEFAULT"
    ncpu: Optional[int] = None
    redirect_file: Optional[str] = "stdout"    # "stdout" to mirror in console


class VSPStabReceipt(BaseModel):
    # highlights
    static_margin: Optional[float] = None   # fraction (e.g., 0.12)
    x_np_m: Optional[float] = None

    # base case tables (orient="split")
    base_stab: Dict[str, Any]
    base_body: Dict[str, Any]

    # derivatives
    derivs_stab: Dict[str, Any]
    derivs_body: Dict[str, Any]

    # flight condition as parsed from FC_* and our ticket
    flight_condition: Dict[str, Any]

    # control groups available during the run
    control_groups: List[str]

    # manifest of how we actually ran
    run_manifest: Dict[str, Any]

    # convenience accessors
    def df_base_stab(self) -> pd.DataFrame:  return pd.DataFrame(**self.base_stab)
    def df_base_body(self) -> pd.DataFrame:  return pd.DataFrame(**self.base_body)
    def df_derivs_stab(self) -> pd.DataFrame:return pd.DataFrame(**self.derivs_stab)
    def df_derivs_body(self) -> pd.DataFrame:return pd.DataFrame(**self.derivs_body)