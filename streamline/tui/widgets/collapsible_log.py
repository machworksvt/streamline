from __future__ import annotations

"""Collapsible log widget with level filtering and event handling."""

import logging
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static, RichLog
from textual import events

# Import the LogMessageEvent for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..events import LogMessageEvent


class CollapsibleLog(Vertical):
    """Log viewer with collapsible header and minimum level filtering."""
    
    collapsed: bool = reactive(False)  # type: ignore
    min_level: int = reactive(logging.DEBUG)  # type: ignore

    def compose(self) -> ComposeResult:  # type: ignore
        self._header = Static("Log", id="log_header")
        self._header.can_focus = True
        self._rich = RichLog(
            id="log_body",
            markup=True,
            highlight=False,
            auto_scroll=True,
        )
        yield self._header
        yield self._rich

    def on_mount(self) -> None:  # pragma: no cover - UI
        self.set_class(False, "collapsed")
        self._apply_collapse_state()

    def toggle(self) -> None:
        """Toggle the collapsed state of the log."""
        self.collapsed = not self.collapsed
        self._apply_collapse_state()

    def _apply_collapse_state(self) -> None:
        """Apply the current collapse state to the UI."""
        self._rich.display = not self.collapsed
        self.set_class(self.collapsed, "collapsed")
        self._header.update("Log (hidden)" if self.collapsed else "Log")
        
    def on_click(self, event: events.Click) -> None:  # pragma: no cover - UI
        if event.control is self._header:
            self.toggle()
            event.stop()

    def set_min_level(self, level: int | str) -> None:
        """Set minimum log level to display."""
        if isinstance(level, str):
            self.min_level = logging.getLevelName(level.upper())
        else:
            self.min_level = int(level)

    def log(
        self, 
        message: str, 
        level: str | None = None, 
        context: dict | None = None,
        hint: str | None = None, 
        exc_info: str | None = None
    ) -> None:
        """Log a message with optional structured context."""
        level_name = (level or "INFO").upper()
        
        # Filter by minimum level
        try:
            level_value = logging.getLevelName(level_name)
            if isinstance(level_value, int) and level_value < self.min_level:
                return
        except Exception:
            pass
        
        # Color mapping
        color = {
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "WARN": "yellow",
            "ERROR": "red",
            "ERR": "red",
            "CRITICAL": "red",
        }.get(level_name, "white")
        
        styled_tag = f"[{color}][{level_name}][/{color}]"
        
        # Build the full message
        parts = [f"{styled_tag} {message}"]
        
        # Add context if present
        if context:
            context_str = " ".join(f"{k}={v!r}" for k, v in sorted(context.items()))
            parts.append(f"[dim]| {context_str}[/dim]")
        
        # Add hint if present
        if hint:
            parts.append(f"[dim italic]hint: {hint}[/dim italic]")
        
        # Add exception info if present
        if exc_info:
            parts.append(f"[red]{exc_info}[/red]")
        
        self._rich.write(" ".join(parts))

    def log_from_event(self, event: LogMessageEvent) -> None:
        """Process a LogMessageEvent directly."""
        self.log(
            message=event.message,
            level=event.level,
            context=event.context,
            hint=event.hint,
            exc_info=event.exc_info,
        )
