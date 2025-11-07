from __future__ import annotations

"""Project header widget displaying project status and active context."""

from typing import Optional, List

from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text


class ProjectHeader(Static):
    """Reactive header widget showing project name, active tab, and job summary."""
    
    project_name: str = reactive("No project loaded")  # type: ignore
    active_tab: str = reactive("Configs")  # type: ignore
    job_summary: str = reactive("")  # type: ignore

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)

    def update_context(
        self,
        *,
        project_id: Optional[str],
        active_tab: Optional[str] = None,
        running_jobs: Optional[int] = None,
        total_jobs: Optional[int] = None,
    ) -> None:
        """Update the header context with new project/job information."""
        name = project_id or "No project loaded"
        if name != self.project_name:
            self.project_name = name
        if active_tab:
            self.active_tab = active_tab
        if total_jobs is not None:
            running = running_jobs or 0
            summary = f"Jobs: {running} active / {total_jobs} total"
            if summary != self.job_summary:
                self.job_summary = summary
        elif not project_id:
            if self.job_summary:
                self.job_summary = ""
        self.refresh()

    def watch_project_name(self, _: str) -> None:  # pragma: no cover - UI updates
        self.refresh()

    def watch_active_tab(self, _: str) -> None:  # pragma: no cover - UI updates
        self.refresh()

    def watch_job_summary(self, _: str) -> None:  # pragma: no cover - UI updates
        self.refresh()

    def render(self) -> Text:
        """Render the header text with styling."""
        style = "bold #9bffc7"
        parts: List[str] = ["Streamline"]
        if self.project_name:
            parts.append(f"Project: {self.project_name}")
        if self.job_summary:
            parts.append(self.job_summary)
        return Text(" | ".join(parts), style=style)
