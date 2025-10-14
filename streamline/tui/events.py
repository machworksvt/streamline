from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import time

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Core event type strings (central source)
CATALOG_CHANGED = "CatalogChanged"
CONFIGURATION_CREATED = "ConfigurationCreated"
CONFIGURATION_UPDATED = "ConfigurationUpdated"
CONFIGURATION_STALE = "ConfigurationStale"
JOB_SUBMITTED = "JobSubmitted"
JOB_STARTED = "JobStarted"
JOB_COMPLETED = "JobCompleted"
JOB_FAILED = "JobFailed"
RECEIPT_ADDED = "ReceiptAdded"
DERIVED_DATA_UPDATED = "DerivedDataUpdated"
LOG_MESSAGE = "LogMessage"

ALL_EVENT_TYPES = {
    CATALOG_CHANGED,
    CONFIGURATION_CREATED,
    CONFIGURATION_UPDATED,
    CONFIGURATION_STALE,
    JOB_SUBMITTED,
    JOB_STARTED,
    JOB_COMPLETED,
    JOB_FAILED,
    RECEIPT_ADDED,
    DERIVED_DATA_UPDATED,
    LOG_MESSAGE,
}

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

# Convenience constructors
def build_event(evt_type: str, payload: Optional[Dict[str, Any]] = None, *, ts_provider=None) -> Event:
    import time
    if evt_type not in ALL_EVENT_TYPES:
        # Allow extension without crashing; could log a warning
        pass
    return Event(type=evt_type, payload=payload or {}, ts=(ts_provider() if ts_provider else time.time()))


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
