from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Event:
    """Base marker for all TUI events."""

    emitted_at: datetime = field(default_factory=_utcnow, init=False)


@dataclass(frozen=True)
class SessionEvent(Event):
    """Event scoped to a particular TUI project session."""

    session_id: str


@dataclass(frozen=True)
class AnalysisJobEvent(SessionEvent):
    """Base payload for job-level events coming from the AnalysisManager."""

    job_id: str
    analysis_key: str


@dataclass(frozen=True)
class AnalysisJobQueued(AnalysisJobEvent):
    """Raised when a job is submitted to the AnalysisManager queue."""

    ticket_payload: Dict[str, Any]
    context: Dict[str, Any]
    submitted_at: datetime


@dataclass(frozen=True)
class AnalysisJobStatusChanged(AnalysisJobEvent):
    """Raised whenever the associated job transitions to a new status."""

    status: str
    ticket_sha: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    error: Optional[str] = None
    receipt_summary: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CacheIndexUpdated(SessionEvent):
    """Emitted when the cached receipts index is refreshed."""

    entry_count: int


@dataclass(frozen=True)
class ResultsIndexUpdated(SessionEvent):
    """Emitted when the persistent results index is refreshed."""

    entry_count: int


@dataclass(frozen=True)
class ProjectAssetsRefreshed(SessionEvent):
    """Indicates configuration and operating-point catalogs were reloaded."""

    config_count: int
    op_count: int


@dataclass(frozen=True)
class WorkerFailed(SessionEvent):
    """Raised when a background worker encounters an unhandled exception."""

    message: str
    details: Optional[str] = None
