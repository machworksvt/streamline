from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .analysis import AnalysisManager
from .core import (
    ConfigCatalogError,
    LoggingConfig,
    OperatingPointCatalogError,
    StreamlineError,
    get_logger,
    setup_logging,
)
from .core.schema import (
    Configuration,
    MissionDefinition,
    MissionPhase,
    OperatingPoint,
    PowerplantDefinition,
    ProjectDefinition,
    UAVDefinition,
)
from .io.config_catalog import load_config_catalog
from .io.fs import load_config, load_project_def, write_json
from .io.op_catalog import get_operating_point, load_op_catalog
from .io.results_index import load_result_entries
from .tui import StreamlineApp
from .vsp.contracts import ComputeGeometryTicket, ParasiteDragTicket, StabilityTicket
from .vsp.configure import apply_configuration
from .vsp.operating_point import apply_operating_point
from .vsp.session import lock_gui, unlock_gui
from .vsp.sets import list_sets, set_membership_counts, choose_populated_set


logger = get_logger(__name__)


def _log_streamline_error(exc: StreamlineError) -> None:
    logger.error(exc.message, context=exc.context, code=exc.code, hint=exc.hint)


def _log_unhandled_error(exc: Exception, *, context: Optional[Dict[str, str]] = None) -> None:
    logger.exception("Unhandled exception", context=context or {})
# TODO: Add unit tests for CLI commands (using pytest + subprocess)
# TODO: Add end-to-end tests for smoke_run (using pytest + subprocess), and make it headless-friendly by auto-generating the model
# TODO: Validate parasite drag settings cuz the CD0 value is way too low right now
# TODO: Start TUI?
# TODO: Operating points need inertia overrides not just mass
# TODO: Add clear_cache to AnalysisManager and CLI
# TODO: Add the stability reqs to the taxonomy folder
# TODO: Check that I can actually apply control deflections the way I want
# TODO: File outputs for the vsp analyses should be cached, and the files should be in the artifact dir, so they are viewable in case of errors (like what happens if you try transsonic VLM)


"""
    Future Endevors:
    - Automated trim routine (is it possible this isn't compatible with how I'm doing parm overrides? maybe it is?)
    - Unit tests
    - Robust unified logging system, and error reporting/handling
    - The TUI w/ textual
        - Analyis manager queue/history viewer
        - Project browser
        - More robust error handling/logging

"""


# -------------------------
# Utilities
# -------------------------

def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# -------------------------
# Defaults for seed files
# -------------------------

def default_project_json(project_id: str) -> ProjectDefinition:
    return ProjectDefinition(
        project_id=project_id,
        description="New Streamline project",
        aircraft_file=f"{project_id}.vsp3",
        default_set="baseline",
        versions={"streamline_schema": "0.1.0"},
        references={
            "missions": [f"missions/{project_id}_mission.json"],
            "powerplants": [f"powerplants/{project_id}_pp.json"],
            "ops": [f"ops/cruise.json"],
            "configs": [f"configs/clean.json"],
        },
        uav=UAVDefinition(
            uav_id="baseline",
            dod_group="Group 2",
            propulsion_type="electric_prop",
            notes="Edit as needed",
        ),
        control_policy="mirror_openvsp",
        mixing_profiles={},
        notes="",
    )


def default_mission_json(project_id: str) -> MissionDefinition:
    return MissionDefinition(
        mission_id=f"{project_id}_mission",
        phases=[
            MissionPhase(name="takeoff", type="takeoff", targets={"speed_mps": 18.0, "altitude_m": 0.0}),
            MissionPhase(name="climb", type="climb", targets={"ROC_mps": 3.0, "altitude_m": 200.0}),
            MissionPhase(name="cruise", type="cruise", targets={"mach": 0.15, "altitude_m": 200.0}),
            MissionPhase(name="landing", type="landing", targets={"speed_mps": 14.0, "altitude_m": 0.0}),
        ],
        environment={},
        reserves={"time_s": 300},
        objectives={"maximize_range": 1.0},
    )


def default_powerplant_json(project_id: str) -> PowerplantDefinition:
    return PowerplantDefinition(
        powerplant_id=f"{project_id}_pp",
        type="electric_prop",
        maps={"mode": "constant_thrust", "T_N": 10.0},
        dynamics={"tau_s": 0.3},
        limits={"max_thrust_N": 20.0, "min_thrust_N": 0.0, "max_power_W": 800.0},
        energy_model={"battery_Wh": 200.0},
    )


