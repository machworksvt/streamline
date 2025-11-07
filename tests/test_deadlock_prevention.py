"""Tests for deadlock prevention in multithreaded analysis execution and event handling.

This module tests the interaction between:
- AnalysisWorker thread executing jobs
- AnalysisManager lock management
- EventBus event publication
- ProjectSession job state synchronization
- UI thread event handling via call_from_thread simulation

These tests ensure that the system doesn't deadlock under concurrent load.
"""

import threading
import time
from pathlib import Path
from queue import Queue
from typing import List, Optional
import pytest

from streamline.analysis.manager import AnalysisManager
from streamline.tui.session import ProjectSession
from streamline.tui.event_bus import EventBus
from streamline.tui.events import (
    AnalysisJobQueued,
    AnalysisJobStatusChanged,
    LogMessageEvent,
)
from streamline.vsp.contracts.compute_geometry import ComputeGeometryTicket
from streamline.core.schema import Configuration


class DeadlockDetector:
    """Helper to detect potential deadlocks by monitoring thread progress."""
    
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self.checkpoints: dict[str, float] = {}
        self.lock = threading.Lock()
        self.failed = False
        self.failure_reason: Optional[str] = None
    
    def checkpoint(self, name: str) -> None:
        """Mark that a thread has reached a checkpoint."""
        with self.lock:
            self.checkpoints[name] = time.time()
    
    def verify_progress(self, checkpoint_name: str, message: str, timeout_override: Optional[float] = None) -> None:
        """Verify that a checkpoint was reached within the timeout.
        
        Args:
            checkpoint_name: The checkpoint to wait for
            message: Error message if timeout occurs
            timeout_override: Optional timeout override for long-running operations (e.g., 60s for real VSP analyses)
        """
        timeout = timeout_override if timeout_override is not None else self.timeout
        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if checkpoint_name in self.checkpoints:
                    return
            time.sleep(0.1)
        
        with self.lock:
            self.failed = True
            self.failure_reason = f"DEADLOCK: {message} (checkpoint '{checkpoint_name}' not reached within {timeout}s)"
    
    def assert_no_deadlock(self):
        """Raise assertion if deadlock was detected."""
        if self.failed:
            raise AssertionError(self.failure_reason)


class EventCollector:
    """Collects events published to the bus for verification."""
    
    def __init__(self, event_bus: EventBus):
        self.events: List = []
        self.lock = threading.Lock()
        self.event_bus = event_bus
        self._subscription = event_bus.subscribe_any(self._collect)
    
    def _collect(self, event):
        with self.lock:
            self.events.append(event)
    
    def wait_for_event(self, event_type, timeout: float = 5.0) -> bool:
        """Wait for a specific event type to be published."""
        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if any(isinstance(e, event_type) for e in self.events):
                    return True
            time.sleep(0.1)
        return False
    
    def get_events(self, event_type):
        """Get all events of a specific type."""
        with self.lock:
            return [e for e in self.events if isinstance(e, event_type)]
    
    def cleanup(self):
        """Remove subscription."""
        self._subscription.cancel()


@pytest.fixture
def mock_vsp():
    """Provide a minimal mock VSP object."""
    class MockVSP:
        def Update(self):
            # Simulate some work
            time.sleep(0.01)
    
    return MockVSP()


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project structure."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()
    
    # Create minimal project structure with all required fields
    import json
    project_def = {
        "project_id": "test_project",
        "aircraft_file": "test.vsp3",
        "default_set": "Set_0",
        "uav": {
            "name": "Test UAV",
            "mtow_kg": 25.0,
            "cruise_speed_mps": 20.0,
            "endurance_hours": 1.0,
            "dod_group": "Group 2",  # Must be one of the literal values
            "propulsion_type": "electric_prop"  # Must be one of the literal values
        }
    }
    (project_root / f"{project_root.name}.json").write_text(json.dumps(project_def))
    (project_root / "configs").mkdir()
    (project_root / "operating_points").mkdir()
    (project_root / "results").mkdir()
    
    return project_root


