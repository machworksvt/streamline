# streamline/vsp/analyses/compute_geometry.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from ...core.schema import Configuration, RunManifest
from ...io.results_index import ResultIndexEntry, append_result_entry
from ..configure import AppliedConfiguration, apply_configuration
from ..util import as_list, apply_udp_overrides
from ..contracts.compute_geometry import (
    ComputeGeometryTicket,
    ComputeGeometryPayload,
    ComputeGeometryReceipt,
)
from ..run_utils import dump_json, prepare_results_dir, relativize
from ._set_utils import resolve_set_index, resolve_set_name

if TYPE_CHECKING:
    from ...analysis.manager import AnalysisJob, AnalysisManager


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

    set_idx = resolve_set_index(vsp, ticket, applied_cfg)
    set_name = resolve_set_name(vsp, set_idx, applied_cfg)

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





def _materialize_compute_geometry(
    manager: 'AnalysisManager',
    job: 'AnalysisJob',
    ticket_sha: str,
    payload: ComputeGeometryPayload,
    started: datetime,
    ended: datetime,
) -> ComputeGeometryReceipt:
    if not isinstance(payload, ComputeGeometryPayload):
        raise TypeError("Expected ComputeGeometryPayload, got {}".format(type(payload).__name__))

    results_root = manager.results_root
    artifacts: Dict[str, str] = {}
    artifact_dir_rel: Optional[str] = None
    artifact_dir_path: Optional[Path] = None

    settings = {
        "analysis": payload.analysis_name,
        "analysis_method": payload.analysis_method,
        "set_index": payload.set_index,
        "set_name": payload.set_name,
        "mode_id": payload.mode_id,
        "use_mode_flag": payload.use_mode_flag,
        "applied_var_presets": payload.applied_var_presets,
        "parm_overrides": payload.parm_overrides,
        "symmetry": payload.symmetry,
        "alternate_input_format_flag": payload.alternate_input_format_flag,
    }

    if results_root is not None:
        run_dir = prepare_results_dir(results_root, job.analysis_key, ticket_sha, started)
        artifact_dir_path = run_dir
        artifact_dir_rel = relativize(run_dir, results_root)

        ticket_payload = json.loads(job.ticket.model_dump_json(exclude_none=True, exclude_defaults=False))
        dump_json(run_dir / "ticket.json", ticket_payload)
        artifacts["ticket_json"] = relativize(run_dir / "ticket.json", results_root)

        dump_json(run_dir / "settings.json", settings)
        artifacts["settings_json"] = relativize(run_dir / "settings.json", results_root)

    manifest = RunManifest(
        tool_versions=manager.versions,
        inputs_sha256=ticket_sha,
        started_utc=started.isoformat(timespec="seconds") + "Z",
        ended_utc=ended.isoformat(timespec="seconds") + "Z",
        source_paths=[artifact_dir_rel] if artifact_dir_rel is not None else [],
    )

    if results_root is not None and artifact_dir_path is not None:
        manifest_path = artifact_dir_path / "run_manifest.json"
        dump_json(manifest_path, manifest.model_dump())
        artifacts["run_manifest_json"] = relativize(manifest_path, results_root)

        append_result_entry(
            results_root.parent,
            ResultIndexEntry(
                analysis=job.analysis_key,
                ticket_sha256=ticket_sha,
                artifact_dir=artifact_dir_rel,
                summary={
                    "set_index": payload.set_index,
                    "set_name": payload.set_name,
                    "mode_id": payload.mode_id,
                    "use_mode_flag": payload.use_mode_flag,
                },
                manifest=manifest,
            ),
        )

    return ComputeGeometryReceipt(
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=artifact_dir_rel,
        artifacts=artifacts,
        settings=settings,
    )