def default_op_json() -> OperatingPoint:
    return OperatingPoint(op_name="cruise", altitude_m=200.0, mach=0.15, notes="Seed cruise point")


def default_config_json() -> Configuration:
    return Configuration(
        config_id="clean",
        geom_set_name="baseline",
        var_presets=[],
        control_surface_groups=[],
        hinges=[],
        payloads_toggle=[],
        udp_overrides={},
        runtime_overrides={},
        notes="Clean configuration",
    )


# -------------------------
# Project creation
# -------------------------

def create_new_project(projects_root: Path, project_id: str) -> Path:
    proj = ensure_dir(projects_root / project_id)
    ensure_dir(proj / "missions")
    ensure_dir(proj / "powerplants")
    ensure_dir(proj / "ops")
    ensure_dir(proj / "configs")
    ensure_dir(proj / "runs")
    ensure_dir(proj / "results")
    ensure_dir(proj / "exports")

    proj_def = default_project_json(project_id)
    write_json(json.loads(proj_def.model_dump_json()), proj / f"{project_id}.json")
    write_json(json.loads(default_mission_json(project_id).model_dump_json()), proj / f"missions/{project_id}_mission.json")
    write_json(json.loads(default_powerplant_json(project_id).model_dump_json()), proj / f"powerplants/{project_id}_pp.json")
    write_json(json.loads(default_op_json().model_dump_json()), proj / "ops/cruise.json")
    write_json(json.loads(default_config_json().model_dump_json()), proj / "configs/clean.json")
    logger.info(
        "Project scaffolding created",
        context={"project_id": project_id, "path": str(proj)},
    )
    return proj


def create_empty_vsp3(vsp, vsp_path: Path) -> None:
    vsp.ClearVSPModel()
    vsp.WriteVSPFile(str(vsp_path))
    logger.info("Created empty VSP model", context={"path": str(vsp_path)})


# -------------------------
# Smoke test runner
# -------------------------

