from __future__ import annotations

"""Command palette providers for the Streamline TUI."""

from typing import Any, Callable

from textual.command import Provider, Hit, DiscoveryHit, Hits
from textual.screen import Screen
from textual.style import Style


class ProjectCommandProvider(Provider):
    """Command palette entries for project operations."""

    def __init__(self, screen: Screen[Any], match_style: Style | None = None) -> None:
        super().__init__(screen, match_style)

    @property
    def _entries(self) -> list[tuple[str, Callable[[], None], str]]:
        return [
            ("Open project...", self._open_project, "Select and load an existing project."),
            ("New project...", self._new_project, "Create a new project by id."),
        ]

    async def search(self, query: str) -> Hits:
        """Search for matching commands based on query."""
        matcher = self.matcher(query)
        for title, handler, help_text in self._entries:
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), handler, help=help_text)

    async def discover(self) -> Hits:
        """Discover all available commands."""
        for title, handler, help_text in self._entries:
            yield DiscoveryHit(title, handler, help=help_text)

    def _open_project(self) -> None:
        """Trigger the open project action."""
        self.app.action_open_project()

    def _new_project(self) -> None:
        """Trigger the new project action."""
        self.app.action_new_project()
