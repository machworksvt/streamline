from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.schema import ProjectDefinition
from ..io.config_catalog import ConfigSummary
from ..io.op_catalog import OperatingPointSummary
from ..io.results_index import ResultIndexEntry
from ..vsp.contracts.base import Receipt


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
    finished: bool = False


@dataclass
class SessionState:
    """Aggregate representation of the data the TUI needs."""

    project_root: Path
    project_id: str
    project_def: ProjectDefinition
    config_catalog: List[ConfigSummary] = field(default_factory=list)
    op_catalog: List[OperatingPointSummary] = field(default_factory=list)
    cache_entries: List[Dict[str, Any]] = field(default_factory=list)
    results_index: List[ResultIndexEntry] = field(default_factory=list)
    jobs: Dict[str, SessionJob] = field(default_factory=dict)


@dataclass
class SessionConfig:
    """User-configurable knobs controlling a project session."""

    projects_root: Path
    project_id: str
    open_gui: bool = False
    auto_start_workers: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "projects_root", Path(self.projects_root))