def smoke_run(
    projects_root: Path,
    project_id: str,
    set_name: str,
    mach: float | None,
    alpha_deg: float | None,
    config_id: str | None,
    op_id: str | None,
) -> None:
    proj = ensure_dir(projects_root / project_id)
    results_root = ensure_dir(proj / "results")
    vsp_path = proj / f"{project_id}.vsp3"
    run_logger = logger.bind(command="smoke", project_id=project_id)

    manager = AnalysisManager(results_root=results_root, open_gui=True)
    vsp = manager.vsp
    if vsp is None:
        raise StreamlineError(
            "AnalysisManager did not return an OpenVSP context",
            context={"project_id": project_id},
        )
    
    with manager.vsp_guard():
        if not vsp_path.exists():
            create_empty_vsp3(vsp, vsp_path)
        else:
            try:
                vsp.ReadVSPFile(str(vsp_path))
            except Exception:
                pass

    run_logger.info(
        "OpenVSP GUI ready",
        context={"vsp_path": str(vsp_path)},
    )
    run_logger.info("Create or load geometry, then save before continuing.")
    input("       Press ENTER here when you're ready to run VSPAERO... ")

    with manager.vsp_guard():
        try:
            vsp.WriteVSPFile(str(vsp_path))
        except Exception as exc:
            run_logger.warning(
                "Could not save model before analysis",
                hint=str(exc),
            )

    config_catalog = load_config_catalog(proj)
    if not config_catalog:
        raise ConfigCatalogError(
            "No configurations found for smoke run",
            context={"project_id": project_id},
        )

    if config_id:
        config_summary = next((item for item in config_catalog if item.config_id == config_id), None)
        if config_summary is None:
            available = ", ".join(item.config_id for item in config_catalog)
            raise ConfigCatalogError(
                f"Configuration '{config_id}' not found",
                context={"requested": config_id, "available": available},
            )
    else:
        config_summary = config_catalog[0]
        config_id = config_summary.config_id

    config = load_config(config_summary.path)

    op_catalog = load_op_catalog(proj)
    if not op_catalog:
        raise OperatingPointCatalogError(
            "No operating points found for smoke run",
            context={"project_id": project_id},
        )
    if op_id:
        op_summary = next((item for item in op_catalog if item.op_id == op_id), None)
        if op_summary is None:
            available_ops = ", ".join(item.op_id for item in op_catalog)
            raise OperatingPointCatalogError(
                f"Operating point '{op_id}' not found",
                context={"requested": op_id, "available": available_ops},
            )
    else:
        op_summary = op_catalog[0]
        op_id = op_summary.op_id

    op = get_operating_point(proj, op_summary.op_id)
    applied_op = apply_operating_point(op)

    with manager.vsp_guard():
        all_sets = list_sets(vsp)
        counts = set_membership_counts(vsp)
    for idx, name in all_sets.items():
        run_logger.info(
            "Set membership",
            context={"index": idx, "name": name, "members": counts.get(idx, 0)},
        )

    try:
        with manager.vsp_guard():
            applied_cfg = apply_configuration(vsp, config, fallback_set_name=set_name)
    except ValueError as exc:
        raise StreamlineError(
            f"Failed to apply configuration '{config.config_id}'",
            context={"set_name": set_name},
            hint=str(exc),
        ) from exc

    resolved_set_idx = applied_cfg.geom_set_index
    if resolved_set_idx is None:
        with manager.vsp_guard():
            resolved_set_idx = choose_populated_set(vsp)
    resolved_set_name = applied_cfg.geom_set_name or all_sets.get(resolved_set_idx, set_name)

    alpha_value = float(alpha_deg) if alpha_deg is not None else 2.0
    mach_value = float(mach) if mach is not None else None

    run_logger.info(
        "Operating point selected",
        context={
            "op_id": applied_op.op_id,
            "altitude_m": applied_op.altitude_m,
            "mach": applied_op.mach,
        },
    )

    base_context = {
        "config_id": config.config_id,
        "set_index": resolved_set_idx,
        "set_name": resolved_set_name,
        "mode_id": applied_cfg.mode_id,
        "use_mode_flag": applied_cfg.use_mode_flag,
    }
    if applied_cfg.applied_var_presets:
        base_context["applied_var_presets"] = list(applied_cfg.applied_var_presets)

    base_parm_overrides: Dict[str, float] = {}
    if applied_cfg.parm_overrides:
        base_parm_overrides.update(applied_cfg.parm_overrides)

    base_dependency_keys = {
        f"config:{config.config_id}",
        f"set:{resolved_set_idx}",
    }
    if applied_cfg.mode_id:
        base_dependency_keys.add(f"mode:{applied_cfg.mode_id}")
    base_dependency_keys.add(f"mode_flag:{int(bool(applied_cfg.use_mode_flag))}")

    geometry_ticket = ComputeGeometryTicket(
        config_id=config.config_id,
        set_index=resolved_set_idx,
        set_name=resolved_set_name,
        mode_id=applied_cfg.mode_id,
        use_mode_flag=applied_cfg.use_mode_flag,
    )
    geom_context = dict(base_context)
    geom_context["analysis_method"] = geometry_ticket.analysis_method
    geom_context["symmetry"] = geometry_ticket.symmetry
    geom_context["alternate_input_format_flag"] = geometry_ticket.alternate_input_format_flag
    if base_parm_overrides:
        geom_context["parm_overrides"] = dict(base_parm_overrides)
    if geometry_ticket.udp_overrides:
        geom_context["udp_overrides"] = dict(geometry_ticket.udp_overrides)
    if geometry_ticket.runtime_overrides:
        geom_context["runtime_overrides"] = dict(geometry_ticket.runtime_overrides)

    geom_job_id = manager.submit(
        "vspaero_compute_geometry",
        geometry_ticket,
        context_extras=geom_context,
        runtime_kwargs={"applied_configuration": applied_cfg},
        dependency_keys=set(base_dependency_keys),
    )
    stability_ticket = StabilityTicket(
        config_id=config.config_id,
        set_index=resolved_set_idx,
        set_name=resolved_set_name,
        mode_id=applied_cfg.mode_id,
        use_mode_flag=applied_cfg.use_mode_flag,
        operating_point_id=applied_op.op_id,
        alpha_deg=alpha_value,
        beta_deg=0.0,
        mach=mach_value,
        ncpu=max(1, (os.cpu_count() or 4)),
        redirect_file="stdout",
    )
    stability_context = dict(base_context)
    stability_context["operating_point_id"] = applied_op.op_id
    stability_context["alpha_deg"] = stability_ticket.alpha_deg
    stability_context["beta_deg"] = stability_ticket.beta_deg
    stability_context["mach"] = mach_value
    stability_context["ncpu"] = stability_ticket.ncpu
    if applied_op.altitude_m is not None:
        stability_context["altitude_m"] = applied_op.altitude_m
    if applied_op.mach is not None and mach_value is None:
        stability_context["mach"] = applied_op.mach
    if stability_ticket.control_group_deflections_deg:
        stability_context["control_group_deflections"] = dict(stability_ticket.control_group_deflections_deg)

    stability_parm_overrides = dict(base_parm_overrides)
    if stability_ticket.udp_overrides:
        stability_parm_overrides.update(stability_ticket.udp_overrides)
    if stability_ticket.runtime_overrides:
        stability_parm_overrides.update(stability_ticket.runtime_overrides)
    if stability_parm_overrides:
        stability_context["parm_overrides"] = stability_parm_overrides

    stability_dependency_keys = set(base_dependency_keys)
    stability_dependency_keys.add(f"op:{applied_op.op_id}")
    stability_dependency_keys.add(f"alpha:{stability_ticket.alpha_deg}")
    if stability_ticket.mach is not None:
        stability_dependency_keys.add(f"mach:{stability_ticket.mach}")
    stability_job_id = manager.submit(
        "vspaero_stability",
        stability_ticket,
        context_extras=stability_context,
        runtime_kwargs={
            "applied_configuration": applied_cfg,
            "applied_operating_point": applied_op,
        },
        dependency_keys=stability_dependency_keys,
        wait_for={geom_job_id},
    )

    parasite_ticket = ParasiteDragTicket(
        config_id=config.config_id,
        set_index=resolved_set_idx,
        set_name=resolved_set_name,
        mode_id=applied_cfg.mode_id,
        use_mode_flag=applied_cfg.use_mode_flag,
        operating_point_id=applied_op.op_id,
        altitude_m=None,
        mach=mach_value,
    )
    parasite_parm_overrides = dict(stability_parm_overrides)
    if parasite_ticket.udp_overrides:
        parasite_parm_overrides.update(parasite_ticket.udp_overrides)
    if parasite_ticket.runtime_overrides:
        parasite_parm_overrides.update(parasite_ticket.runtime_overrides)

    parasite_context = dict(stability_context)
    parasite_context["freestream_mode"] = "mach" if mach_value is not None else "auto"
    if parasite_parm_overrides:
        parasite_context["parm_overrides"] = parasite_parm_overrides

    parasite_dependency_keys = set(stability_dependency_keys)
    if mach_value is not None:
        parasite_dependency_keys.add(f"mach:{mach_value}")
        parasite_dependency_keys.add("freestream:mach")
    else:
        parasite_dependency_keys.add("freestream:auto")
    parasite_job_id = manager.submit(
        "parasite_drag",
        parasite_ticket,
        context_extras=parasite_context,
        runtime_kwargs={
            "applied_configuration": applied_cfg,
            "applied_operating_point": applied_op,
        },
        dependency_keys=parasite_dependency_keys,
        wait_for={geom_job_id},
    )

    with manager.vsp_guard():
        lock_gui(vsp)
    try:
        manager.drain()
    finally:
        with manager.vsp_guard():
            unlock_gui(vsp)

    job_states = {
        "geometry": manager.job_state(geom_job_id),
        "stability": manager.job_state(stability_job_id),
        "parasite": manager.job_state(parasite_job_id),
    }
    for label, state in job_states.items():
        if state.error is not None:
            raise StreamlineError(
                f"{label} analysis failed",
                context={"project_id": project_id, "job_id": state.job.job_id},
                hint=str(state.error),
            ) from state.error

    stab_receipt = job_states["stability"].receipt
    parasite_receipt = job_states["parasite"].receipt

    if stab_receipt is None or parasite_receipt is None:
        raise StreamlineError(
            "Expected analysis receipts were not produced",
            context={"project_id": project_id},
        )

    if stab_receipt.artifact_dir:
        run_logger.info(
            "Stability results stored",
            context={"path": str(results_root / stab_receipt.artifact_dir)},
        )
    else:
        run_logger.warning("Stability receipt did not report an artifact directory")
    if stab_receipt.static_margin is not None:
        run_logger.info(
            "Static margin computed",
            context={"static_margin": stab_receipt.static_margin},
        )

    if parasite_receipt.total_cd is not None:
        run_logger.info(
            "Parasite drag computed",
            context={"total_cd": parasite_receipt.total_cd},
        )
    if parasite_receipt.artifact_dir:
        run_logger.info(
            "Parasite drag artifacts stored",
            context={"path": str(results_root / parasite_receipt.artifact_dir)},
        )

    run_logger.info("Smoke test complete")
    if stab_receipt.artifact_dir:
        run_logger.info(
            "Stability artifact directory",
            context={"path": str(results_root / stab_receipt.artifact_dir)},
        )
    if parasite_receipt.artifact_dir:
        run_logger.info(
            "Parasite drag artifact directory",
            context={"path": str(results_root / parasite_receipt.artifact_dir)},
        )

