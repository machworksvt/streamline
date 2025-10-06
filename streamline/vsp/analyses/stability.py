# streamline/vsp/analyses/stability.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from ...core.schema import Configuration, OperatingPoint
from ..configure import AppliedConfiguration, apply_configuration
from ..operating_point import AppliedOperatingPoint, apply_operating_point
from ..errors import VSPMissingResults
from ..util import (
    as_list,
    apply_control_deflections,
    apply_udp_overrides,
    get_control_group_names,
)
from ..sets import choose_populated_set
from ..contracts.stability import StabilityTicket, StabilityPayload
from ..contracts.compute_geometry import ComputeGeometryTicket
from .compute_geometry import run_compute_geometry


_STAB_AXES = ["CD", "CS", "CL", "CMl", "CMm", "CMn"]
_BODY_AXES = ["CFx", "CFy", "CFz", "CMx", "CMy", "CMz"]
_RATE_COLS = ["alpha", "beta", "p", "q", "r", "U", "Mach"]
_OUT_TO_VSP = {"CD": "CD", "CS": "CS", "CL": "CL", "Cl": "CMl", "Cm": "CMm", "Cn": "CMn"}
_ANALYSIS_KEY = "vspaero_stability"


def _resolve_set_index(
    vsp,
    ticket: StabilityTicket,
    applied_cfg: Optional[AppliedConfiguration],
) -> Optional[int]:
    if ticket.set_index is not None:
        return int(ticket.set_index)
    if applied_cfg and applied_cfg.geom_set_index is not None:
        return int(applied_cfg.geom_set_index)

    candidates: List[str] = []
    if ticket.set_name:
        candidates.append(ticket.set_name)
    if applied_cfg and applied_cfg.geom_set_name:
        candidates.append(applied_cfg.geom_set_name)

    try:
        mapping = {i: vsp.GetSetName(i) for i in range(vsp.GetNumSets())}
    except Exception:
        mapping = {}

    for candidate in candidates:
        if not candidate:
            continue
        for idx, name in mapping.items():
            if name and name.lower() == candidate.lower():
                return idx

    try:
        return choose_populated_set(vsp)
    except Exception:
        return None


def _resolve_set_name(
    vsp,
    set_idx: Optional[int],
    applied_cfg: Optional[AppliedConfiguration],
) -> Optional[str]:
    if set_idx is None:
        return applied_cfg.geom_set_name if applied_cfg else None
    if applied_cfg and applied_cfg.geom_set_index == set_idx and applied_cfg.geom_set_name:
        return applied_cfg.geom_set_name
    try:
        return vsp.GetSetName(int(set_idx))
    except Exception:
        return applied_cfg.geom_set_name if applied_cfg else None


def _apply_operating_point(
    operating_point: Optional[OperatingPoint],
    applied_operating_point: Optional[AppliedOperatingPoint],
) -> Optional[AppliedOperatingPoint]:
    if operating_point is not None and applied_operating_point is not None:
        raise ValueError("Provide either operating_point or applied_operating_point, not both.")
    if operating_point is not None:
        return apply_operating_point(operating_point)
    return applied_operating_point


