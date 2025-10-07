from __future__ import annotations

import json
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Type

from ..core.errors import AnalysisError
from ..core.logging import get_logger
from ..core.schema import RunManifest
from ..io.cache_store import CacheRecord, load_cache_records, save_cache_records
from ..io.results_index import (
    ResultIndexEntry,
    append_result_entry,
    load_result_entries,
    remove_result_entries,
)
from ..vsp.contracts.base import Receipt, Ticket
from ..vsp.contracts.compute_geometry import (
    ComputeGeometryPayload,
    ComputeGeometryReceipt,
)
from ..vsp.contracts.parasite_drag import (
    ParasiteDragPayload,
    ParasiteDragReceipt,
)
from ..vsp.contracts.stability import (
    StabilityPayload,
    StabilityReceipt,
)
from ..vsp.run_utils import dump_json, prepare_results_dir, relativize
from ..vsp.session import init_context

MaterializerFunc = Callable[["AnalysisManager", "AnalysisJob", str, Any, datetime, datetime], Receipt]


@dataclass
class AnalysisJob:
    job_id: str
    analysis_key: str
    ticket: Ticket
    context_extras: Dict[str, Any] = field(default_factory=dict)
    runtime_kwargs: Dict[str, Any] = field(default_factory=dict)
    dependency_keys: Set[str] = field(default_factory=set)
    wait_for: Set[str] = field(default_factory=set)
    priority: int = 0
    submitted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AnalysisRegistration:
    key: str
    runner: Callable[..., Any]
    materializer: Optional[MaterializerFunc] = None
    default_kwargs: Dict[str, Any] = field(default_factory=dict)
    default_dependency_keys: Set[str] = field(default_factory=set)
    description: Optional[str] = None
    uses_vsp_lock: bool = True
    receipt_model: Optional[Type[Receipt]] = None


@dataclass
class AnalysisCacheEntry:
    ticket_sha: str
    receipt: Receipt
    stored_at: datetime = field(default_factory=datetime.utcnow)
    dependency_keys: Set[str] = field(default_factory=set)


@dataclass
class JobState:
    job: AnalysisJob
    status: str = "pending"
    ticket_sha: Optional[str] = None
    receipt: Optional[Receipt] = None
    error: Optional[BaseException] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class DependencyIndex:
    def __init__(self) -> None:
        self._by_ticket: Dict[str, Set[str]] = {}
        self._reverse: Dict[str, Set[str]] = {}

    def record(self, ticket_sha: str, keys: Iterable[str]) -> None:
        keys_set = {k for k in keys if k}
        self.clear(ticket_sha)
        if not keys_set:
            return
        self._by_ticket[ticket_sha] = set(keys_set)
        for key in keys_set:
            self._reverse.setdefault(key, set()).add(ticket_sha)

    def clear(self, ticket_sha: str) -> None:
        prior = self._by_ticket.pop(ticket_sha, None)
        if not prior:
            return
        for key in prior:
            refs = self._reverse.get(key)
            if refs is None:
                continue
            refs.discard(ticket_sha)
            if not refs:
                self._reverse.pop(key, None)

    def invalidate(self, keys: Iterable[str]) -> Set[str]:
        impacted: Set[str] = set()
        for key in keys:
            if not key:
                continue
            refs = self._reverse.pop(key, None)
            if not refs:
                continue
            impacted.update(refs)
        for ticket_sha in impacted:
            self.clear(ticket_sha)
        return impacted

    def dependencies_for(self, ticket_sha: str) -> Set[str]:
        return set(self._by_ticket.get(ticket_sha, set()))


