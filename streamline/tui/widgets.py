from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Label, ListItem, ListView, Static

from .session import ProjectSummary


class ProjectList(ListView):
    """List projects discovered on disk."""

    projects: reactive[list[ProjectSummary]] = reactive([], init=False)

    def set_projects(self, projects: Iterable[ProjectSummary]) -> None:
        self.clear()
        self.projects = list(projects)
        if not self.projects:
            empty = ListItem(Label("No projects found"), id="empty", disabled=True)
            self.append(empty)
            self.index = 0
            return
        for summary in self.projects:
            label = Label(summary.project_id)
            item = ListItem(label, id=summary.project_id, data=summary)
            self.append(item)
        self.index = 0


class ProjectSummaryView(Static):
    """Display core details about the active project."""

    project: reactive[Optional[ProjectSummary]] = reactive(None, init=False)

    def show_project(self, project: Optional[ProjectSummary]) -> None:
        self.project = project
        if project is None:
            self.update("Select a project to view details.")
            return
        lines = [
            f"[b]{project.project_id}[/b]",
            project.description or "No description provided.",
            "",
            f"Model file: {'available' if project.has_model else 'missing'}",
        ]
        if project.last_run:
            last = project.last_run.strftime("%Y-%m-%d %H:%M")
            lines.append(f"Last analysis: {last} UTC")
        else:
            lines.append("Last analysis: none recorded")
        self.update("\n".join(lines))


class AnalysisQueueView(DataTable):
    """Present pending jobs from the AnalysisManager queue."""

    def on_mount(self) -> None:  # pragma: no cover - UI wiring
        self.add_columns("Job ID", "Analysis", "Status")
        self.cursor_type = "row"

    def refresh_from_manager(self, manager) -> None:
        self.clear(columns=False)
        if manager is None:
            return
        try:
            pending = manager.pending_jobs()
        except Exception:  # pragma: no cover - defensive UI update
            return
        for job_id, state in pending.items():
            status = state.status
            analysis = state.job.analysis_key
            self.add_row(job_id, analysis, status)


class PrimaryLayout(Container):
    """Top-level layout for the Streamline Textual app."""

    def compose(self) -> ComposeResult:  # type: ignore[override]
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label("Projects", classes="section-title")
                yield ProjectList(id="project-list")
            with Vertical(id="main"):
                yield Label("Project Overview", classes="section-title")
                yield ProjectSummaryView(id="project-summary")
                yield Label("Analysis Queue", classes="section-title")
                yield AnalysisQueueView(id="analysis-queue")