def run_stability(
    vsp,
    ticket: StabilityTicket,
    configuration: Optional[Configuration] = None,
    applied_configuration: Optional[AppliedConfiguration] = None,
    operating_point: Optional[OperatingPoint] = None,
    applied_operating_point: Optional[AppliedOperatingPoint] = None) -> StabilityPayload:
    if configuration is not None and applied_configuration is not None:
        raise ValueError("Provide either configuration or applied_configuration, not both.")

    applied_cfg = applied_configuration
    if configuration is not None:
        applied_cfg = apply_configuration(
            vsp,
            configuration,
            fallback_set_index=ticket.set_index,
            fallback_set_name=ticket.set_name,
        )

    applied_op = _apply_operating_point(operating_point, applied_operating_point)

    config_id = ticket.config_id or (
        applied_cfg.config_id if applied_cfg and applied_cfg.config_id is not None else (configuration.config_id if configuration else None)
    )

    mode_id = ticket.mode_id or (applied_cfg.mode_id if applied_cfg else None)
    use_mode_flag = (
        ticket.use_mode_flag
        if ticket.use_mode_flag is not None
        else (applied_cfg.use_mode_flag if applied_cfg and applied_cfg.use_mode_flag is not None else None)
    )

    if applied_cfg is None and mode_id:
        try:
            vsp.ApplyModeSettings(mode_id)
        except Exception:
            mode_id = None
            use_mode_flag = None

    set_idx = _resolve_set_index(vsp, ticket, applied_cfg)
    set_name = _resolve_set_name(vsp, set_idx, applied_cfg)

    apply_control_deflections(vsp, ticket.control_group_deflections_deg)

    parm_overrides: Dict[str, float] = {}
    if applied_cfg and applied_cfg.parm_overrides:
        parm_overrides.update(applied_cfg.parm_overrides)
    if ticket.udp_overrides:
        parm_overrides.update(ticket.udp_overrides)
    if ticket.runtime_overrides:
        parm_overrides.update(ticket.runtime_overrides)
    if parm_overrides:
        apply_udp_overrides(vsp, parm_overrides)

    cg_ticket = ComputeGeometryTicket(
        config_id=config_id,
        mode_id=mode_id,
        use_mode_flag=use_mode_flag,
        set_index=set_idx,
        set_name=set_name,
        analysis_method="VLM",
    )
    run_compute_geometry(
        vsp,
        cg_ticket,
        configuration=None,
        applied_configuration=applied_cfg,
    )

    analysis = "VSPAEROSweep"
    vsp.SetAnalysisInputDefaults(analysis)

    resolved_set_idx = set_idx if set_idx is not None else choose_populated_set(vsp)
    vsp.SetIntAnalysisInput(analysis, "GeomSet", as_list(int(resolved_set_idx)))
    if hasattr(vsp, "STABILITY_DEFAULT"):
        vsp.SetIntAnalysisInput(analysis, "UnsteadyType", as_list(int(vsp.STABILITY_DEFAULT)))
    if hasattr(vsp, "VORTEX_LATTICE"):
        vsp.SetIntAnalysisInput(analysis, "AnalysisMethod", as_list(int(vsp.VORTEX_LATTICE)))

    if use_mode_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "UseModeFlag", as_list(int(1 if use_mode_flag else 0)))
    if mode_id is not None:
        vsp.SetStringAnalysisInput(analysis, "ModeID", as_list(mode_id))

    ncpu = ticket.ncpu if ticket.ncpu else max(1, (os.cpu_count() or 4))
    vsp.SetIntAnalysisInput(analysis, "NCPU", as_list(int(ncpu)))
    if ticket.redirect_file is not None:
        vsp.SetStringAnalysisInput(analysis, "RedirectFile", as_list(ticket.redirect_file))

    op_mach = applied_op.mach if applied_op else None
    op_vinf = applied_op.tas_mps if applied_op else None

    mach_value = ticket.mach if ticket.mach is not None else op_mach
    if mach_value is not None:
        vsp.SetDoubleAnalysisInput(analysis, "MachStart", as_list(float(mach_value)))
        vsp.SetDoubleAnalysisInput(analysis, "MachEnd", as_list(float(mach_value)))
        vsp.SetIntAnalysisInput(analysis, "MachNpts", as_list(1))
        vsp.SetDoubleAnalysisInput(analysis, "Machref", as_list(float(ticket.mach_ref or mach_value)))
    elif ticket.vinf_mps is not None or op_vinf is not None:
        vinf = ticket.vinf_mps if ticket.vinf_mps is not None else op_vinf
        if vinf is not None:
            vsp.SetDoubleAnalysisInput(analysis, "Vinf", as_list(float(vinf)))
            vsp.SetDoubleAnalysisInput(analysis, "Vref", as_list(float(ticket.vref_mps or vinf)))
            if ticket.vref_mps is not None:
                vsp.SetIntAnalysisInput(analysis, "ManualVrefFlag", as_list(1))

    vsp.SetDoubleAnalysisInput(analysis, "AlphaStart", as_list(float(ticket.alpha_deg)))
    vsp.SetDoubleAnalysisInput(analysis, "AlphaEnd", as_list(float(ticket.alpha_deg)))
    vsp.SetIntAnalysisInput(analysis, "AlphaNpts", as_list(1))

    vsp.SetDoubleAnalysisInput(analysis, "BetaStart", as_list(float(ticket.beta_deg)))
    vsp.SetDoubleAnalysisInput(analysis, "BetaEnd", as_list(float(ticket.beta_deg)))
    vsp.SetIntAnalysisInput(analysis, "BetaNpts", as_list(1))

    if ticket.rho_kgpm3 is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Rho", as_list(float(ticket.rho_kgpm3)))
    if ticket.re_cref is not None:
        vsp.SetDoubleAnalysisInput(analysis, "ReCref", as_list(float(ticket.re_cref)))
        vsp.SetDoubleAnalysisInput(analysis, "ReCrefEnd", as_list(float(ticket.re_cref)))
        vsp.SetIntAnalysisInput(analysis, "ReCrefNpts", as_list(1))

    if ticket.xcg_m is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Xcg", as_list(float(ticket.xcg_m)))
    if ticket.ycg_m is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Ycg", as_list(float(ticket.ycg_m)))
    if ticket.zcg_m is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Zcg", as_list(float(ticket.zcg_m)))
    if ticket.ref_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "RefFlag", as_list(int(ticket.ref_flag)))
    if ticket.mac_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "MACFlag", as_list(int(ticket.mac_flag)))
    if ticket.scurve_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "ScurveFlag", as_list(int(ticket.scurve_flag)))

    vsp.Update()
    rid = vsp.ExecAnalysis(analysis)
    stab_id = vsp.FindLatestResultsID("VSPAERO_Stab")
    if not stab_id:
        raise VSPMissingResults("VSPAERO_Stab")

    try:
        sm = float(vsp.GetDoubleResults(stab_id, "SM")[0])
    except Exception:
        sm = None
    try:
        xnp = float(vsp.GetDoubleResults(stab_id, "X_np")[0])
    except Exception:
        xnp = None

    base_stab_df = pd.DataFrame(columns=["CD", "CS", "CL", "Cl", "Cm", "Cn"], dtype=float)
    name_map_stab = {
        "CD": "Base_Aero_CD",
        "CS": "Base_Aero_CS",
        "CL": "Base_Aero_CL",
        "Cl": "Base_Aero_CMl",
        "Cm": "Base_Aero_CMm",
        "Cn": "Base_Aero_CMn",
    }
    row = {}
    for key, result_name in name_map_stab.items():
        try:
            vals = vsp.GetDoubleResults(stab_id, result_name)
            row[key] = float(vals[0]) if vals else float("nan")
        except Exception:
            row[key] = float("nan")
    base_stab_df.loc[0] = row

    base_body_df = pd.DataFrame(columns=_BODY_AXES, dtype=float)
    row_body = {}
    for axis in _BODY_AXES:
        try:
            vals = vsp.GetDoubleResults(stab_id, f"Base_Aero_{axis}")
            row_body[axis] = float(vals[0]) if vals else float("nan")
        except Exception:
            row_body[axis] = float("nan")
    base_body_df.loc[0] = row_body

    control_names = get_control_group_names(vsp)
    deriv_cols = _RATE_COLS + control_names

    derivs_stab_df = pd.DataFrame(index=["CD", "CS", "CL", "Cl", "Cm", "Cn"], columns=deriv_cols, dtype=float)
    for out in derivs_stab_df.index:
        out_name = _OUT_TO_VSP[out]
        for inn in _RATE_COLS:
            vname = f"{out_name}_{inn if inn not in ['alpha', 'beta'] else inn.capitalize()}"
            try:
                vals = vsp.GetDoubleResults(stab_id, vname)
                derivs_stab_df.loc[out, inn] = float(vals[0]) if vals else float("nan")
            except Exception:
                derivs_stab_df.loc[out, inn] = float("nan")
        for cname in control_names:
            vname = f"{out_name}_{cname}"
            try:
                vals = vsp.GetDoubleResults(stab_id, vname)
                derivs_stab_df.loc[out, cname] = float(vals[0]) if vals else float("nan")
            except Exception:
                derivs_stab_df.loc[out, cname] = float("nan")

    derivs_body_df = pd.DataFrame(index=_BODY_AXES, columns=deriv_cols, dtype=float)
    for out in derivs_body_df.index:
        for inn in _RATE_COLS:
            vname = f"{out}_{inn if inn not in ['alpha', 'beta'] else inn.capitalize()}"
            try:
                vals = vsp.GetDoubleResults(stab_id, vname)
                derivs_body_df.loc[out, inn] = float(vals[0]) if vals else float("nan")
            except Exception:
                derivs_body_df.loc[out, inn] = float("nan")
        for cname in control_names:
            vname = f"{out}_{cname}"
            try:
                vals = vsp.GetDoubleResults(stab_id, vname)
                derivs_body_df.loc[out, cname] = float(vals[0]) if vals else float("nan")
            except Exception:
                derivs_body_df.loc[out, cname] = float("nan")

    flight_condition: Dict[str, Any] = {}
    for key in [
        "FC_AoA_",
        "FC_Beta_",
        "FC_Mach_",
        "FC_Vinf_",
        "FC_Rho_",
        "FC_Sref_",
        "FC_Bref_",
        "FC_Cref_",
        "FC_Xcg_",
        "FC_Ycg_",
        "FC_Zcg_",
    ]:
        try:
            vals = vsp.GetDoubleResults(stab_id, key)
            if vals:
                flight_condition[key] = float(vals[0])
                continue
        except Exception:
            pass
        try:
            sval = vsp.GetStringResults(stab_id, key)
            if sval:
                flight_condition[key] = sval[0]
        except Exception:
            pass

    op_summary = applied_op.to_summary() if applied_op else {}

    applied_var_presets = applied_cfg.applied_var_presets if applied_cfg else []

    return StabilityPayload(
        analysis_name=analysis,
        set_index=resolved_set_idx,
        set_name=set_name,
        mode_id=mode_id,
        use_mode_flag=use_mode_flag,
        applied_var_presets=list(applied_var_presets),
        parm_overrides=dict(parm_overrides),
        operating_point=op_summary,
        results_id=stab_id,
        static_margin=sm,
        x_np_m=xnp,
        flight_condition=flight_condition,
        control_groups=control_names,
        base_stab=base_stab_df,
        base_body=base_body_df,
        derivs_stab=derivs_stab_df,
        derivs_body=derivs_body_df,
        ncpu=ncpu,
    )




