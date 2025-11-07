from __future__ import annotations

"""Configurations panel widget with keyboard navigation and stale tracking."""

from typing import Optional

from textual.app import ComposeResult
from textual.widgets import Static
from textual import events

# Type hints for session - avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..session import ProjectSession


class ConfigsPanel(Static):
    """Panel displaying configurations catalog with keyboard navigation and stale tracking."""
    
    session: Optional['ProjectSession'] = None
    selected_index: int = 0
    stale_ids: set[str] = set()
    
    def redraw(self):
        """Redraw the configurations list."""
        if not self.session:
            self.update("No project loaded")
            return
        
        cfgs = self.session.state.config_catalog
        if not cfgs:
            self.update("(no configurations)")
            return
        
        if self.selected_index >= len(cfgs):
            self.selected_index = max(0, len(cfgs) - 1)
        
        rows = []
        for idx, c in enumerate(cfgs):
            marker = '>' if idx == self.selected_index else ' '
            stale = c.config_id in self.stale_ids
            set_name = getattr(c, 'set_name', '-') or '-'
            mode_id = getattr(c, 'mode_id', None) or '-'
            line = f"{marker} {c.config_id:15} set={set_name} mode={mode_id}"
            if stale:
                line = f"[yellow]{line} [STALE][/yellow]"
            rows.append(line)
        
        self.update("Configurations:\n" + "\n".join(rows))
    
    def on_key(self, event: events.Key):
        """Handle keyboard navigation."""
        if event.key == 'up':
            self.selected_index = max(0, self.selected_index - 1)
            self.redraw()
            event.stop()
        elif event.key == 'down':
            if self.session and self.selected_index < len(self.session.state.config_catalog) - 1:
                self.selected_index += 1
                self.redraw()
                event.stop()
    
    def selected_config_id(self) -> Optional[str]:
        """Get the currently selected configuration ID."""
        if not self.session or not self.session.state.config_catalog:
            return None
        if self.selected_index < len(self.session.state.config_catalog):
            return self.session.state.config_catalog[self.selected_index].config_id
        return None
