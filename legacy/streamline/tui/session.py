from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..analysis.manager import AnalysisManager
from ..core.logging import get_logger
from ..core.errors import VSPSessionError
from ..core.schema import Configuration, ModeRef, VarPresetRef
from ..io.config_catalog import get_configuration, load_config_catalog
from ..io.op_catalog import load_op_catalog
from ..io.results_index import ResultIndexEntry, load_result_entries
from ..io.fs import load_config, load_project_def
from ..vsp.contracts.base import Ticket
from ..vsp.configure import (
    ConfigurationIntrospectionError,
    configuration_from_mode,
    derive_configuration as derive_configuration_from_base,
    list_mode_details,
    list_vsp_sets,
    revalidate_existing_configs_with_lock,
    save_configuration_json,
)

from .context import SessionConfig, SessionJob, SessionState
from .event_bus import EventBus
from .events import (
    AnalysisJobQueued,
    AnalysisJobStatusChanged,
    CatalogChangedEvent,
    CacheIndexUpdated,
    ConfigurationCreatedEvent,
    ConfigurationRemovedEvent,
    ConfigurationStaleEvent,
    ConfigurationUpdatedEvent,
    ProjectAssetsRefreshed,
    ResultsIndexUpdated,
    WorkerFailed,
)
from .workers import AnalysisWorker


def _ticket_payload(ticket: Ticket) -> Dict[str, Any]:
    return json.loads(ticket.model_dump_json(exclude_none=True, exclude_defaults=False))


def _receipt_summary(receipt: Optional[Any]) -> Optional[Dict[str, Any]]:
    if receipt is None:
        return None
    try:
        payload = receipt.model_dump(mode="json")
    except AttributeError:
        return None
    summary_keys = {"ticket_sha256", "artifact_dir", "artifacts"}
    return {key: payload.get(key) for key in summary_keys}