# -------------------------
# CLI entry point
# -------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="streamline",
        description="Streamline project bootstrap & analysis harness",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("STREAMLINE_LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO or STREAMLINE_LOG_LEVEL env)",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("STREAMLINE_LOG_FILE"),
        help="Optional log file path (default: STREAMLINE_LOG_FILE env)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create a new project scaffolding and a matching .vsp3")
    p_init.add_argument("project_id")
    p_init.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )

    p_gui = sub.add_parser("gui", help="Open the OpenVSP GUI in the current environment")

    p_configs = sub.add_parser("configs", help="List configurations available for a project")
    p_configs.add_argument("project_id")
    p_configs.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )

    p_ops = sub.add_parser("ops", help="List operating points available for a project")
    p_ops.add_argument("project_id")
    p_ops.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )

    p_results = sub.add_parser("results", help="List recorded analysis runs for a project")
    p_results.add_argument("project_id")
    p_results.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )
    p_results.add_argument("--analysis", default=None, help="Filter by analysis key (optional)")
    p_results.add_argument("--op", default=None, help="Filter by operating point ID (optional)")
    p_results.add_argument("--limit", type=int, default=10, help="Maximum entries to show (default: 10)")

    p_smoke = sub.add_parser("smoke", help="Create/open project, then run VSPAERO smoke analyses")
    p_smoke.add_argument("project_id")
    p_smoke.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )
    p_smoke.add_argument("--set", dest="set_name", default="baseline", help="OpenVSP Set to analyze")
    p_smoke.add_argument("--config", dest="config_id", default=None, help="Configuration ID to apply")
    p_smoke.add_argument("--op", dest="op_id", default=None, help="Operating point ID to apply")
    p_smoke.add_argument("--mach", type=float, default=None, help="Override Mach number if desired")
    p_smoke.add_argument("--alpha-deg", type=float, default=None, help="Angle of attack override (deg)")

    p_tui = sub.add_parser("tui", help="Launch the Textual interface")
    p_tui.add_argument(
        "--projects-root",
        default=str(repo_root_from_here() / "projects"),
        help="Root folder for projects/ (default: ./projects)",
    )
    p_tui.add_argument(
        "--open-gui",
        action="store_true",
        help="Open OpenVSP GUI when the analysis manager is first created",
    )

    args = parser.parse_args(argv)

    log_file = Path(args.log_file).expanduser().resolve() if args.log_file else None
    setup_logging(LoggingConfig(level=args.log_level, logfile=log_file))
    cli_logger = logger.bind(command=args.cmd)

    try:
        if args.cmd == "init":
            projects_root = ensure_dir(Path(args.projects_root))
            proj = create_new_project(projects_root, args.project_id)
            manager = AnalysisManager(open_gui=False)
            vsp = manager.vsp
            if vsp is None:
                raise StreamlineError(
                    "Failed to initialize OpenVSP context",
                    context={"command": "init"},
                )
            with manager.vsp_guard():
                create_empty_vsp3(vsp, proj / f"{args.project_id}.vsp3")
            cli_logger.info(
                "Project scaffold created",
                context={
                    "project_id": args.project_id,
                    "project_path": str(proj),
                    "vsp_model": str(proj / f"{args.project_id}.vsp3"),
                },
            )
            return 0

        if args.cmd == "gui":
            manager = AnalysisManager(open_gui=True)
            vsp = manager.vsp
            if vsp is None:
                raise StreamlineError(
                    "Failed to initialize OpenVSP context",
                    context={"command": "gui"},
                )
            cli_logger.info("OpenVSP GUI launched")
            return 0

        if args.cmd == "configs":
            projects_root = ensure_dir(Path(args.projects_root))
            proj = ensure_dir(projects_root / args.project_id)
            catalog = load_config_catalog(proj)
            if not catalog:
                cli_logger.warning(
                    "No configurations found",
                    context={"project_id": args.project_id},
                )
            else:
                for summary in catalog:
                    cli_logger.info(
                        "Configuration",
                        context={
                            "project_id": args.project_id,
                            "config_id": summary.config_id,
                            "mode": summary.mode_id or "(none)",
                            "set": summary.set_name if summary.set_name is not None else summary.set_index,
                            "has_presets": summary.has_presets,
                            "notes": summary.notes or None,
                        },
                    )
            return 0

        if args.cmd == "ops":
            projects_root = ensure_dir(Path(args.projects_root))
            proj = ensure_dir(projects_root / args.project_id)
            catalog = load_op_catalog(proj)
            if not catalog:
                cli_logger.warning(
                    "No operating points found",
                    context={"project_id": args.project_id},
                )
            else:
                for summary in catalog:
                    cli_logger.info(
                        "Operating point",
                        context={
                            "project_id": args.project_id,
                            "op_id": summary.op_id,
                            "altitude_m": summary.altitude_m,
                            "mach": summary.mach,
                            "tas_mps": summary.tas_mps,
                            "notes": summary.notes or None,
                        },
                    )
            return 0

        if args.cmd == "results":
            projects_root = ensure_dir(Path(args.projects_root))
            proj = ensure_dir(projects_root / args.project_id)
            entries = load_result_entries(proj)
            if args.analysis:
                entries = [e for e in entries if e.analysis == args.analysis]
            if args.op:
                entries = [e for e in entries if (e.summary or {}).get("operating_point_id") == args.op]
            if not entries:
                cli_logger.info(
                    "No results recorded",
                    context={"project_id": args.project_id},
                )
                return 0
            entries.sort(
                key=lambda e: (
                    e.manifest.started_utc if e.manifest and e.manifest.started_utc else ""
                ),
                reverse=True,
            )
            limit = args.limit if args.limit is not None and args.limit > 0 else len(entries)
            cli_logger.info(
                "Results summary",
                context={
                    "project_id": args.project_id,
                    "requested_limit": args.limit,
                    "showing": min(limit, len(entries)),
                    "total": len(entries),
                },
            )
            for entry in entries[:limit]:
                started = entry.manifest.started_utc if entry.manifest and entry.manifest.started_utc else "?"
                summary = entry.summary or {}
                cli_logger.info(
                    "Result entry",
                    context={
                        "started": started,
                        "analysis": entry.analysis,
                        "config": summary.get("config_id")
                        or summary.get("configuration_id"),
                        "set": summary.get("set_name") or summary.get("set_index"),
                        "mode": summary.get("mode_id"),
                        "operating_point": summary.get("operating_point_id"),
                        "artifacts": entry.artifact_dir,
                        "ticket_sha": entry.ticket_sha256,
                    },
                )
            return 0

        if args.cmd == "smoke":
            projects_root = ensure_dir(Path(args.projects_root))
            smoke_run(
                projects_root,
                args.project_id,
                set_name=args.set_name,
                mach=args.mach,
                alpha_deg=args.alpha_deg,
                config_id=args.config_id,
                op_id=args.op_id,
            )
            return 0

        if args.cmd == "tui":
            projects_root = ensure_dir(Path(args.projects_root))
            app = StreamlineApp(projects_root=projects_root, open_gui=args.open_gui)
            app.run()
            return 0

        return 0

    except StreamlineError as exc:
        _log_streamline_error(exc)
        return 1
    except Exception as exc:  # pragma: no cover - CLI guardrail
        _log_unhandled_error(exc, context={"command": getattr(args, "cmd", None)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())








