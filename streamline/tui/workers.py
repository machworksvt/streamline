from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ..analysis.manager import AnalysisManager
from .event_bus import EventBus
from .events import WorkerFailed


class AnalysisWorker(threading.Thread):
    """Background helper that drains the AnalysisManager queue."""

    def __init__(
        self,
        *,
        manager: AnalysisManager,
        session_id: str,
        event_bus: EventBus,
        sync_callback: Callable[[], None],
        poll_interval: float = 0.5,
    ) -> None:
        super().__init__(daemon=True)
        self._manager = manager
        self._session_id = session_id
        self._event_bus = event_bus
        self._sync_callback = sync_callback
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()

    def run(self) -> None:  # pragma: no cover - exercised via higher-level tests
        while not self._stop_event.is_set():
            job_was_processed = False
            try:
                receipt = self._manager.run_next(block=True, timeout=self._poll_interval)
                # A job was attempted if run_next didn't return None
                # This includes: completed, cached, failed, or dependency-blocked jobs
                job_was_processed = (receipt is not None)
            except Exception as exc:  # noqa: BLE001 - propagate through event bus
                # An exception means a job was attempted but failed catastrophically
                job_was_processed = True
                self._event_bus.publish(
                    WorkerFailed(
                        session_id=self._session_id,
                        message="Analysis worker encountered an error",
                        details=str(exc),
                    )
                )
            
            # DO NOT call sync_callback from worker thread - it can cause deadlock
            # The manager publishes job events that the UI can react to
            # The UI thread should call sync_job_states() in response to events
        
        # Final sync so the UI sees terminal job states when the worker stops.
        # This is safe because worker is stopping, no more jobs will run
        try:
            self._sync_callback()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()
