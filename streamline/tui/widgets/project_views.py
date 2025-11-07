from __future__ import annotations

"""Project selection and creation views with associated message."""

from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Static, Input, ListView, ListItem
from textual import events
from textual.message import Message


class ProjectChosen(Message):
    """Message posted when a project is chosen from the selector or created."""
    
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__()


class ProjectSelectionView(Static):
    """Full-screen view for selecting an existing project."""

    def compose(self) -> ComposeResult:  # type: ignore
        yield Static(
            "Select a project (Enter). Press Esc to cancel. Use the command palette for new projects.",
            id="project_selector_hint"
        )
        yield ListView(id="project_selector_list")

    def on_mount(self) -> None:  # pragma: no cover - UI
        self.refresh_projects()

    def refresh_projects(self) -> None:
        """Scan projects directory and populate the list."""
        projects_root = Path("projects")
        entries: list[ListItem] = []
        if projects_root.exists():
            for path in sorted([p for p in projects_root.iterdir() if p.is_dir()]):
                entries.append(ListItem(Static(path.name)))
        list_view = self.query_one(ListView)
        list_view.clear()
        for item in entries:
            list_view.append(item)
        if entries:
            list_view.index = 0
            # Force focus and highlight of the first item
            self.call_after_refresh(lambda: list_view.focus())
        else:
            list_view.index = None

    def focus_list(self) -> None:
        """Focus the project list for keyboard navigation."""
        try:
            self.query_one(ListView).focus()
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle project selection from the list."""
        name = None
        try:
            static_child = event.item.query_one(Static)
            renderable = getattr(static_child, "renderable", None)
            if renderable is not None:
                name = getattr(renderable, "plain", None) or str(renderable)
            else:
                name = static_child.render() if hasattr(static_child, "render") else None
        except Exception:
            pass
        if not name:
            name = getattr(event.item, "id", None) or str(event.item)
        project_id = str(name).strip()
        if project_id:
            self.app.post_message(ProjectChosen(project_id))
        self.app._hide_project_selector()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        """Handle escape key to cancel selection."""
        if event.key == "escape":
            self.app._hide_project_selector()
            event.stop()


class NewProjectView(Static):
    """Full-screen view for creating a new project."""

    def compose(self) -> ComposeResult:  # type: ignore
        yield Static(
            "Create a new project id. Press Enter to confirm or Esc to cancel.",
            id="new_project_hint"
        )
        yield Input(placeholder="project_id", id="new_project_input")

    def on_mount(self) -> None:  # pragma: no cover - UI
        self.reset()
        self.focus_input()

    def reset(self) -> None:
        """Clear the input field."""
        try:
            self.query_one(Input).value = ""
        except Exception:
            pass

    def focus_input(self) -> None:
        """Focus the input field for typing."""
        try:
            self.query_one(Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle project creation when Enter is pressed."""
        project_id = event.value.strip()
        if project_id:
            self.app._hide_new_project()
            self.app.post_message(ProjectChosen(project_id))
        else:
            self.focus_input()

    def on_key(self, event: events.Key) -> None:
        """Handle escape key to cancel creation."""
        if event.key == "escape":
            self.app._hide_new_project()
            event.stop()
