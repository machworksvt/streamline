from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from ..analysis.manager import AnalysisManager
from ..core.logging import get_logger
from ..io.config_catalog import load_config_catalog
from ..io.op_catalog import load_op_catalog
from ..io.results_index import ResultIndexEntry, load_result_entries
from ..io.fs import load_project_def
from ..vsp.contracts.base import Ticket

from .context import SessionConfig, SessionJob, SessionState
from .event_bus import EventBus
from .events import (
    AnalysisJobQueued,
    AnalysisJobStatusChanged,
    CacheIndexUpdated,
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
        configs = load_config_catalog(self.project_root)
        ops = load_op_catalog(self.project_root)
        with self._lock:
            self.state.config_catalog = configs
            self.state.op_catalog = ops
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

