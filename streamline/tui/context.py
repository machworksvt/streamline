from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Event as _ThreadEvent, Thread
from time import sleep
from typing import Any, Dict, List, Optional

from ..core.schema import ProjectDefinition
from ..io.config_catalog import load_config_catalog, ConfigSummary
from ..io.op_catalog import load_op_catalog, OperatingPointSummary
from ..io.results_index import load_result_entries, ResultIndexEntry
from ..tui.event_bus import get_global_event_bus, set_global_event_bus
from ..tui.events import (
    JOB_SUBMITTED,
    JOB_STARTED,
    JOB_COMPLETED,
    JOB_FAILED,
    RECEIPT_ADDED,
    CATALOG_CHANGED,
    CONFIGURATION_STALE,
)
from ..vsp.contracts.base import Receipt
from ..analysis.manager import AnalysisManager
from ..io import config_catalog as _config_catalog
from ..io import op_catalog as _op_catalog
from ..io import results_index as _results_index
from ..analysis.test_analyses import register_test_analyses  # new import
from ..core.logging import get_logger
from ..vsp import session as vsp_session

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionJob:
    """Track a job submitted through the AnalysisManager."""
    job_id: str
    analysis_key: str
    ticket_payload: Dict[str, Any]
    context: Dict[str, Any]
    submitted_at: datetime = field(default_factory=_utcnow)
    status: str = "pending"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    ticket_sha: Optional[str] = None
    receipt: Optional[Receipt] = None
    error: Optional[str] = None


@dataclass
class SessionState:
    config_catalog: List[ConfigSummary] = field(default_factory=list)
    op_catalog: List[OperatingPointSummary] = field(default_factory=list)
    results_index: List[ResultIndexEntry] = field(default_factory=list)
    jobs: Dict[str, SessionJob] = field(default_factory=dict)


@dataclass
class SessionConfig:
    projects_root: Path
    project_id: str
    open_gui: bool = False
    auto_start_workers: bool = True

    @property
    def project_root(self) -> Path:
        return self.projects_root / self.project_id


class ProjectSession:
    """Owns an AnalysisManager, catalog state, and optionally launches the OpenVSP GUI."""

    def __init__(self, config: SessionConfig, *, event_bus=None) -> None:
        self.config = config
        self.project_root = config.project_root
        self.state = SessionState()
        self._event_bus = event_bus or get_global_event_bus()
        if self._event_bus is None:
            try:
                from .event_bus import EventBus  # type: ignore
                bus = EventBus()
                set_global_event_bus(bus)
                self._event_bus = bus
            except Exception:
                pass
        results_dir = self.project_root / "results"
        try:
            results_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Initialize AnalysisManager (headless unless open_gui True)
        self.manager = AnalysisManager(results_root=results_dir, open_gui=config.open_gui)
        try:
            register_test_analyses(self.manager)
        except Exception:
            pass
        # Attempt GUI launch (no auto-launch in tests because open_gui False there)
        if config.open_gui:
            vsp_mod = self.manager.vsp
            if vsp_mod and vsp_session.supports_gui(vsp_mod):
                try:
                    vsp_session.start_gui(vsp_mod, strict=False)
                except Exception as exc:  # pragma: no cover - GUI failure logging
                    logger.warning(
                        "OpenVSP GUI launch failed", hint=str(exc)
                    )
            else:
                logger.debug(
                    "GUI not started: supports_gui=False or vsp missing",
                    context={
                        "vsp_available": vsp_mod is not None,
                        "supports_gui": bool(vsp_mod and vsp_session.supports_gui(vsp_mod)),
                    },
                )
        # Load catalogs
        self.refresh_catalogs()
        self.refresh_results_index()

    # --- Catalog / results refresh ---
    def _load_catalogs(self) -> None:
        try:
            self.state.config_catalog = load_config_catalog(self.project_root)
        except Exception as exc:
            logger.warning("Failed to load config catalog", hint=str(exc))
        try:
            self.state.op_catalog = load_op_catalog(self.project_root)
        except Exception as exc:
            logger.warning("Failed to load operating point catalog", hint=str(exc))

    def refresh_catalogs(self):
        self._load_catalogs()

    def refresh_results_index(self):
        try:
            self.state.results_index = load_result_entries(self.project_root / "results") or []
        except Exception:
            self.state.results_index = []

    # Placeholder methods for compatibility (can be expanded later)
    def submit(self, *args, **kwargs):  # pragma: no cover - passthrough
        return self.manager.submit(*args, **kwargs)

    def start_revalidation_loop(self, *_, **__):  # pragma: no cover
        pass

    def start_analysis_worker(self, *_, **__):  # pragma: no cover
        pass

    def stop(self):  # pragma: no cover
        try:
            self.manager.shutdown()
        except Exception:
            pass

# Convenience factory

def create_project_session(project_id: str, *, projects_root: Path, open_gui: bool = False) -> ProjectSession:
    cfg = SessionConfig(projects_root=projects_root, project_id=project_id, open_gui=open_gui)
    return ProjectSession(cfg)

