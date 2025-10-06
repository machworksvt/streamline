# streamline/vsp/analyses/parasite_drag.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from ...core.schema import Configuration, OperatingPoint
from ..configure import AppliedConfiguration, apply_configuration
from ..operating_point import AppliedOperatingPoint, apply_operating_point
from ..errors import VSPMissingResults
from ..sets import choose_populated_set
from ..util import as_list, apply_udp_overrides
from ..contracts.parasite_drag import ParasiteDragTicket, ParasiteDragPayload

_ANALYSIS_KEY = "parasite_drag"


def _gd(vsp, rid, name) -> List[float]:
    try:
        vals = vsp.GetDoubleResults(rid, name)
        return [float(x) for x in vals] if vals else []
    except Exception:
        return []


def _gs(vsp, rid, name) -> List[str]:
    try:
        vals = vsp.GetStringResults(rid, name)
        return [str(x) for x in vals] if vals else []
    except Exception:
        return []


def _g1d(vsp, rid, name) -> Optional[float]:
    vals = _gd(vsp, rid, name)
    return vals[0] if vals else None


def _apply_operating_point(
    operating_point: Optional[OperatingPoint],
    applied_operating_point: Optional[AppliedOperatingPoint],
) -> Optional[AppliedOperatingPoint]:
    if operating_point is not None and applied_operating_point is not None:
        raise ValueError("Provide either operating_point or applied_operating_point, not both.")
    if operating_point is not None:
        return apply_operating_point(operating_point)
    return applied_operating_point


