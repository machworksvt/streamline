# streamline/vsp/analyses/comp_geom.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from ...core.schema import Configuration, RunManifest
from ...io.results_index import ResultIndexEntry, append_result_entry
from ..configure import AppliedConfiguration, apply_configuration
from ..run_utils import dump_json, prepare_results_dir, relativize
from ..util import as_list, apply_udp_overrides
from ..results import dump_available, get as get_result
from ..contracts.comp_geom import CompGeomTicket, CompGeomPayload, CompGeomReceipt
from ._set_utils import resolve_set_index, resolve_set_name

if TYPE_CHECKING:
    from ...analysis.manager import AnalysisJob, AnalysisManager


def _normalize_export_mask(value: Optional[int | list[int]]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    mask = 0
    for item in value:
        try:
            mask |= int(item)
        except Exception:
            continue
    return mask if mask else None


def _set_int_input(vsp, analysis: str, name: str, value: int) -> bool:
    try:
        vsp.SetIntAnalysisInput(analysis, name, as_list(int(value)))
        return True
    except Exception:
        return False


def _set_bool_input(vsp, analysis: str, name: str, flag: Optional[bool]) -> None:
    if flag is None:
        return
    _set_int_input(vsp, analysis, name, 1 if flag else 0)


def _coerce_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): _coerce_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_value(v) for v in value]
    try:
        return float(value)
    except Exception:
        return str(value)


def _extract_scalar(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and len(value) == 1:
        elem = value[0]
        if isinstance(elem, (int, float)):
            return float(elem)
    return None


def run_comp_geom(
    vsp,
    ticket: CompGeomTicket,
    configuration: Optional[Configuration] = None,
    applied_configuration: Optional[AppliedConfiguration] = None,
) -> CompGeomPayload:
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

    set_idx = resolve_set_index(vsp, ticket, applied_cfg)
    set_name = resolve_set_name(vsp, set_idx, applied_cfg)

    parm_overrides: Dict[str, float] = {}
    if applied_cfg and applied_cfg.parm_overrides:
        parm_overrides.update(applied_cfg.parm_overrides)
    if ticket.udp_overrides:
        parm_overrides.update(ticket.udp_overrides)
    if ticket.runtime_overrides:
        parm_overrides.update(ticket.runtime_overrides)
    if parm_overrides:
        apply_udp_overrides(vsp, parm_overrides)

    analysis = "CompGeom"
    vsp.SetAnalysisInputDefaults(analysis)

    if set_idx is not None:
        if not _set_int_input(vsp, analysis, "Set", int(set_idx)):
            _set_int_input(vsp, analysis, "GeomSet", int(set_idx))

    _set_bool_input(vsp, analysis, "HalfMeshFlag", ticket.half_mesh_flag)

    file_export_mask = _normalize_export_mask(ticket.file_export_types)
    if file_export_mask is not None:
        for name in ("FileExportFlags", "FileExportTypes", "ExportFileFlag"):
            if _set_int_input(vsp, analysis, name, file_export_mask):
                break

    if ticket.write_csv_flag is not None:
        _set_bool_input(vsp, analysis, "WriteCSVFlag", ticket.write_csv_flag)

    for flag_name, enabled in (ticket.write_flags or {}).items():
        if isinstance(enabled, bool):
            _set_bool_input(vsp, analysis, flag_name, enabled)

    vsp.Update()
    results_id = vsp.ExecAnalysis(analysis)

    available = dump_available(vsp, results_id)
    results_data: Dict[str, Any] = {}
    summary: Dict[str, float] = {}
    mesh_geom_ids: list[str] = []

    for name in available:
        try:
            raw = get_result(vsp, results_id, name)
        except Exception:
            continue
        coerced = _coerce_value(raw)
        results_data[name] = coerced
        scalar = _extract_scalar(coerced)
        if scalar is not None:
            summary[name] = scalar
        if name == "Mesh_GeomID":
            if isinstance(coerced, list):
                mesh_geom_ids = [str(item) for item in coerced if isinstance(item, str)]

    if ticket.cleanup_mesh_geoms and mesh_geom_ids:
        try:
            vsp.DeleteGeomVec(mesh_geom_ids)
        except Exception:
            pass

    try:
        vsp.ClearResults(results_id)
    except Exception:
        pass

    applied_var_presets = applied_cfg.applied_var_presets if applied_cfg else []

    return CompGeomPayload(
        analysis_name=analysis,
        set_index=set_idx,
        set_name=set_name,
        half_mesh_flag=ticket.half_mesh_flag,
        write_csv_flag=ticket.write_csv_flag,
        file_export_mask=file_export_mask,
        results_available=available,
        summary=summary,
        results_data=results_data,
        mesh_geom_ids=mesh_geom_ids,
        applied_var_presets=list(applied_var_presets),
        parm_overrides=dict(parm_overrides),
    )


def _materialize_comp_geom(
    manager: "AnalysisManager",
    job: "AnalysisJob",
    ticket_sha: str,
    payload: CompGeomPayload,
    started: datetime,
    ended: datetime,
) -> CompGeomReceipt:
    if not isinstance(payload, CompGeomPayload):
        raise TypeError(f"Expected CompGeomPayload, got {type(payload).__name__}")

    results_root = manager.results_root
    artifacts: Dict[str, str] = {}
    artifact_dir_rel: Optional[str] = None
    artifact_dir_path: Optional[Path] = None

    settings: Dict[str, Any] = {
        "analysis": payload.analysis_name,
        "set_index": payload.set_index,
        "set_name": payload.set_name,
        "half_mesh_flag": payload.half_mesh_flag,
        "write_csv_flag": payload.write_csv_flag,
        "file_export_mask": payload.file_export_mask,
        "applied_var_presets": payload.applied_var_presets,
        "parm_overrides": payload.parm_overrides,
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

        results_blob = {
            "available": payload.results_available,
            "summary": payload.summary,
            "data": payload.results_data,
        }
        dump_json(run_dir / "results.json", results_blob)
        artifacts["results_json"] = relativize(run_dir / "results.json", results_root)

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
                summary=dict(sorted(payload.summary.items())),
                manifest=manifest,
            ),
        )

    return CompGeomReceipt(
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=artifact_dir_rel,
        artifacts=artifacts,
        settings=settings,
        summary=dict(payload.summary),
        available_results=dict(payload.results_available),
    )
