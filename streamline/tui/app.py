from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, ListView

from ..core import get_logger
from .session import ProjectSummary, StreamlineSession
from .widgets import AnalysisQueueView, PrimaryLayout, ProjectList, ProjectSummaryView


def _default_projects_root() -> Path:
    return Path(__file__).resolve().parents[2] / "projects"


class StreamlineApp(App[None]):
    """First-pass Textual interface for Streamline."""

    CSS_PATH = Path(__file__).with_name("app.tcss")
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_projects", "Refresh"),
    ]

    def __init__(self, projects_root: Optional[Path] = None, *, open_gui: bool = False) -> None:
        super().__init__()
        root = Path(projects_root) if projects_root is not None else _default_projects_root()
        self.session = StreamlineSession(root, open_gui=open_gui)
        self.logger = get_logger(__name__)
        self._active_project: Optional[ProjectSummary] = None

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=True)
        yield Footer()
        yield PrimaryLayout()

    async def on_mount(self) -> None:
        await self._refresh_projects()
        self.set_interval(1.5, self._refresh_queue)

    async def action_refresh_projects(self) -> None:
        await self._refresh_projects()

    async def _refresh_projects(self) -> None:
        project_list = self.query_one(ProjectList)
        summaries = self.session.discover_projects()
        project_list.set_projects(summaries)
        summary_view = self.query_one(ProjectSummaryView)
        if summaries:
            summary_view.show_project(summaries[0])
            project_list.index = 0
            self._set_active_project(summaries[0])
        else:
            summary_view.show_project(None)
            self._set_active_project(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "project-list":
            return
        summary_view = self.query_one(ProjectSummaryView)
        project: Optional[ProjectSummary] = None
        if hasattr(event.item, "data") and isinstance(event.item.data, ProjectSummary):
            project = event.item.data
        summary_view.show_project(project)
        self._set_active_project(project)

    def _set_active_project(self, project: Optional[ProjectSummary]) -> None:
        self._active_project = project
        self.session.bind_results_root(project)
        queue = self.query_one(AnalysisQueueView)
        manager = self.session.analysis_manager if project and self.session.pending_jobs() else None
        queue.refresh_from_manager(manager)

    def _refresh_queue(self) -> None:
        queue = self.query_one(AnalysisQueueView)
        manager = self.session.analysis_manager if self.session.pending_jobs() else None
        queue.refresh_from_manager(manager)

    async def on_shutdown_request(self, event: events.ShutdownRequest) -> None:  # pragma: no cover - UI lifecycle
        self.session.shutdown()
        await super().on_shutdown_request(event)
