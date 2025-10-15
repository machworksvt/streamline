from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import time

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

@dataclass(frozen=True)
class Event:
    type: str = ""  # auto-filled with class name if empty
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=lambda: time.time())
    def __post_init__(self):  # auto-assign type if not provided
        if not self.type:
            object.__setattr__(self, 'type', self.__class__.__name__)
    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


@dataclass(frozen=True)
class SessionEvent(Event):
    """Event scoped to a particular TUI project session."""
    session_id: str = ""


@dataclass(frozen=True)
class AnalysisJobEvent(SessionEvent):
    """Base payload for job-level events coming from the AnalysisManager."""
    job_id: str = ""
    analysis_key: str = ""


@dataclass(frozen=True)
class AnalysisJobQueued(AnalysisJobEvent):
    """Raised when a job is submitted to the AnalysisManager queue."""
    ticket_payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    submitted_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class AnalysisJobStatusChanged(AnalysisJobEvent):
    """Raised whenever the associated job transitions to a new status."""
    status: str = ""
    ticket_sha: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    receipt_summary: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CacheIndexUpdated(SessionEvent):
    """Emitted when the cached receipts index is refreshed."""
    entry_count: int = 0


@dataclass(frozen=True)
class ResultsIndexUpdated(SessionEvent):
    """Emitted when the persistent results index is refreshed."""
    entry_count: int = 0


@dataclass(frozen=True)
class ProjectAssetsRefreshed(SessionEvent):
    """Indicates configuration and operating-point catalogs were reloaded."""
    config_count: int = 0
    op_count: int = 0


@dataclass(frozen=True)
class WorkerFailed(SessionEvent):
    """Raised when a background worker encounters an unhandled exception."""
    message: str = ""
    details: Optional[str] = None


# ---------------------------------------------------------------------------
# Generic manager-level events (preferred over raw string identifiers)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManagerEvent(Event):
    """Base class for manager-centric events that are not session-scoped."""


@dataclass(frozen=True)
class JobEvent(ManagerEvent):
    job_id: str = ""
    analysis_key: str = ""


@dataclass(frozen=True)
class JobSubmittedEvent(JobEvent):
    ticket_payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    wait_for: Tuple[str, ...] = tuple()
    priority: int = 0
    submitted_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class JobStartedEvent(JobEvent):
    started_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class JobFailedEvent(JobEvent):
    error: str = ""
    failed_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class JobCompletedEvent(JobEvent):
    ticket_sha: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: datetime = field(default_factory=_utcnow)
    receipt_summary: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ReceiptAddedEvent(JobEvent):
    ticket_sha: Optional[str] = None
    receipt_summary: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class LogMessageEvent(ManagerEvent):
    level: str = ""
    name: str = ""
    message: str = ""


# ---------------------------------------------------------------------------
# Catalog / configuration events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogEvent(Event):
    project: Optional[str] = None


@dataclass(frozen=True)
class CatalogChangedEvent(CatalogEvent):
    kind: str = ""
    identifiers: Tuple[str, ...] = tuple()
    reason: Optional[str] = None


@dataclass(frozen=True)
class ConfigurationEvent(CatalogEvent):
    config_id: str = ""


@dataclass(frozen=True)
class ConfigurationCreatedEvent(ConfigurationEvent):
    source: Optional[str] = None  # e.g. "mode", "snapshot"


@dataclass(frozen=True)
class ConfigurationUpdatedEvent(ConfigurationEvent):
    changes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfigurationRemovedEvent(ConfigurationEvent):
    reason: Optional[str] = None


@dataclass(frozen=True)
class ConfigurationStaleEvent(ConfigurationEvent):
    errors: Tuple[str, ...] = tuple()

