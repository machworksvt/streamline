from __future__ import annotations

import threading
from pathlib import Path

import pytest

from streamline.analysis.manager import AnalysisManager
from streamline.main import create_new_project
from streamline.tui import (
    AnalysisJobStatusChanged,
    CacheIndexUpdated,
    EventBus,
    ProjectSession,
    ResultsIndexUpdated,
    SessionConfig,
)
from streamline.tui.events import SessionEvent
from streamline.analysis.contracts import Ticket

from tests.support.dummy_analysis import register_dummy_analysis


def test_event_bus_dispatches_to_base_and_specific_handlers() -> None:
    bus = EventBus()
    base_events: list[str] = []
    specific_events: list[str] = []

    def on_session(event) -> None:
        base_events.append(event.__class__.__name__)

    def on_status(event: AnalysisJobStatusChanged) -> None:
        specific_events.append(event.status)

    bus.subscribe(SessionEvent, on_session)
    bus.subscribe(AnalysisJobStatusChanged, on_status)

    bus.publish(
        AnalysisJobStatusChanged(
            session_id="session",
            job_id="job",
            analysis_key="dummy",
            status="completed",
            ticket_sha="abc",
            started_at=None,
            ended_at=None,
        )
    )

    assert base_events == ["AnalysisJobStatusChanged"]
    assert specific_events == ["completed"]


@pytest.fixture()
def project_workspace(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    create_new_project(projects_root, "demo")
    return projects_root


def test_project_session_executes_dummy_analysis(project_workspace: Path) -> None:
    project_id = "demo"

    def manager_factory(path: Path) -> AnalysisManager:
        manager = AnalysisManager(vsp=object(), results_root=path, auto_init_vsp=False, open_gui=False)
        register_dummy_analysis(manager)
        return manager

    bus = EventBus()
    completion_signal = threading.Event()
    cache_signal = threading.Event()
    results_signal = threading.Event()
    statuses: list[str] = []

    def on_status(event: AnalysisJobStatusChanged) -> None:
        statuses.append(event.status)
        if event.status in {"completed", "cached"}:
            completion_signal.set()

    bus.subscribe(AnalysisJobStatusChanged, on_status)

    def on_cache(event: CacheIndexUpdated) -> None:
        if event.entry_count > 0:
            cache_signal.set()

    def on_results(event: ResultsIndexUpdated) -> None:
        if event.entry_count > 0:
            results_signal.set()

    bus.subscribe(CacheIndexUpdated, on_cache)
    bus.subscribe(ResultsIndexUpdated, on_results)

    session = ProjectSession.open(
        config=SessionConfig(projects_root=project_workspace, project_id=project_id, auto_start_workers=True),
        event_bus=bus,
        manager_factory=manager_factory,
    )
    try:
        job = session.queue_analysis("dummy", Ticket())
        assert completion_signal.wait(timeout=5.0)
        assert cache_signal.wait(timeout=2.0)
        assert results_signal.wait(timeout=2.0)
        assert session.state.jobs[job.job_id].status in {"completed", "cached"}
        assert session.state.cache_entries
        assert session.state.results_index
        assert statuses[-1] in {"completed", "cached"}
    finally:
        session.shutdown()