def _resolve_set_index(
    vsp,
    ticket: ParasiteDragTicket,
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


def run_parasite_drag(
    vsp,
    ticket: ParasiteDragTicket,
    configuration: Optional[Configuration] = None,
    applied_configuration: Optional[AppliedConfiguration] = None,
    operating_point: Optional[OperatingPoint] = None,
    applied_operating_point: Optional[AppliedOperatingPoint] = None) -> ParasiteDragPayload:
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

    parm_overrides: Dict[str, float] = {}
    if applied_cfg and applied_cfg.parm_overrides:
        parm_overrides.update(applied_cfg.parm_overrides)
    if ticket.udp_overrides:
        parm_overrides.update(ticket.udp_overrides)
    if ticket.runtime_overrides:
        parm_overrides.update(ticket.runtime_overrides)
    if parm_overrides:
        apply_udp_overrides(vsp, parm_overrides)

    analysis = "ParasiteDrag"
    vsp.SetAnalysisInputDefaults(analysis)

    resolved_set_idx = set_idx if set_idx is not None else choose_populated_set(vsp)
    vsp.SetIntAnalysisInput(analysis, "GeomSet", as_list(int(resolved_set_idx)))
    if use_mode_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "UseModeFlag", as_list(int(1 if use_mode_flag else 0)))
    if mode_id is not None:
        vsp.SetStringAnalysisInput(analysis, "ModeID", as_list(mode_id))

    altitude = ticket.altitude_m if ticket.altitude_m is not None else (applied_op.altitude_m if applied_op else None)
    if altitude is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Altitude", as_list(float(altitude)))

    if ticket.delta_temp_K is not None:
        vsp.SetDoubleAnalysisInput(analysis, "DeltaTemp", as_list(float(ticket.delta_temp_K)))

    density = ticket.rho_kgpm3
    if density is None and applied_op and "rho" in applied_op.atmosphere_overrides:
        density = applied_op.atmosphere_overrides["rho"]
    if density is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Density", as_list(float(density)))

    if ticket.pressure_Pa is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Pressure", as_list(float(ticket.pressure_Pa)))
    if ticket.temperature_K is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Temperature", as_list(float(ticket.temperature_K)))

    mach_value = ticket.mach if ticket.mach is not None else (applied_op.mach if applied_op else None)
    if mach_value is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Mach", as_list(float(mach_value)))
    else:
        vinf_value = ticket.vinf_mps if getattr(ticket, "vinf_mps", None) is not None else (applied_op.tas_mps if applied_op else None)
        if vinf_value is not None:
            vsp.SetDoubleAnalysisInput(analysis, "Vinf", as_list(float(vinf_value)))

    if ticket.dynamic_visc_Pas is not None:
        vsp.SetDoubleAnalysisInput(analysis, "DynaVisc", as_list(float(ticket.dynamic_visc_Pas)))
    if ticket.kinematic_visc_m2ps is not None:
        vsp.SetDoubleAnalysisInput(analysis, "KineVisc", as_list(float(ticket.kinematic_visc_m2ps)))
    if ticket.re_per_length is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Re_L", as_list(float(ticket.re_per_length)))
    if ticket.specific_heat_ratio is not None:
        vsp.SetDoubleAnalysisInput(analysis, "SpecificHeatRatio", as_list(float(ticket.specific_heat_ratio)))

    if ticket.length_unit is not None:
        vsp.SetIntAnalysisInput(analysis, "LengthUnit", as_list(int(ticket.length_unit)))
    if ticket.alt_length_unit is not None:
        vsp.SetIntAnalysisInput(analysis, "AltLengthUnit", as_list(int(ticket.alt_length_unit)))
    if ticket.temp_unit is not None:
        vsp.SetIntAnalysisInput(analysis, "TempUnit", as_list(int(ticket.temp_unit)))
    if ticket.pres_unit is not None:
        vsp.SetIntAnalysisInput(analysis, "PresUnit", as_list(int(ticket.pres_unit)))
    if ticket.velocity_unit is not None:
        vsp.SetIntAnalysisInput(analysis, "VelocityUnit", as_list(int(ticket.velocity_unit)))

    if ticket.lam_cf_eqn_choice is not None:
        vsp.SetIntAnalysisInput(analysis, "LamCfEqnChoice", as_list(int(ticket.lam_cf_eqn_choice)))
    if ticket.turb_cf_eqn_choice is not None:
        vsp.SetIntAnalysisInput(analysis, "TurbCfEqnChoice", as_list(int(ticket.turb_cf_eqn_choice)))

    if ticket.ref_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "RefFlag", as_list(int(ticket.ref_flag)))
    if ticket.sref_m2 is not None:
        vsp.SetDoubleAnalysisInput(analysis, "Sref", as_list(float(ticket.sref_m2)))
    if ticket.wing_id is not None:
        vsp.SetStringAnalysisInput(analysis, "WingID", as_list(ticket.wing_id))

    if ticket.freestream_prop_choice is not None:
        vsp.SetIntAnalysisInput(analysis, "FreestreamPropChoice", as_list(int(ticket.freestream_prop_choice)))

    if ticket.recompute_geom is not None:
        vsp.SetIntAnalysisInput(analysis, "RecomputeGeom", as_list(1 if ticket.recompute_geom else 0))

    if ticket.export_subcomp_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "ExportSubCompFlag", as_list(int(ticket.export_subcomp_flag)))
    if ticket.file_name:
        vsp.SetStringAnalysisInput(analysis, "FileName", as_list(ticket.file_name))

    vsp.Update()
    vsp.ExecAnalysis(analysis)
    res_id = vsp.FindLatestResultsID("Parasite_Drag")
    if not res_id:
        raise VSPMissingResults("Parasite_Drag")

    total_cd = _g1d(vsp, res_id, "Total_CD_Total")
    total_f = _g1d(vsp, res_id, "Total_f_Total")
    geom_cd_total = _g1d(vsp, res_id, "Geom_CD_Total")
    geom_f_total = _g1d(vsp, res_id, "Geom_f_Total")
    excres_cd_total = _g1d(vsp, res_id, "Excres_CD_Total")
    excres_f_total = _g1d(vsp, res_id, "Excres_f_Total")

    labels: Dict[str, str] = {}
    for key in [
        "Alt_Label",
        "Pres_Label",
        "Rho_Label",
        "Temp_Label",
        "Sref_Label",
        "Swet_Label",
        "Vinf_Label",
        "Lref_Label",
        "f_Label",
        "LamCfEqnName",
        "TurbCfEqnName",
    ]:
        s = _gs(vsp, res_id, key)
        if s:
            labels[key] = s[0]

    flight_condition: Dict[str, float] = {}
    for key in [
        "FC_Alt",
        "FC_Mach",
        "FC_Pres",
        "FC_Rho",
        "FC_Sref",
        "FC_Temp",
        "FC_Vinf",
        "FC_dTemp",
    ]:
        val = _g1d(vsp, res_id, key)
        if val is not None:
            flight_condition[key] = val

    comp_cols = {
        "Comp_ID": "id",
        "Comp_Label": "label",
        "Comp_SurfNum": "surf_num",
        "Comp_Lref": "L_ref",
        "Comp_FineRat": "fineness_or_tc",
        "Comp_Roughness": "roughness",
        "Comp_PercLam": "perc_laminar",
        "Comp_Q": "interference_Q",
        "Comp_Re": "Re",
        "Comp_TawTwRatio": "Taw_Tw",
        "Comp_TeTwRatio": "Te_Tw",
        "Comp_Swet": "S_wet",
        "Comp_Cf": "Cf",
        "Comp_FFEqn": "FF_eqn",
        "Comp_FFEqnName": "FF_eqn_name",
        "Comp_FFIn": "FF_in",
        "Comp_FFOut": "FF_out",
        "Comp_f": "f",
        "Comp_CD": "CD",
        "Comp_PercTotalCD": "perc_total_cd",
    }
    comp_data: Dict[str, List[Any]] = {}
    for raw_name, alias in comp_cols.items():
        vals_s = _gs(vsp, res_id, raw_name)
        vals_d = _gd(vsp, res_id, raw_name)
        comp_data[alias] = vals_s if vals_s else vals_d
    max_comp = max((len(v) for v in comp_data.values()), default=0)
    for key, values in comp_data.items():
        if len(values) < max_comp:
            comp_data[key] = values + [None] * (max_comp - len(values))
    components_df = pd.DataFrame(comp_data)

    exc_cols = {
        "Excres_Type": "type",
        "Excres_Label": "label",
        "Excres_Input": "input_value",
        "Excres_Amount": "amount",
        "Excres_f": "f",
        "Excres_CD_Total": "cd_total",
        "Excres_PercTotalCD": "perc_total_cd",
        "Excres_f_Total": "f_total",
        "Excres_Perc_Total": "perc_total",
    }
    exc_data: Dict[str, List[Any]] = {}
    for raw_name, alias in exc_cols.items():
        vals_s = _gs(vsp, res_id, raw_name)
        vals_d = _gd(vsp, res_id, raw_name)
        exc_data[alias] = vals_s if vals_s else vals_d
    max_exc = max((len(v) for v in exc_data.values()), default=0)
    for key, values in exc_data.items():
        if len(values) < max_exc:
            exc_data[key] = values + [None] * (max_exc - len(values))
    exc_df = pd.DataFrame(exc_data)

    op_summary = applied_op.to_summary() if applied_op else {}
    applied_var_presets = applied_cfg.applied_var_presets if applied_cfg else []

    totals_payload = {
        "total_cd": total_cd,
        "total_f": total_f,
        "geom_cd_total": geom_cd_total,
        "geom_f_total": geom_f_total,
        "excres_cd_total": excres_cd_total,
        "excres_f_total": excres_f_total,
    }

    return ParasiteDragPayload(
        analysis_name=analysis,
        set_index=resolved_set_idx,
        set_name=set_name,
        mode_id=mode_id,
        use_mode_flag=use_mode_flag,
        applied_var_presets=list(applied_var_presets),
        parm_overrides=dict(parm_overrides),
        operating_point=op_summary,
        results_id=res_id,
        totals=totals_payload,
        labels=labels,
        flight_condition=flight_condition,
        components=components_df,
        excrescence=exc_df,
    )