class AnalysisManager:
    """Queue, execute, persist, and cache Streamline analyses."""

    def __init__(
        self,
        *,
        vsp: Optional[object] = None,
        results_root: Optional[Path] = None,
        vsp_lock: Optional[threading.RLock] = None,
        auto_init_vsp: bool = True,
        open_gui: bool = False,
    ) -> None:
        if vsp is None and not auto_init_vsp:
            raise ValueError("Provide a VSP context or enable auto_init_vsp.")

        self._logger = get_logger(__name__).bind(manager_id=uuid.uuid4().hex[:8])
        self._logger.debug(
            "Initializing AnalysisManager",
            context={"auto_init_vsp": auto_init_vsp, "open_gui": open_gui},
        )

        self._vsp_lock = vsp_lock or threading.RLock()
        self._lock = threading.RLock()
        self._registry: Dict[str, AnalysisRegistration] = {}
        self._queue: "Queue[str]" = Queue()
        self._jobs: Dict[str, JobState] = {}
        self._cache: Dict[str, Dict[str, AnalysisCacheEntry]] = {}
        self._dependency_index = DependencyIndex()
        self._vsp_versions: Dict[str, str] = {}
        self._deferred_cache_records: Dict[str, List[CacheRecord]] = {}

        if vsp is None:
            ctx = init_context(open_gui=open_gui)
            self._vsp = ctx.vsp
            self._vsp_versions = dict(ctx.versions)
            self._logger.info(
                "Bound new OpenVSP session",
                context={"versions": self._vsp_versions},
            )
        else:
            self._vsp = vsp
            self._logger.info("Attached provided OpenVSP session")

        self.register_builtin_analyses()

        self._results_root: Optional[Path] = None
        if results_root is not None:
            self.set_results_root(results_root)


    # ------------------------------------------------------------------
    # Properties & configuration
    # ------------------------------------------------------------------
    @property
    def vsp(self) -> Optional[object]:
        return self._vsp

    @property
    def results_root(self) -> Optional[Path]:
        return self._results_root

    @property
    def versions(self) -> Dict[str, str]:
        return dict(self._vsp_versions)

    def bind_vsp(self, vsp: object) -> None:
        with self._lock:
            self._vsp = vsp

    def set_results_root(self, root: Optional[Path]) -> None:
        with self._lock:
            self._results_root = Path(root).resolve() if root is not None else None
            self._cache.clear()
            self._dependency_index = DependencyIndex()
            self._deferred_cache_records.clear()
            if self._results_root is not None:
                stale_removed = self._load_persisted_cache_locked()
                if stale_removed:
                    self._persist_cache_locked()
        self._logger.info(
            "Configured results root",
            context={"results_root": str(self._results_root) if self._results_root else None},
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_analysis(
        self,
        key: str,
        runner: Callable[..., Any],
        *,
        materializer: Optional[MaterializerFunc] = None,
        default_kwargs: Optional[Dict[str, Any]] = None,
        default_dependency_keys: Optional[Iterable[str]] = None,
        description: Optional[str] = None,
        uses_vsp_lock: bool = True,
        receipt_model: Optional[Type[Receipt]] = None,
    ) -> None:
        with self._lock:
            if key in self._registry:
                # existing registration wins
                return
            if receipt_model is not None and not issubclass(receipt_model, Receipt):
                raise TypeError("receipt_model must inherit from Receipt")
            self._registry[key] = AnalysisRegistration(
                key=key,
                runner=runner,
                materializer=materializer,
                default_kwargs=dict(default_kwargs or {}),
                default_dependency_keys=set(default_dependency_keys or set()),
                description=description,
                uses_vsp_lock=bool(uses_vsp_lock),
                receipt_model=receipt_model,
            )
            pending_records = self._deferred_cache_records.pop(key, [])
            if pending_records and self._results_root is not None:
                self._load_cache_records_for_analysis_locked(key, pending_records)
                self._persist_cache_locked()
        self._logger.debug(
            "Registered analysis",
            context={
                "analysis": key,
                "uses_vsp_lock": uses_vsp_lock,
                "has_materializer": materializer is not None,
                "persistable": receipt_model is not None,
            },
        )
    def register_builtin_analyses(self) -> None:
        from ..vsp.analyses.compute_geometry import run_compute_geometry
        from ..vsp.analyses.parasite_drag import run_parasite_drag
        from ..vsp.analyses.stability import run_stability

        self.register_analysis(
            "vspaero_compute_geometry",
            run_compute_geometry,
            materializer=_materialize_compute_geometry,
            default_dependency_keys={"vsp_model", "configuration"},
            receipt_model=ComputeGeometryReceipt,
            description="Pre-compute VSPAERO geometry inputs",
        )
        self.register_analysis(
            "vspaero_stability",
            run_stability,
            materializer=_materialize_stability,
            default_dependency_keys={"vsp_model", "configuration", "operating_point"},
            receipt_model=StabilityReceipt,
            description="Run VSPAERO static stability analysis",
        )
        self.register_analysis(
            "parasite_drag",
            run_parasite_drag,
            materializer=_materialize_parasite_drag,
            default_dependency_keys={"vsp_model", "configuration", "freestream"},
            receipt_model=ParasiteDragReceipt,
            description="Run VSPAERO parasite drag build-up",
        )

    # ------------------------------------------------------------------
    # Queue API
    # ------------------------------------------------------------------
    def submit(
        self,
        analysis_key: str,
        ticket: Ticket,
        *,
        context_extras: Optional[Dict[str, Any]] = None,
        runtime_kwargs: Optional[Dict[str, Any]] = None,
        dependency_keys: Optional[Iterable[str]] = None,
        wait_for: Optional[Iterable[str]] = None,
        priority: int = 0,
    ) -> str:
        with self._lock:
            if analysis_key not in self._registry:
                raise KeyError(f"Analysis '{analysis_key}' is not registered")
            job_id = uuid.uuid4().hex
            base_context = {"analysis": analysis_key}
            if context_extras:
                base_context.update(context_extras)
            job = AnalysisJob(
                job_id=job_id,
                analysis_key=analysis_key,
                ticket=ticket,
                context_extras=base_context,
                runtime_kwargs=dict(runtime_kwargs or {}),
                dependency_keys=set(dependency_keys or set()),
                wait_for=set(wait_for or set()),
                priority=int(priority),
            )
            self._jobs[job_id] = JobState(job=job)
            self._queue.put(job_id)
            self._logger.info(
                "Queued analysis job",
                context={
                    "job_id": job_id,
                    "analysis": analysis_key,
                    "priority": priority,
                    "wait_for": list(job.wait_for),
                },
            )
            return job_id

    def has_pending(self) -> bool:
        return not self._queue.empty()

    def pending_jobs(self) -> Dict[str, JobState]:
        with self._lock:
            return {
                job_id: state
                for job_id, state in self._jobs.items()
                if state.status in {"pending", "running"}
            }

    def job_state(self, job_id: str) -> JobState:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown job_id '{job_id}'")
            return self._jobs[job_id]

    def run_next(self, *, block: bool = False, timeout: Optional[float] = None) -> Optional[Receipt]:
        try:
            job_id = self._queue.get(block=block, timeout=timeout)
        except Empty:
            return None
        try:
            return self._execute_job(job_id)
        finally:
            self._queue.task_done()

    def drain(self) -> None:
        while self.has_pending():
            if self.run_next(block=False) is None:
                break

    # ------------------------------------------------------------------
    # Cache & invalidation
    # ------------------------------------------------------------------
    def invalidate(self, keys: Iterable[str]) -> Set[str]:
        key_list = [k for k in keys]
        with self._lock:
            impacted = self._dependency_index.invalidate(key_list)
            if not impacted:
                self._logger.debug(
                    "No cache entries impacted by invalidation",
                    context={"keys": key_list},
                )
                return set()
            for cache_bucket in self._cache.values():
                for ticket_sha in list(impacted):
                    cache_bucket.pop(ticket_sha, None)
            for deferred in self._deferred_cache_records.values():
                deferred[:] = [record for record in deferred if record.ticket_sha256 not in impacted]
            empty_keys = [key for key, records in self._deferred_cache_records.items() if not records]
            for empty_key in empty_keys:
                self._deferred_cache_records.pop(empty_key, None)
            self._persist_cache_locked()
            self._prune_stale_cache_entries_locked()
        impacted_set = set(impacted)
        self._logger.info(
            "Invalidated cached receipts",
            context={"keys": key_list, "impacted": list(impacted_set)},
        )
        return impacted_set
    def clear_cache(
        self,
        *,
        analysis_keys: Optional[Iterable[str]] = None,
        ticket_shas: Optional[Iterable[str]] = None,
        drop_results: bool = True,
    ) -> List[str]:
        """Clear cached receipts and optionally remove their artifacts."""

        keys_filter: Set[str] = {key for key in (analysis_keys or []) if key}
        ticket_filter: Set[str] = {sha for sha in (ticket_shas or []) if sha}
        removed_entries: List[Tuple[str, str, AnalysisCacheEntry]] = []

        with self._lock:
            if not self._cache and not self._deferred_cache_records:
                self._logger.debug(
                    "Cache already empty",
                    context={"analysis_keys": list(keys_filter) or None, "ticket_shas": list(ticket_filter) or None},
                )
                return []
            cache_changed = False
            for analysis_key, bucket in list(self._cache.items()):
                if keys_filter and analysis_key not in keys_filter:
                    continue
                for ticket_sha, entry in list(bucket.items()):
                    if ticket_filter and ticket_sha not in ticket_filter:
                        continue
                    removed_entries.append((analysis_key, ticket_sha, entry))
                    bucket.pop(ticket_sha, None)
                    self._dependency_index.clear(ticket_sha)
                    cache_changed = True
                if not bucket:
                    self._cache.pop(analysis_key, None)
            if keys_filter or ticket_filter:
                for analysis_key, records in list(self._deferred_cache_records.items()):
                    if keys_filter and analysis_key not in keys_filter:
                        continue
                    if ticket_filter:
                        remaining = [record for record in records if record.ticket_sha256 not in ticket_filter]
                    else:
                        remaining = []
                    if remaining:
                        if len(remaining) != len(records):
                            self._deferred_cache_records[analysis_key] = remaining
                            cache_changed = True
                        continue
                    self._deferred_cache_records.pop(analysis_key, None)
                    cache_changed = True
            else:
                if self._deferred_cache_records:
                    cache_changed = True
                self._deferred_cache_records.clear()
            if cache_changed:
                self._persist_cache_locked()

        if not removed_entries:
            self._logger.debug(
                "No cache entries matched clear request",
                context={
                    "analysis_keys": list(keys_filter) or None,
                    "ticket_shas": list(ticket_filter) or None,
                },
            )
            return []

        removed_shas = [ticket_sha for _, ticket_sha, _ in removed_entries]
        root = self._results_root
        removed_artifacts: List[str] = []
        keys_context = list(keys_filter) or None

        if drop_results:
            if root is None:
                self._logger.warning(
                    "drop_results requested but no results_root configured",
                    context={"analysis_keys": keys_context, "ticket_shas": removed_shas},
                )
            else:
                for analysis_key, ticket_sha, entry in removed_entries:
                    artifact_rel = getattr(entry.receipt, "artifact_dir", None)
                    if not artifact_rel:
                        continue
                    artifact_path = root / artifact_rel
                    try:
                        artifact_path.relative_to(root)
                    except ValueError:
                        self._logger.warning(
                            "Skipping artifact outside results root",
                            context={
                                "analysis": analysis_key,
                                "ticket_sha": ticket_sha,
                                "artifact_dir": str(artifact_path),
                            },
                        )
                        continue
                    if not artifact_path.exists():
                        continue
                    try:
                        shutil.rmtree(artifact_path)
                        removed_artifacts.append(str(artifact_path.relative_to(root)))
                    except Exception as exc:  # pragma: no cover - filesystem guard
                        self._logger.warning(
                            "Failed to remove cached artifact directory",
                            context={
                                "analysis": analysis_key,
                                "ticket_sha": ticket_sha,
                                "artifact_dir": str(artifact_path),
                            },
                            hint=str(exc),
                        )
                if removed_artifacts:
                    self._logger.info(
                        "Removed cached result artifacts",
                        context={
                            "analysis_keys": keys_context,
                            "count": len(removed_artifacts),
                        },
                    )
                try:
                    remove_result_entries(root.parent, ticket_shas=removed_shas)
                except Exception as exc:  # pragma: no cover - filesystem guard
                    self._logger.warning(
                        "Failed to update results index after cache clear",
                        context={"analysis_keys": keys_context},
                        hint=str(exc),
                    )

        self._logger.info(
            "Cleared cached receipts",
            context={
                "analysis_keys": keys_context,
                "ticket_shas": removed_shas,
                "drop_results": drop_results,
            },
        )
        return removed_shas

    def cache_summaries(
        self,
        *,
        analysis_keys: Optional[Iterable[str]] = None,
        ticket_shas: Optional[Iterable[str]] = None,
        include_deferred: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return cache entry metadata for introspection."""

        keys_filter: Set[str] = {key for key in (analysis_keys or []) if key}
        ticket_filter: Set[str] = {sha for sha in (ticket_shas or []) if sha}
        summaries: List[Dict[str, Any]] = []

        with self._lock:
            for analysis_key, bucket in self._cache.items():
                if keys_filter and analysis_key not in keys_filter:
                    continue
                registration = self._registry.get(analysis_key)
                description = registration.description if registration else None
                for ticket_sha, entry in bucket.items():
                    if ticket_filter and ticket_sha not in ticket_filter:
                        continue
                    if self._results_root is not None and not self._receipt_is_valid(entry):
                        continue
                    receipt = entry.receipt
                    manifest = getattr(receipt, "run_manifest", None)
                    summaries.append(
                        {
                            "analysis": analysis_key,
                            "status": "available",
                            "ticket_sha": ticket_sha,
                            "stored_at": entry.stored_at.isoformat(),
                            "artifact_dir": getattr(receipt, "artifact_dir", None),
                            "dependencies": sorted(entry.dependency_keys),
                            "receipt_model": f"{receipt.__class__.__module__}.{receipt.__class__.__qualname__}",
                            "analysis_description": description,
                            "run_started": manifest.started_utc if manifest else None,
                        }
                    )
            if include_deferred:
                for analysis_key, records in self._deferred_cache_records.items():
                    if keys_filter and analysis_key not in keys_filter:
                        continue
                    registration = self._registry.get(analysis_key)
                    description = registration.description if registration else None
                    for record in records:
                        if ticket_filter and record.ticket_sha256 not in ticket_filter:
                            continue
                        receipt_data = record.receipt or {}
                        manifest_data = receipt_data.get("run_manifest") or {}
                        summaries.append(
                            {
                                "analysis": analysis_key,
                                "status": "deferred",
                                "ticket_sha": record.ticket_sha256,
                                "stored_at": record.stored_at,
                                "artifact_dir": receipt_data.get("artifact_dir"),
                                "dependencies": sorted(record.dependency_keys),
                                "receipt_model": record.receipt_model,
                                "analysis_description": description,
                                "run_started": manifest_data.get("started_utc"),
                            }
                        )

        summaries.sort(key=lambda item: (item["analysis"], item.get("stored_at") or "", item["ticket_sha"]))
        return summaries

    def cache_entry(self, analysis_key: str, ticket_sha: str) -> Optional[AnalysisCacheEntry]:
        with self._lock:
            entry = self._cache.get(analysis_key, {}).get(ticket_sha)
        if entry and not self._receipt_is_valid(entry):
            with self._lock:
                bucket = self._cache.get(analysis_key, {})
                bucket.pop(ticket_sha, None)
                self._dependency_index.clear(ticket_sha)
            return None
        return entry

    def _execute_job(self, job_id: str) -> Optional[Receipt]:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError("Unknown job '{0}'".format(job_id))
            job = state.job
        self._logger.debug(
            "Evaluating job for execution",
            context={"job_id": job_id, "analysis": job.analysis_key},
        )
        if not self._dependencies_satisfied(job):
            self._logger.debug(
                "Job waiting on dependencies",
                context={"job_id": job_id, "wait_for": list(job.wait_for)},
            )
            self._queue.put(job_id)
            return None

        ticket_sha = job.ticket.sha256(job.context_extras or None)
        cache_entry = self.cache_entry(job.analysis_key, ticket_sha)
        if cache_entry:
            with self._lock:
                state.status = "cached"
                state.ticket_sha = ticket_sha
                state.receipt = cache_entry.receipt
                state.started_at = state.started_at or datetime.utcnow()
                state.ended_at = datetime.utcnow()
                state.error = None
            self._logger.info(
                "Reusing cached receipt",
                context={"job_id": job_id, "analysis": job.analysis_key, "ticket_sha": ticket_sha},
            )
            return cache_entry.receipt

        with self._lock:
            state.status = "running"
            state.started_at = datetime.utcnow()
            state.error = None
            started_at = state.started_at
        self._logger.info(
            "Running analysis job",
            context={"job_id": job_id, "analysis": job.analysis_key},
        )

        registration = self._registry[job.analysis_key]
        call_kwargs = dict(registration.default_kwargs)
        call_kwargs.update(job.runtime_kwargs)

        try:
            if registration.uses_vsp_lock:
                if self._vsp is None:
                    err = AnalysisError(
                        "OpenVSP context is required for analysis",
                        context={"analysis": job.analysis_key},
                    )
                    self._logger.error(err.message, context=err.context, code=err.code)
                    raise err
                with self.vsp_guard():
                    result = registration.runner(self._vsp, job.ticket, **call_kwargs)
            else:
                result = registration.runner(self._vsp, job.ticket, **call_kwargs)
        except BaseException as exc:
            ended = datetime.utcnow()
            with self._lock:
                state.status = "failed"
                state.error = exc
                state.ended_at = ended
            self._logger.exception(
                "Analysis job failed",
                context={"job_id": job_id, "analysis": job.analysis_key},
            )
            raise

        ended = datetime.utcnow()

        if registration.materializer is not None:
            receipt = registration.materializer(
                self,
                job,
                ticket_sha,
                result,
                started_at or ended,
                ended,
            )
        else:
            if not isinstance(result, Receipt):
                raise TypeError(
                    "Analysis '{0}' returned a non-Receipt payload without a materializer".format(job.analysis_key)
                )
            receipt = result

        deps = set(registration.default_dependency_keys) | set(job.dependency_keys)
        entry = AnalysisCacheEntry(ticket_sha=ticket_sha, receipt=receipt, stored_at=ended, dependency_keys=deps)
        with self._lock:
            state.status = "completed"
            state.ticket_sha = ticket_sha
            state.receipt = receipt
            state.ended_at = ended
            cache_bucket = self._cache.setdefault(job.analysis_key, {})
            cache_bucket[ticket_sha] = entry
            self._dependency_index.record(ticket_sha, deps)
            self._persist_cache_locked()
        self._prune_stale_cache_entries()
        self._logger.info(
            "Analysis job completed",
            context={
                "job_id": job_id,
                "analysis": job.analysis_key,
                "ticket_sha": ticket_sha,
            },
        )
        return receipt

    def _dependencies_satisfied(self, job: AnalysisJob) -> bool:
        if not job.wait_for:
            return True
        unresolved: Set[str] = set()
        with self._lock:
            for dep_id in job.wait_for:
                dep_state = self._jobs.get(dep_id)
                if dep_state is None:
                    err = AnalysisError(
                        "Job depends on unknown prerequisite",
                        context={"job_id": job.job_id, "missing_dependency": dep_id},
                    )
                    self._logger.error(err.message, context=err.context, code=err.code)
                    raise err
                if dep_state.status in {"pending", "running"}:
                    unresolved.add(dep_id)
                if dep_state.status in {"failed", "cancelled"}:
                    err = AnalysisError(
                        "Blocking dependency is not complete",
                        context={
                            "job_id": job.job_id,
                            "dependency": dep_id,
                            "status": dep_state.status,
                        },
                    )
                    self._logger.error(err.message, context=err.context, code=err.code)
                    raise err
        return not unresolved

    def _prune_stale_cache_entries(self) -> None:
        with self._lock:
            self._prune_stale_cache_entries_locked()

    def _prune_stale_cache_entries_locked(self) -> None:
        root = self._results_root
        if not self._cache:
            return
        updated = False
        for analysis_key, bucket in list(self._cache.items()):
            for ticket_sha, entry in list(bucket.items()):
                if root is None or not self._receipt_is_valid(entry):
                    bucket.pop(ticket_sha, None)
                    self._dependency_index.clear(ticket_sha)
                    updated = True
            if not bucket:
                self._cache.pop(analysis_key, None)
                updated = True
        if updated:
            self._persist_cache_locked()
    def _receipt_is_valid(self, entry: AnalysisCacheEntry) -> bool:
        root = self._results_root
        if root is None:
            return False
        receipt = entry.receipt
        if not receipt.artifact_dir:
            return True
        artifact_path = root / receipt.artifact_dir
        if not artifact_path.exists():
            return False
        manifest_path = artifact_path / "run_manifest.json"
        if not manifest_path.exists():
            return True
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        inputs_sha = manifest_data.get("inputs_sha256")
        return not inputs_sha or inputs_sha == entry.ticket_sha

    def _load_persisted_cache_locked(self) -> bool:
        if self._results_root is None:
            return False
        cache_records = load_cache_records(self._results_root)
        if not cache_records:
            return False
        stale = False
        for record in cache_records:
            registration = self._registry.get(record.analysis)
            if registration is None or registration.receipt_model is None:
                self._deferred_cache_records.setdefault(record.analysis, []).append(record)
                continue
            if self._load_cache_records_for_analysis_locked(record.analysis, [record]):
                stale = True
        return stale

    def _load_cache_records_for_analysis_locked(
        self, analysis_key: str, records: Iterable[CacheRecord]
    ) -> bool:
        registration = self._registry.get(analysis_key)
        if registration is None or registration.receipt_model is None:
            return False
        if self._results_root is None:
            return False
        stale = False
        for record in records:
            try:
                receipt = registration.receipt_model.model_validate(record.receipt)
            except Exception as exc:
                self._logger.warning(
                    "Failed to restore cached receipt",
                    context={
                        "analysis": analysis_key,
                        "ticket_sha": record.ticket_sha256,
                    },
                    hint=str(exc),
                )
                stale = True
                continue
            try:
                stored_at = datetime.fromisoformat(record.stored_at)
            except Exception:
                stored_at = datetime.utcnow()
            entry = AnalysisCacheEntry(
                ticket_sha=record.ticket_sha256,
                receipt=receipt,
                stored_at=stored_at,
                dependency_keys=set(record.dependency_keys),
            )
            if not self._receipt_is_valid(entry):
                stale = True
                continue
            cache_bucket = self._cache.setdefault(analysis_key, {})
            cache_bucket[record.ticket_sha256] = entry
            self._dependency_index.record(record.ticket_sha256, entry.dependency_keys)
        return stale

    def _persist_cache_locked(self) -> None:
        if self._results_root is None:
            return
        records: List[CacheRecord] = []
        for analysis_key, bucket in self._cache.items():
            registration = self._registry.get(analysis_key)
            if registration is None or registration.receipt_model is None:
                continue
            receipt_model = registration.receipt_model
            receipt_type = f"{receipt_model.__module__}.{receipt_model.__qualname__}"
            for ticket_sha, entry in bucket.items():
                records.append(
                    CacheRecord(
                        analysis=analysis_key,
                        ticket_sha256=ticket_sha,
                        stored_at=entry.stored_at.isoformat(),
                        dependency_keys=sorted(entry.dependency_keys),
                        receipt=entry.receipt.model_dump(mode="json"),
                        receipt_model=receipt_type,
                    )
                )
        for analysis_key, pending in self._deferred_cache_records.items():
            records.extend(pending)
        records.sort(key=lambda rec: (rec.analysis, rec.stored_at, rec.ticket_sha256))
        save_cache_records(self._results_root, records)
    @contextmanager
    def vsp_guard(self):
        self._vsp_lock.acquire()
        try:
            yield
        finally:
            self._vsp_lock.release()


# ----------------------------------------------------------------------
# Materializers
# ----------------------------------------------------------------------

def _df_to_dict(df):
    if df is None:
        return {"index": [], "columns": [], "data": []}
    return df.to_dict(orient="split")

def _store_dataframe(df, path: Path) -> None:
    if df is not None:
        df.to_csv(path, index=False)


#TODO: Move the following three functions to their respective analysis files
def _materialize_compute_geometry(
    manager: "AnalysisManager",
    job: AnalysisJob,
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


def _materialize_stability(
    manager: "AnalysisManager",
    job: AnalysisJob,
    ticket_sha: str,
    payload: StabilityPayload,
    started: datetime,
    ended: datetime,
) -> StabilityReceipt:
    if not isinstance(payload, StabilityPayload):
        raise TypeError("Expected StabilityPayload, got {}".format(type(payload).__name__))

    results_root = manager.results_root
    artifacts: Dict[str, str] = {}
    artifact_dir_rel: Optional[str] = None
    artifact_dir_path: Optional[Path] = None

    ticket_payload = json.loads(job.ticket.model_dump_json(exclude_none=True, exclude_defaults=False))
    context_payload = dict(job.context_extras)
    if payload.parm_overrides:
        context_payload.setdefault("parm_overrides", payload.parm_overrides)


    if results_root is not None:
        run_dir = prepare_results_dir(results_root, job.analysis_key, ticket_sha, started)
        artifact_dir_path = run_dir
        artifact_dir_rel = relativize(run_dir, results_root)

        op_id = context_payload.get("operating_point_id")
        if context_payload.get("config_id") and "config_id" not in ticket_payload:
            ticket_payload["config_id"] = context_payload["config_id"]
        if context_payload.get("mode_id") and "mode_id" not in ticket_payload:
            ticket_payload["mode_id"] = context_payload["mode_id"]
        if op_id and "operating_point_id" not in ticket_payload:
            ticket_payload["operating_point_id"] = op_id

        dump_json(run_dir / "ticket.json", ticket_payload)
        artifacts["ticket_json"] = relativize(run_dir / "ticket.json", results_root)

        _store_dataframe(payload.base_stab, run_dir / "base_stability_axes.csv")
        _store_dataframe(payload.base_body, run_dir / "base_body_axes.csv")
        _store_dataframe(payload.derivs_stab, run_dir / "derivs_stability_axes.csv")
        _store_dataframe(payload.derivs_body, run_dir / "derivs_body_axes.csv")
        if payload.base_stab is not None:
            artifacts["base_stability_axes_csv"] = relativize(run_dir / "base_stability_axes.csv", results_root)
        if payload.base_body is not None:
            artifacts["base_body_axes_csv"] = relativize(run_dir / "base_body_axes.csv", results_root)
        if payload.derivs_stab is not None:
            artifacts["derivs_stability_axes_csv"] = relativize(run_dir / "derivs_stability_axes.csv", results_root)
        if payload.derivs_body is not None:
            artifacts["derivs_body_axes_csv"] = relativize(run_dir / "derivs_body_axes.csv", results_root)

        summary_payload = {
            "static_margin": payload.static_margin,
            "x_np_m": payload.x_np_m,
            "flight_condition": payload.flight_condition,
            "control_groups": payload.control_groups,
            "context": context_payload,
        }
        dump_json(run_dir / "summary.json", summary_payload)
        artifacts["summary_json"] = relativize(run_dir / "summary.json", results_root)

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

        op_summary = payload.operating_point or {}
        append_result_entry(
            results_root.parent,
            ResultIndexEntry(
                analysis=job.analysis_key,
                ticket_sha256=ticket_sha,
                artifact_dir=artifact_dir_rel,
                summary={
                    "config_id": context_payload.get("config_id"),
                    "mode_id": context_payload.get("mode_id"),
                    "operating_point_id": context_payload.get("operating_point_id"),
                    "altitude_m": op_summary.get("altitude_m"),
                    "mach": op_summary.get("mach") or context_payload.get("mach"),
                    "static_margin": payload.static_margin,
                },
                manifest=manifest,
            ),
        )

    return StabilityReceipt(
        vsp_results_id=payload.results_id,
        static_margin=payload.static_margin,
        x_np_m=payload.x_np_m,
        base_stab=_df_to_dict(payload.base_stab),
        base_body=_df_to_dict(payload.base_body),
        derivs_stab=_df_to_dict(payload.derivs_stab),
        derivs_body=_df_to_dict(payload.derivs_body),
        flight_condition=payload.flight_condition,
        control_groups=payload.control_groups,
        operating_point=payload.operating_point,
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=artifact_dir_rel,
        artifacts=artifacts,
    )


def _materialize_parasite_drag(
    manager: "AnalysisManager",
    job: AnalysisJob,
    ticket_sha: str,
    payload: ParasiteDragPayload,
    started: datetime,
    ended: datetime,
) -> ParasiteDragReceipt:
    if not isinstance(payload, ParasiteDragPayload):
        raise TypeError("Expected ParasiteDragPayload, got {}".format(type(payload).__name__))

    results_root = manager.results_root
    artifacts: Dict[str, str] = {}
    artifact_dir_rel: Optional[str] = None
    artifact_dir_path: Optional[Path] = None

    ticket_payload = json.loads(job.ticket.model_dump_json(exclude_none=True, exclude_defaults=False))
    context_payload = dict(job.context_extras)
    if payload.parm_overrides:
        context_payload.setdefault("parm_overrides", payload.parm_overrides)

    if results_root is not None:
        run_dir = prepare_results_dir(results_root, job.analysis_key, ticket_sha, started)
        artifact_dir_path = run_dir
        artifact_dir_rel = relativize(run_dir, results_root)

        if context_payload.get("config_id") and "config_id" not in ticket_payload:
            ticket_payload["config_id"] = context_payload["config_id"]
        if context_payload.get("mode_id") and "mode_id" not in ticket_payload:
            ticket_payload["mode_id"] = context_payload["mode_id"]
        if context_payload.get("operating_point_id") and "operating_point_id" not in ticket_payload:
            ticket_payload["operating_point_id"] = context_payload["operating_point_id"]

        dump_json(run_dir / "ticket.json", ticket_payload)
        artifacts["ticket_json"] = relativize(run_dir / "ticket.json", results_root)

        if payload.components is not None:
            components_path = run_dir / "components.csv"
            payload.components.to_csv(components_path, index=False)
            artifacts["components_csv"] = relativize(components_path, results_root)
        if payload.excrescence is not None:
            exc_path = run_dir / "excrescence.csv"
            payload.excrescence.to_csv(exc_path, index=False)
            artifacts["excrescence_csv"] = relativize(exc_path, results_root)

        summary_payload = {
            "totals": payload.totals,
            "labels": payload.labels,
            "flight_condition": payload.flight_condition,
            "context": context_payload,
        }
        dump_json(run_dir / "summary.json", summary_payload)
        artifacts["summary_json"] = relativize(run_dir / "summary.json", results_root)

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

        op_summary = payload.operating_point or {}
        append_result_entry(
            results_root.parent,
            ResultIndexEntry(
                analysis=job.analysis_key,
                ticket_sha256=ticket_sha,
                artifact_dir=artifact_dir_rel,
                summary={
                    "config_id": context_payload.get("config_id"),
                    "mode_id": context_payload.get("mode_id"),
                    "operating_point_id": context_payload.get("operating_point_id"),
                    "altitude_m": op_summary.get("altitude_m"),
                    "mach": op_summary.get("mach") or context_payload.get("mach"),
                    "total_cd": payload.totals.get("total_cd") if payload.totals else None,
                },
                manifest=manifest,
            ),
        )

    totals = payload.totals or {}
    return ParasiteDragReceipt(
        vsp_results_id=payload.results_id,
        total_cd=totals.get("total_cd"),
        total_f=totals.get("total_f"),
        geom_cd_total=totals.get("geom_cd_total"),
        geom_f_total=totals.get("geom_f_total"),
        excres_cd_total=totals.get("excres_cd_total"),
        excres_f_total=totals.get("excres_f_total"),
        labels=payload.labels,
        flight_condition=payload.flight_condition,
        operating_point=payload.operating_point,
        components=_df_to_dict(payload.components),
        excrescence=_df_to_dict(payload.excrescence),
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=artifact_dir_rel,
        artifacts=artifacts,
    )
