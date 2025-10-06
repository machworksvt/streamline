# streamline/vsp/analyses/compute_geometry.py
from __future__ import annotations

from typing import Dict, Optional

from ...core.schema import Configuration
from ..configure import AppliedConfiguration, apply_configuration
from ..sets import choose_populated_set
from ..util import as_list, apply_udp_overrides
from ..contracts.compute_geometry import (
    ComputeGeometryTicket,
    ComputeGeometryPayload,
)


def _resolve_set_index(
    vsp,
    ticket: ComputeGeometryTicket,
    applied_cfg: Optional[AppliedConfiguration],
) -> Optional[int]:
    if ticket.set_index is not None:
        return int(ticket.set_index)
    if applied_cfg and applied_cfg.geom_set_index is not None:
        return int(applied_cfg.geom_set_index)

    candidates = []
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


def run_compute_geometry(
    vsp,
    ticket: ComputeGeometryTicket,
    configuration: Optional[Configuration] = None,
    applied_configuration: Optional[AppliedConfiguration] = None,
) -> ComputeGeometryPayload:
    if configuration is not None and applied_configuration is not None:
        raise ValueError("Provide either configuration or applied_configuration, not both.")

    applied_cfg = applied_configuration
    if configuration is not None:
        applied_cfg = apply_configuration(vsp, configuration)

    mode_id = ticket.mode_id or (applied_cfg.mode_id if applied_cfg else None)
    use_mode_flag = (
        ticket.use_mode_flag
        if ticket.use_mode_flag is not None
        else (applied_cfg.use_mode_flag if applied_cfg and applied_cfg.use_mode_flag is not None else None)
    )

    set_idx = _resolve_set_index(vsp, ticket, applied_cfg)
    set_name = _resolve_set_name(vsp, set_idx, applied_cfg)

    analysis = "VSPAEROComputeGeometry"
    vsp.SetAnalysisInputDefaults(analysis)

    if set_idx is not None:
        vsp.SetIntAnalysisInput(analysis, "GeomSet", as_list(int(set_idx)))
    if hasattr(vsp, "VORTEX_LATTICE"):
        vsp.SetIntAnalysisInput(analysis, "AnalysisMethod", as_list(int(vsp.VORTEX_LATTICE)))

    if ticket.symmetry is not None:
        vsp.SetIntAnalysisInput(analysis, "Symmetry", as_list(int(ticket.symmetry)))
    if use_mode_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "UseModeFlag", as_list(int(1 if use_mode_flag else 0)))
    if mode_id is not None:
        vsp.SetStringAnalysisInput(analysis, "ModeID", as_list(mode_id))
    if ticket.alternate_input_format_flag is not None:
        vsp.SetIntAnalysisInput(analysis, "AlternateInputFormatFlag", as_list(int(ticket.alternate_input_format_flag)))

    overrides: Dict[str, float] = {}
    if applied_cfg and applied_cfg.parm_overrides:
        overrides.update(applied_cfg.parm_overrides)
    if ticket.udp_overrides:
        overrides.update(ticket.udp_overrides)
    if ticket.runtime_overrides:
        overrides.update(ticket.runtime_overrides)
    if overrides:
        apply_udp_overrides(vsp, overrides)

    vsp.Update()
    vsp.ExecAnalysis(analysis)

    applied_var_presets = applied_cfg.applied_var_presets if applied_cfg else []

    return ComputeGeometryPayload(
        analysis_name=analysis,
        analysis_method=ticket.analysis_method,
        set_index=set_idx,
        set_name=set_name,
        mode_id=mode_id,
        use_mode_flag=use_mode_flag,
        applied_var_presets=list(applied_var_presets),
        parm_overrides=dict(overrides),
        symmetry=ticket.symmetry,
        alternate_input_format_flag=ticket.alternate_input_format_flag,
    )