def test_concurrent_job_execution_no_deadlock(mock_vsp, temp_project):
    """Test that concurrent job execution and event handling doesn't deadlock."""
    
    detector = DeadlockDetector(timeout=10.0)
    event_bus = EventBus()
    collector = EventCollector(event_bus)
    
    # Create manager with real VSP lock
    manager = AnalysisManager(
        vsp=mock_vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    # Register a test analysis that simulates work
    def test_runner(vsp, ticket):
        detector.checkpoint("analysis_started")
        time.sleep(0.05)  # Simulate analysis work
        detector.checkpoint("analysis_completed")
        return {"result": "success"}
    
    def materializer(manager, job, ticket_sha, result, started, ended):
        from streamline.analysis.contracts import Receipt
        from streamline.core.schema import RunManifest
        manifest = RunManifest(
            started_utc=started.isoformat(),
            ended_utc=ended.isoformat(),
            inputs_sha256=ticket_sha,
        )
        return Receipt(ticket_sha256=ticket_sha, run_manifest=manifest)
    
    manager.register_analysis(
        "test_analysis",
        test_runner,
        materializer=materializer,
        uses_vsp_lock=True,
    )
    
    # Submit multiple jobs
    tickets = []
    for i in range(3):
        ticket = type('TestTicket', (), {
            'sha256': lambda self, ctx=None: f"test_sha_{i}",
            'model_dump': lambda self, **kwargs: {"test": f"ticket_{i}"},
        })()
        tickets.append(ticket)
    
    job_ids = []
    for ticket in tickets:
        job_id = manager.submit("test_analysis", ticket)
        job_ids.append(job_id)
        detector.checkpoint(f"job_submitted_{len(job_ids)}")
    
    # Simulate worker thread executing jobs
    def worker_thread():
        detector.checkpoint("worker_started")
        for i in range(3):
            receipt = manager.run_next(block=False)
            if receipt:
                detector.checkpoint(f"job_executed_{i+1}")
        detector.checkpoint("worker_completed")
    
    # Simulate UI thread handling events
    def ui_thread():
        detector.checkpoint("ui_started")
        # Simulate processing events (like call_from_thread does)
        for _ in range(10):
            time.sleep(0.02)
            # Simulate UI updates that might interact with locks
            _ = [j for j in manager.pending_jobs()]
        detector.checkpoint("ui_completed")
    
    # Start threads
    worker = threading.Thread(target=worker_thread, daemon=True)
    ui = threading.Thread(target=ui_thread, daemon=True)
    
    worker.start()
    ui.start()
    
    # Verify progress on both threads
    detector.verify_progress("worker_started", "Worker thread never started")
    detector.verify_progress("ui_started", "UI thread never started")
    detector.verify_progress("job_executed_1", "First job never completed")
    detector.verify_progress("worker_completed", "Worker thread never completed all jobs")
    detector.verify_progress("ui_completed", "UI thread never completed")
    
    # Wait for threads to finish
    worker.join(timeout=5.0)
    ui.join(timeout=5.0)
    
    # Assert no deadlock detected
    detector.assert_no_deadlock()
    
    # Verify all jobs completed
    assert not worker.is_alive(), "Worker thread is still running (possible deadlock)"
    assert not ui.is_alive(), "UI thread is still running (possible deadlock)"
    
    collector.cleanup()


def test_sync_job_states_no_deadlock(mock_vsp, temp_project):
    """Test that ProjectSession.sync_job_states doesn't deadlock when called concurrently."""
    
    detector = DeadlockDetector(timeout=10.0)
    event_bus = EventBus()
    collector = EventCollector(event_bus)
    
    # Create manager
    manager = AnalysisManager(
        vsp=mock_vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    # Register test analysis
    def slow_analysis(vsp, ticket):
        detector.checkpoint("slow_analysis_running")
        time.sleep(0.1)  # Simulate slow work
        detector.checkpoint("slow_analysis_done")
        return {"result": "success"}
    
    def materializer(manager, job, ticket_sha, result, started, ended):
        from streamline.analysis.contracts import Receipt
        from streamline.core.schema import RunManifest
        manifest = RunManifest(
            started_utc=started.isoformat(),
            ended_utc=ended.isoformat(),
            inputs_sha256=ticket_sha,
        )
        return Receipt(ticket_sha256=ticket_sha, run_manifest=manifest)
    
    manager.register_analysis(
        "slow_analysis",
        slow_analysis,
        materializer=materializer,
        uses_vsp_lock=True,
    )
    
    # Create session
    from streamline.tui.context import SessionConfig
    config = SessionConfig(
        projects_root=temp_project.parent,
        project_id="test",
        open_gui=False,
        auto_start_workers=False,  # Manual control
    )
    
    session = ProjectSession(
        project_root=temp_project,
        manager=manager,
        config=config,
        event_bus=event_bus,
    )
    
    # Submit job
    ticket = type('TestTicket', (), {
        'sha256': lambda self, ctx=None: "test_sha_sync",
        'model_dump': lambda self, **kwargs: {"test": "sync_ticket"},
        'model_dump_json': lambda self, **kwargs: '{"test": "sync_ticket"}',
    })()
    
    job = session.queue_analysis("slow_analysis", ticket)
    detector.checkpoint("job_queued")
    
    # Simulate worker executing job WITHOUT calling sync
    def worker_thread():
        detector.checkpoint("worker_sync_started")
        receipt = manager.run_next(block=True, timeout=2.0)
        # NOTE: Worker no longer calls sync_callback - that's the fix!
        detector.checkpoint("worker_sync_completed")
    
    # Simulate UI thread responding to events by calling sync
    # (mimics what the real app does in _handle_event)
    def ui_sync_thread():
        detector.checkpoint("ui_sync_started")
        # Wait for worker to complete, then sync
        time.sleep(0.2)
        for _ in range(3):
            try:
                session.sync_job_states()
            except Exception:
                pass
            time.sleep(0.05)
        detector.checkpoint("ui_sync_completed")
    
    # Start threads
    worker = threading.Thread(target=worker_thread, daemon=True)
    ui_sync = threading.Thread(target=ui_sync_thread, daemon=True)
    
    worker.start()
    ui_sync.start()
    
    # Verify progress
    detector.verify_progress("worker_sync_started", "Worker never started")
    detector.verify_progress("ui_sync_started", "UI sync thread never started")
    detector.verify_progress("worker_sync_completed", "Worker never completed (possible deadlock)")
    detector.verify_progress("ui_sync_completed", "UI sync never completed (possible deadlock)")
    
    # Wait for completion
    worker.join(timeout=5.0)
    ui_sync.join(timeout=5.0)
    
    detector.assert_no_deadlock()
    
    # Verify threads finished
    assert not worker.is_alive(), "Worker still running"
    assert not ui_sync.is_alive(), "UI sync thread still running"
    
    collector.cleanup()


def test_event_publishing_during_lock_holding_no_deadlock(mock_vsp, temp_project):
    """Test that publishing events while holding manager lock doesn't deadlock event handlers."""
    
    detector = DeadlockDetector(timeout=10.0)
    event_bus = EventBus()
    collector = EventCollector(event_bus)
    
    # Track event handler execution
    handler_calls = Queue()
    
    def slow_event_handler(event):
        """Event handler that simulates slow UI operations."""
        detector.checkpoint(f"handler_called_{type(event).__name__}")
        handler_calls.put(type(event).__name__)
        time.sleep(0.02)  # Simulate UI work
        detector.checkpoint(f"handler_done_{type(event).__name__}")
    
    # Subscribe to all events
    event_bus.subscribe_any(slow_event_handler)
    
    # Create manager
    manager = AnalysisManager(
        vsp=mock_vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    def test_analysis(vsp, ticket):
        detector.checkpoint("analysis_with_events_started")
        # This will publish events while holding manager lock
        time.sleep(0.05)
        detector.checkpoint("analysis_with_events_done")
        return {"result": "done"}
    
    def materializer(manager, job, ticket_sha, result, started, ended):
        from streamline.analysis.contracts import Receipt
        from streamline.core.schema import RunManifest
        manifest = RunManifest(
            started_utc=started.isoformat(),
            ended_utc=ended.isoformat(),
            inputs_sha256=ticket_sha,
        )
        return Receipt(ticket_sha256=ticket_sha, run_manifest=manifest)
    
    manager.register_analysis(
        "event_test",
        test_analysis,
        materializer=materializer,
        uses_vsp_lock=True,
    )
    
    # Submit jobs
    for i in range(2):
        ticket = type('TestTicket', (), {
            'sha256': lambda self, ctx=None, idx=i: f"evt_sha_{idx}",
            'model_dump': lambda self, idx=i, **kwargs: {"test": f"evt_{idx}"},
        })()
        manager.submit("event_test", ticket)
    
    # Execute in worker thread
    def worker():
        detector.checkpoint("event_worker_started")
        manager.run_next(block=False)
        manager.run_next(block=False)
        detector.checkpoint("event_worker_done")
    
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    
    # Verify progress
    detector.verify_progress("event_worker_started", "Event worker never started")
    detector.verify_progress("analysis_with_events_started", "Analysis never started")
    detector.verify_progress("analysis_with_events_done", "Analysis never completed (possible deadlock)")
    detector.verify_progress("event_worker_done", "Event worker never completed")
    
    worker_thread.join(timeout=5.0)
    
    detector.assert_no_deadlock()
    assert not worker_thread.is_alive(), "Event worker still running"
    
    collector.cleanup()


def test_vsp_lock_gui_lock_interaction_no_deadlock(mock_vsp, temp_project):
    """Test that VSP lock and GUI lock/unlock don't cause deadlock."""
    
    detector = DeadlockDetector(timeout=10.0)
    
    # Track GUI lock state
    gui_locked = []
    
    class MockVSPWithGUI:
        def Lock(self):
            gui_locked.append("locked")
            detector.checkpoint("gui_locked")
            time.sleep(0.01)  # Simulate lock operation
        
        def Unlock(self):
            gui_locked.append("unlocked")
            detector.checkpoint("gui_unlocked")
        
        def UpdateGUI(self):
            pass
        
        def Update(self):
            time.sleep(0.01)
    
    vsp = MockVSPWithGUI()
    manager = AnalysisManager(
        vsp=vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    def gui_analysis(vsp_obj, ticket):
        detector.checkpoint("gui_analysis_started")
        time.sleep(0.05)
        detector.checkpoint("gui_analysis_done")
        return {"result": "gui_test"}
    
    def materializer(manager, job, ticket_sha, result, started, ended):
        from streamline.analysis.contracts import Receipt
        from streamline.core.schema import RunManifest
        manifest = RunManifest(
            started_utc=started.isoformat(),
            ended_utc=ended.isoformat(),
            inputs_sha256=ticket_sha,
        )
        return Receipt(ticket_sha256=ticket_sha, run_manifest=manifest)
    
    manager.register_analysis(
        "gui_test",
        gui_analysis,
        materializer=materializer,
        uses_vsp_lock=True,
    )
    
    # Submit job
    ticket = type('TestTicket', (), {
        'sha256': lambda self, ctx=None: "gui_sha",
        'model_dump': lambda self, **kwargs: {"test": "gui"},
    })()
    
    manager.submit("gui_test", ticket)
    
    # Execute
    detector.checkpoint("gui_test_started")
    receipt = manager.run_next(block=False)
    detector.checkpoint("gui_test_completed")
    
    # Verify
    detector.verify_progress("gui_locked", "GUI was never locked")
    detector.verify_progress("gui_unlocked", "GUI was never unlocked (possible deadlock)")
    detector.verify_progress("gui_analysis_done", "Analysis with GUI lock never completed")
    
    detector.assert_no_deadlock()
    
    # Verify lock/unlock sequence
    assert "locked" in gui_locked, "GUI Lock() was never called"
    assert "unlocked" in gui_locked, "GUI Unlock() was never called"
    assert gui_locked.index("locked") < gui_locked.index("unlocked"), "GUI unlocked before locked"


def test_no_deadlock_on_failed_job(mock_vsp, temp_project):
    """Test that failed jobs don't cause deadlock in event handling or syncing."""
    
    detector = DeadlockDetector(timeout=10.0)
    event_bus = EventBus()
    collector = EventCollector(event_bus)
    
    manager = AnalysisManager(
        vsp=mock_vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    def failing_analysis(vsp, ticket):
        detector.checkpoint("failing_analysis_started")
        time.sleep(0.02)
        detector.checkpoint("about_to_fail")
        raise ValueError("Intentional failure for testing")
    
    manager.register_analysis(
        "failing",
        failing_analysis,
        uses_vsp_lock=True,
    )
    
    ticket = type('TestTicket', (), {
        'sha256': lambda self, ctx=None: "fail_sha",
        'model_dump': lambda self, **kwargs: {"test": "fail"},
    })()
    
    manager.submit("failing", ticket)
    
    # Execute (should not deadlock even though job fails)
    detector.checkpoint("executing_failing_job")
    try:
        manager.run_next(block=False)
    except ValueError:
        pass  # Expected
    
    detector.checkpoint("failing_job_handled")
    
    # Verify
    detector.verify_progress("about_to_fail", "Job never reached failure point")
    detector.verify_progress("failing_job_handled", "Failed job was never handled (possible deadlock)")
    
    detector.assert_no_deadlock()
    
    collector.cleanup()


def test_call_from_thread_deadlock_with_event_bus(mock_vsp, temp_project):
    """Test that reproduces the EXACT deadlock seen in the app.
    
    The deadlock happens because:
    1. Worker thread publishes JobSubmittedEvent while in _execute_job
    2. Event handler tries to use call_from_thread to reach UI
    3. call_from_thread blocks waiting for event loop
    4. Worker is still in _execute_job doing cache checks (holding locks)
    5. Event loop can't process because worker is blocked
    6. DEADLOCK
    """
    
    detector = DeadlockDetector(timeout=10.0)
    event_bus = EventBus()
    
    # Track call_from_thread calls
    call_from_thread_called = threading.Event()
    call_from_thread_completed = threading.Event()
    
    def mock_call_from_thread(callback):
        """Simulate Textual's call_from_thread blocking behavior."""
        detector.checkpoint("call_from_thread_invoked")
        call_from_thread_called.set()
        # This simulates the blocking - waiting for event loop to process
        # In the real app, this blocks until Textual's event loop runs the callback
        time.sleep(0.5)  # Simulate event loop delay
        detector.checkpoint("call_from_thread_executing_callback")
        callback()
        detector.checkpoint("call_from_thread_completed")
        call_from_thread_completed.set()
    
    # Create manager
    manager = AnalysisManager(
        vsp=mock_vsp,
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    # Register analysis with SLOW cache validation (simulates disk I/O)
    def slow_analysis(vsp, ticket):
        detector.checkpoint("analysis_running")
        time.sleep(0.05)
        return {"result": "success"}
    
    def materializer(manager, job, ticket_sha, result, started, ended):
        from streamline.analysis.contracts import Receipt
        from streamline.core.schema import RunManifest
        manifest = RunManifest(
            started_utc=started.isoformat(),
            ended_utc=ended.isoformat(),
            inputs_sha256=ticket_sha,
        )
        # Create a receipt that will cause cache validation to do I/O
        receipt = Receipt(ticket_sha256=ticket_sha, run_manifest=manifest)
        receipt.artifact_dir = "test_artifact"
        return receipt
    
    manager.register_analysis(
        "slow_cache_analysis",
        slow_analysis,
        materializer=materializer,
        uses_vsp_lock=True,
    )
    
    # Create event handler that simulates the app's behavior
    def event_handler(event):
        """Simulates StreamlineApp._handle_event_from_bus."""
        detector.checkpoint("event_handler_called")
        # This is what the app does - uses call_from_thread
        mock_call_from_thread(lambda: detector.checkpoint("ui_event_processed"))
    
    event_bus.subscribe_any(event_handler)
    
    # Submit job
    ticket = type('TestTicket', (), {
        'sha256': lambda self, ctx=None: "deadlock_test_sha",
        'model_dump': lambda self, **kwargs: {"test": "deadlock"},
    })()
    
    job_id = manager.submit("slow_cache_analysis", ticket)
    detector.checkpoint("job_submitted")
    
    # Worker thread executes job
    def worker_thread():
        detector.checkpoint("worker_started")
        try:
            # This is where the deadlock happens in the real app
            receipt = manager.run_next(block=False)
            detector.checkpoint("worker_completed")
        except Exception as exc:
            detector.checkpoint(f"worker_failed: {exc}")
    
    worker = threading.Thread(target=worker_thread, daemon=True)
    worker.start()
    
    # Verify checkpoints
    detector.verify_progress("worker_started", "Worker never started")
    detector.verify_progress("job_submitted", "Job never submitted")
    
    # This is the critical check - did the worker complete?
    # In the real app, it hangs here because:
    # - Worker publishes event
    # - Event handler blocks on call_from_thread
    # - Worker is doing cache I/O (slow)
    # - Textual event loop can't process because worker hasn't finished
    detector.verify_progress("worker_completed", "Worker never completed - DEADLOCK!", timeout_override=15.0)
    
    worker.join(timeout=10.0)
    detector.assert_no_deadlock()
    
    assert not worker.is_alive(), "Worker thread still running - deadlock occurred"


def test_cache_entry_blocks_during_validation(temp_project):
    """Test that cache_entry() can block on I/O during receipt validation.
    
    This reproduces the specific code path where the deadlock occurs.
    """
    
    detector = DeadlockDetector(timeout=10.0)
    
    class SlowVSP:
        def Update(self):
            time.sleep(0.01)
    
    manager = AnalysisManager(
        vsp=SlowVSP(),
        results_root=temp_project / "results",
        auto_init_vsp=False,
    )
    
    # Create a fake cache entry with an artifact
    from streamline.analysis.contracts import Receipt
    from streamline.core.schema import RunManifest
    
    manifest = RunManifest(
        started_utc="2025-01-01T00:00:00",
        ended_utc="2025-01-01T00:01:00",
        inputs_sha256="test_sha",
    )
    receipt = Receipt(ticket_sha256="test_sha", run_manifest=manifest)
    receipt.artifact_dir = "slow_io_test"
    
    # Create the artifact directory with manifest
    artifact_path = temp_project / "results" / "slow_io_test"
    artifact_path.mkdir(parents=True)
    manifest_file = artifact_path / "run_manifest.json"
    manifest_file.write_text('{"inputs_sha256": "test_sha"}')
    
    # Register and cache
    def dummy_runner(vsp, ticket):
        return {"result": "test"}
    
    manager.register_analysis(
        "io_test",
        dummy_runner,
        uses_vsp_lock=False,
    )
    
    from streamline.analysis.manager import AnalysisCacheEntry
    from datetime import datetime
    
    entry = AnalysisCacheEntry(
        ticket_sha="test_sha",
        receipt=receipt,
        stored_at=datetime.utcnow(),
        dependency_keys=set(),
    )
    
    with manager._lock:
        manager._cache.setdefault("io_test", {})["test_sha"] = entry
    
    # Now test that cache_entry BLOCKS while validating
    # This simulates what happens in _execute_job
    
    def thread1():
        """Simulates worker calling cache_entry during job execution."""
        detector.checkpoint("thread1_started")
        # This acquires lock and does I/O to validate receipt
        result = manager.cache_entry("io_test", "test_sha")
        detector.checkpoint("thread1_got_cache_entry")
        assert result is not None
        detector.checkpoint("thread1_completed")
    
    def thread2():
        """Simulates UI thread trying to get job state."""
        time.sleep(0.05)  # Let thread1 start
        detector.checkpoint("thread2_started")
        # This tries to acquire the same lock
        try:
            with manager._lock:
                detector.checkpoint("thread2_got_lock")
        except Exception:
            pass
        detector.checkpoint("thread2_completed")
    
    t1 = threading.Thread(target=thread1, daemon=True)
    t2 = threading.Thread(target=thread2, daemon=True)
    
    t1.start()
    t2.start()
    
    # Verify both threads make progress
    detector.verify_progress("thread1_started", "Thread 1 never started")
    detector.verify_progress("thread2_started", "Thread 2 never started")
    detector.verify_progress("thread1_completed", "Thread 1 never completed - blocked on I/O?")
    detector.verify_progress("thread2_completed", "Thread 2 never completed - blocked waiting for lock?")
    
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    
    detector.assert_no_deadlock()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