class ProjectSession:
    """Coordinate AnalysisManager activity for a TUI session."""

    def __init__(
        self,
        *,
        project_root: Path,
        manager: AnalysisManager,
        config: SessionConfig,
        event_bus: Optional[EventBus] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.project_root = project_root
        self.manager = manager
        self.config = config
        self.event_bus = event_bus or EventBus()
        self.session_id = session_id or uuid.uuid4().hex
        self._logger = get_logger(__name__).bind(
            session_id=self.session_id,
            project=str(project_root),
        )
        self._lock = threading.RLock()
        project_def = load_project_def(project_root)
        self.state = SessionState(
            project_root=project_root,
            project_id=project_def.project_id,
            project_def=project_def,
        )
        results_root = project_root / "results"
        results_root.mkdir(parents=True, exist_ok=True)
        if manager.results_root is None or manager.results_root != results_root.resolve():
            manager.set_results_root(results_root)
        self._worker: Optional[AnalysisWorker] = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def open(
        cls,
        *,
        config: SessionConfig,
        event_bus: Optional[EventBus] = None,
        manager_factory: Optional[Callable[[Path], AnalysisManager]] = None,
    ) -> "ProjectSession":
        project_root = (config.projects_root / config.project_id).resolve()
        project_root.mkdir(parents=True, exist_ok=True)
        results_root = project_root / "results"
        results_root.mkdir(parents=True, exist_ok=True)

        if manager_factory is None:
            def manager_factory(results_path: Path) -> AnalysisManager:  # type: ignore[misc]
                return AnalysisManager(results_root=results_path, open_gui=config.open_gui)

        manager = manager_factory(results_root)
        session = cls(
            project_root=project_root,
            manager=manager,
            config=config,
            event_bus=event_bus,
        )
        session.refresh_project_assets()
        session.refresh_cache()
        session.refresh_results()
        session.sync_job_states()
        if config.auto_start_workers:
            session.start_workers()
        return session

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start_workers(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = AnalysisWorker(
                manager=self.manager,
                session_id=self.session_id,
                event_bus=self.event_bus,
                sync_callback=self.sync_job_states,
            )
            self._worker.start()
            self._logger.debug("Started analysis worker thread")

    def shutdown(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            worker = self._worker
            self._worker = None
        if worker is not None:
            worker.stop()
            worker.join(timeout=timeout)
            self._logger.debug("Stopped analysis worker thread")

    def __enter__(self) -> "ProjectSession":
        self.start_workers()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    # ------------------------------------------------------------------
    # Project refresh routines
    # ------------------------------------------------------------------
    def refresh_project_assets(self) -> None:
        def _normalize_provenance(entry: Any) -> Dict[str, Any]:
            if isinstance(entry, dict):
                result = dict(entry)
                presets = result.get("preset_pairs")
                if presets is not None and not isinstance(presets, tuple):
                    result["preset_pairs"] = tuple(presets)
                return result
            if isinstance(entry, tuple):
                parts = list(entry) + [None] * max(0, 7 - len(entry))
                preset_part = parts[2] if len(parts) > 2 else None
                if preset_part is None:
                    preset_part = ()
                return {
                    "mode_id": parts[0] if len(parts) > 0 else None,
                    "mode_use_flag": parts[1] if len(parts) > 1 else None,
                    "preset_pairs": tuple(preset_part),
                    "geom_set_index": parts[3] if len(parts) > 3 else None,
                    "geom_set_name": parts[4] if len(parts) > 4 else None,
                    "checksum": parts[5] if len(parts) > 5 else None,
                    "captured_at": parts[6] if len(parts) > 6 else None,
                }
            return {}

        configs = load_config_catalog(self.project_root)
        ops = load_op_catalog(self.project_root)
        new_config_signatures = {item.config_id: item.signature for item in configs}
        new_config_provenance: Dict[str, Dict[str, Any]] = {}
        new_config_metadata_paths: Dict[str, Optional[Path]] = {}
        for item in configs:
            new_config_provenance[item.config_id] = {
                "mode_id": item.mode_id,
                "mode_use_flag": item.mode_use_flag,
                "preset_pairs": tuple(item.preset_pairs),
                "geom_set_index": item.set_index,
                "geom_set_name": item.set_name,
                "checksum": item.checksum,
                "captured_at": item.captured_at,
            }
            new_config_metadata_paths[item.config_id] = item.metadata_path
        new_op_signatures = {item.op_id: item.signature for item in ops}
        new_op_metadata: Dict[str, Dict[str, Any]] = {}
        for item in ops:
            new_op_metadata[item.op_id] = {
                "checksum": item.checksum,
                "captured_at": item.captured_at,
                "metadata_path": str(item.metadata_path) if item.metadata_path else None,
            }

        with self._lock:
            old_config_signatures = dict(self.state.config_signatures)
            old_config_provenance = {
                cfg: _normalize_provenance(val)
                for cfg, val in dict(self.state.config_provenance).items()
            }
            old_config_metadata_paths = dict(getattr(self.state, "config_metadata_paths", {}))
            old_op_signatures = dict(self.state.op_signatures)
            old_op_metadata = dict(getattr(self.state, "op_metadata", {}))
            self.state.config_catalog = configs
            self.state.op_catalog = ops
            self.state.config_signatures = new_config_signatures
            self.state.config_provenance = new_config_provenance
            self.state.config_metadata_paths = new_config_metadata_paths
            self.state.op_signatures = new_op_signatures
            self.state.op_metadata = new_op_metadata

        added_configs = [cfg_id for cfg_id in new_config_signatures if cfg_id not in old_config_signatures]
        removed_configs = [cfg_id for cfg_id in old_config_signatures if cfg_id not in new_config_signatures]
        updated_configs: Dict[str, Dict[str, bool]] = {}
        for summary in configs:
            cfg_id = summary.config_id
            if cfg_id not in old_config_signatures:
                continue
            changes: Dict[str, bool] = {}
            if new_config_signatures[cfg_id] != old_config_signatures[cfg_id]:
                changes["signature_changed"] = True
            new_prov = new_config_provenance.get(cfg_id, {})
            old_prov = old_config_provenance.get(cfg_id, {})
            if new_prov != old_prov:
                changes["provenance_changed"] = True
            if new_prov.get("checksum") != old_prov.get("checksum"):
                changes["checksum_changed"] = True
            if new_prov.get("captured_at") != old_prov.get("captured_at"):
                changes["captured_at_changed"] = True
            if changes:
                updated_configs[cfg_id] = changes

        added_ops = [op_id for op_id in new_op_signatures if op_id not in old_op_signatures]
        removed_ops = [op_id for op_id in old_op_signatures if op_id not in new_op_signatures]
        updated_ops = [
            op_id
            for op_id in new_op_signatures
            if op_id in old_op_signatures and new_op_signatures[op_id] != old_op_signatures[op_id]
        ]

        impacted_config_ids = tuple(
            dict.fromkeys(added_configs + removed_configs + list(updated_configs.keys()))
        )
        if impacted_config_ids:
            self.event_bus.publish(
                CatalogChangedEvent(
                    kind="config",
                    identifiers=impacted_config_ids,
                    project=str(self.project_root),
                )
            )
        for cfg_id in added_configs:
            self.event_bus.publish(
                ConfigurationCreatedEvent(
                    config_id=cfg_id,
                    project=str(self.project_root),
                    source="catalog",
                )
            )
        for cfg_id, changes in updated_configs.items():
            self.event_bus.publish(
                ConfigurationUpdatedEvent(
                    config_id=cfg_id,
                    project=str(self.project_root),
                    changes=changes,
                )
            )
        for cfg_id in removed_configs:
            self.event_bus.publish(
                ConfigurationRemovedEvent(
                    config_id=cfg_id,
                    project=str(self.project_root),
                    reason="removed_from_catalog",
                )
            )

        drift_messages: Dict[str, List[str]] = {}
        modes_map: Dict[str, Any] = {}
        set_names: List[str] = []
        try:
            details = list_mode_details(resolve_names=True)
            modes_map = {d.mode_id: d for d in details if d.mode_id}
            set_names = list_vsp_sets()
        except Exception as exc:  # pragma: no cover - depends on VSP availability
            self._logger.debug("Skipping mode drift detection", hint=str(exc))
        for summary in configs:
            if not summary.mode_id:
                continue
            md = modes_map.get(summary.mode_id)
            if md is None:
                continue
            stored = new_config_provenance.get(summary.config_id, {})
            messages: List[str] = []
            stored_pairs = tuple(stored.get("preset_pairs") or ())
            actual_pairs = tuple(
                (gs.group_name, gs.setting_name)
                for gs in md.group_settings
                if gs.group_name and gs.setting_name
            )
            if stored_pairs != actual_pairs:
                messages.append("Mode preset assignments differ from stored configuration metadata")
            stored_use = stored.get("mode_use_flag")
            actual_use = md.use_mode_flag
            if stored_use is not None and actual_use is not None and bool(stored_use) != bool(actual_use):
                messages.append("Mode use flag changed in OpenVSP")
            stored_set_index = stored.get("geom_set_index")
            actual_set_index = md.normal_set
            if (
                stored_set_index is not None
                and actual_set_index is not None
                and stored_set_index != actual_set_index
            ):
                messages.append(
                    f"Mode set index changed from {stored_set_index} to {actual_set_index}"
                )
            stored_set_name = stored.get("geom_set_name")
            actual_set_name = None
            if (
                set_names
                and actual_set_index is not None
                and 0 <= actual_set_index < len(set_names)
            ):
                actual_set_name = set_names[actual_set_index]
            if stored_set_name and actual_set_name and stored_set_name != actual_set_name:
                messages.append(
                    f"Mode set name changed from '{stored_set_name}' to '{actual_set_name}'"
                )
            if messages:
                drift_messages[summary.config_id] = messages

        impacted_op_ids = tuple(dict.fromkeys(added_ops + removed_ops + updated_ops))
        if impacted_op_ids:
            self.event_bus.publish(
                CatalogChangedEvent(
                    kind="op",
                    identifiers=impacted_op_ids,
                    project=str(self.project_root),
                )
            )

        invalidate_keys = [f"configuration:{cfg_id}" for cfg_id in list(updated_configs.keys()) + removed_configs]
        if drift_messages:
            invalidate_keys.extend(f"configuration:{cfg_id}" for cfg_id in drift_messages.keys())
        if invalidate_keys:
            invalidate_keys = list(dict.fromkeys(invalidate_keys))
            try:
                self.manager.invalidate(invalidate_keys)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(
                    "Failed to invalidate cache after catalog refresh",
                    context={"keys": invalidate_keys},
                    hint=str(exc),
                )

        config_models = []
        for summary in configs:
            try:
                config_models.append(load_config(summary.path))
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.warning(
                    "Failed to load configuration for validation",
                    context={"config_id": summary.config_id, "path": str(summary.path)},
                    hint=str(exc),
                )
        stale_map: Dict[str, Tuple[str, ...]] = {}
        if config_models:
            validation: Dict[str, List[str]] = {}
            try:
                validation = revalidate_existing_configs_with_lock(config_models, analysis_manager=self.manager)
            except VSPSessionError as exc:  # pragma: no cover - depends on real VSP
                self._logger.debug(
                    "Skipping configuration revalidation; OpenVSP session unavailable",
                    hint=str(exc),
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.warning(
                    "Configuration revalidation failed",
                    hint=str(exc),
                )
            if validation:
                stale_map = {cfg_id: tuple(errs) for cfg_id, errs in validation.items() if errs}

        combined_stale: Dict[str, Tuple[str, ...]] = dict(stale_map)
        for cfg_id, messages in drift_messages.items():
            existing = list(combined_stale.get(cfg_id, ()))
            existing.extend(messages)
            combined_stale[cfg_id] = tuple(existing)
        for cfg_id, errors in combined_stale.items():
            self.event_bus.publish(
                ConfigurationStaleEvent(
                    config_id=cfg_id,
                    errors=errors,
                )
            )
        with self._lock:
            self.state.stale_configs = combined_stale
            self.state.mode_drift_configs = {cfg_id: tuple(msgs) for cfg_id, msgs in drift_messages.items()}

        self.event_bus.publish(
            ProjectAssetsRefreshed(
                session_id=self.session_id,
                config_count=len(configs),
                op_count=len(ops),
            )
        )

    def refresh_cache(self) -> None:
        summaries = self.manager.cache_summaries()
        with self._lock:
            self.state.cache_entries = summaries
        self.event_bus.publish(
            CacheIndexUpdated(
                session_id=self.session_id,
                entry_count=len(summaries),
            )
        )

    def refresh_results(self) -> None:
        results = load_result_entries(self.project_root)
        with self._lock:
            self.state.results_index = results
        self.event_bus.publish(
            ResultsIndexUpdated(
                session_id=self.session_id,
                entry_count=len(results),
            )
        )

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def list_mode_candidates(self, *, resolve_names: bool = True) -> List[Dict[str, Any]]:
        try:
            details = list_mode_details(resolve_names=resolve_names)
        except Exception as exc:
            self._logger.debug("Failed to enumerate OpenVSP modes", hint=str(exc))
            return []
        result: List[Dict[str, Any]] = []
        for item in details:
            result.append(
                {
                    "mode_id": item.mode_id,
                    "mode_name": item.mode_name,
                    "use_mode_flag": item.use_mode_flag,
                    "normal_set": item.normal_set,
                    "degen_set": item.degen_set,
                    "group_settings": [
                        {
                            "group_id": gs.group_id,
                            "group_name": gs.group_name,
                            "setting_id": gs.setting_id,
                            "setting_name": gs.setting_name,
                        }
                        for gs in item.group_settings
                    ],
                }
            )
        return result

    def create_configuration_from_mode(
        self,
        config_id: str,
        mode_id: str,
        *,
        geom_set_name: Optional[str] = None,
        geom_set_index: Optional[int] = None,
        include_presets: bool = True,
        udp_overrides: Optional[Dict[str, float]] = None,
        runtime_overrides: Optional[Dict[str, float]] = None,
        notes: Optional[str] = None,
        use_mode_flag: Optional[bool] = None,
        persist: bool = True,
    ) -> Configuration:
        try:
            configuration = configuration_from_mode(
                config_id=config_id,
                mode_id=mode_id,
                geom_set_name=geom_set_name,
                geom_set_index=geom_set_index,
                include_presets=include_presets,
                udp_overrides=udp_overrides,
                runtime_overrides=runtime_overrides,
                notes=notes,
                use_mode_flag=use_mode_flag,
            )
        except ConfigurationIntrospectionError as exc:
            self._logger.error(
                "Failed to build configuration from mode",
                context={"mode_id": mode_id, "config_id": config_id},
                hint=str(exc),
            )
            raise
        if persist:
            save_configuration_json(self.project_root, configuration)
            self.refresh_project_assets()
        return configuration

    def derive_configuration(
        self,
        base_config_id: str,
        new_config_id: str,
        *,
        udp_overrides: Optional[Dict[str, float]] = None,
        runtime_overrides: Optional[Dict[str, float]] = None,
        additional_presets: Optional[Iterable[Tuple[str, str]]] = None,
        notes: Optional[str] = None,
        mode_override: Optional[ModeRef] = None,
        persist: bool = True,
    ) -> Configuration:
        base_config = get_configuration(self.project_root, base_config_id)
        additional_refs: List[VarPresetRef] = []
        if additional_presets:
            for group_name, setting_name in additional_presets:
                additional_refs.append(
                    VarPresetRef(group_name=group_name, setting_name=setting_name)
                )
        derived = derive_configuration_from_base(
            base_config,
            new_config_id,
            udp_overrides=udp_overrides,
            runtime_overrides=runtime_overrides,
            additional_presets=additional_refs or None,
            notes=notes,
            mode_override=mode_override,
        )
        if persist:
            save_configuration_json(self.project_root, derived)
            self.refresh_project_assets()
        return derived

    # ------------------------------------------------------------------
    # Job orchestration
    # ------------------------------------------------------------------
    def queue_analysis(
        self,
        analysis_key: str,
        ticket: Ticket,
        *,
        context_extras: Optional[Dict[str, Any]] = None,
        runtime_kwargs: Optional[Dict[str, Any]] = None,
        dependency_keys: Optional[Iterable[str]] = None,
        wait_for: Optional[Iterable[str]] = None,
        priority: int = 0,
    ) -> SessionJob:
        job_id = self.manager.submit(
            analysis_key,
            ticket,
            context_extras=context_extras,
            runtime_kwargs=runtime_kwargs,
            dependency_keys=dependency_keys,
            wait_for=wait_for,
            priority=priority,
        )
        job = SessionJob(
            job_id=job_id,
            analysis_key=analysis_key,
            ticket_payload=_ticket_payload(ticket),
            context=dict(context_extras or {}),
        )
        with self._lock:
            self.state.jobs[job_id] = job
        self.event_bus.publish(
            AnalysisJobQueued(
                session_id=self.session_id,
                job_id=job_id,
                analysis_key=analysis_key,
                ticket_payload=job.ticket_payload,
                context=job.context,
                submitted_at=job.submitted_at,
            )
        )
        self._logger.info(
            "Queued analysis job",
            context={"job_id": job_id, "analysis": analysis_key},
        )
        return job

    def sync_job_states(self) -> None:
        """Poll the AnalysisManager for job updates and emit events."""

        with self._lock:
            jobs_snapshot = list(self.state.jobs.values())
        for job in jobs_snapshot:
            try:
                state = self.manager.job_state(job.job_id)
            except KeyError:
                continue
            status_changed = state.status != job.status
            ticket_sha_changed = state.ticket_sha != job.ticket_sha
            details_changed = status_changed or ticket_sha_changed
            if state.receipt is not None and state.receipt is not job.receipt:
                details_changed = True
            if state.error is not None and (job.error or "") != str(state.error):
                details_changed = True
            if not details_changed:
                continue
            with self._lock:
                job.status = state.status
                job.ticket_sha = state.ticket_sha
                job.started_at = state.started_at
                job.ended_at = state.ended_at
                job.receipt = state.receipt
                job.error = str(state.error) if state.error else None
                if job.status in {"completed", "cached", "failed"}:
                    job.finished = True
            receipt_summary = _receipt_summary(state.receipt)
            self.event_bus.publish(
                AnalysisJobStatusChanged(
                    session_id=self.session_id,
                    job_id=job.job_id,
                    analysis_key=job.analysis_key,
                    status=job.status,
                    ticket_sha=job.ticket_sha,
                    started_at=job.started_at,
                    ended_at=job.ended_at,
                    error=job.error,
                    receipt_summary=receipt_summary,
                )
            )
            if job.status in {"completed", "cached"}:
                self.refresh_cache()
                self.refresh_results()
            if job.status == "failed" and job.error:
                self._logger.warning(
                    "Analysis job failed",
                    context={"job_id": job.job_id, "analysis": job.analysis_key},
                    hint=job.error,
                )

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def job_snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                job_id: {
                    "status": job.status,
                    "analysis": job.analysis_key,
                    "ticket_sha": job.ticket_sha,
                    "submitted_at": job.submitted_at,
                    "started_at": job.started_at,
                    "ended_at": job.ended_at,
                    "error": job.error,
                }
                for job_id, job in self.state.jobs.items()
            }

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "project_root": str(self.project_root),
                "project_id": self.state.project_id,
                "jobs": self.job_snapshot(),
                "cache_entries": list(self.state.cache_entries),
                "results_count": len(self.state.results_index),
            }

    # ------------------------------------------------------------------
    # Error handling hooks
    # ------------------------------------------------------------------
    def notify_worker_failure(self, message: str, *, details: Optional[str] = None) -> None:
        self.event_bus.publish(
            WorkerFailed(
                session_id=self.session_id,
                message=message,
                details=details,
            )
        )
        self._logger.error(
            message,
            context={"session_id": self.session_id},
            hint=details,
        )


def create_project_session(
    project_id: str,
    *,
    projects_root: Path,
    open_gui: bool = False,
    auto_start_workers: bool = True,
    event_bus: Optional[EventBus] = None,
    manager_factory: Optional[Callable[[Path], AnalysisManager]] = None,
) -> ProjectSession:
    """Convenience wrapper mirroring the legacy helper."""

    config = SessionConfig(
        projects_root=projects_root,
        project_id=project_id,
        open_gui=open_gui,
        auto_start_workers=auto_start_workers,
    )
    return ProjectSession.open(
        config=config,
        event_bus=event_bus,
        manager_factory=manager_factory,
    )

