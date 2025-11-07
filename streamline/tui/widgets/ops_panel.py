from __future__ import annotations

"""Operating Points panel widget with keyboard navigation."""

from typing import Optional

from textual.app import ComposeResult
from textual.widgets import Static
from textual import events

# Type hints for session - avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..session import ProjectSession


class OpsPanel(Static):
    """Panel displaying operating points catalog with keyboard navigation."""
    
    session: Optional['ProjectSession'] = None
    selected_index: int = 0
    
    def redraw(self):
        """Redraw the operating points list."""
        if not self.session:
            self.update("No project loaded")
            return
        
        ops = self.session.state.op_catalog
        if not ops:
            self.update("(no operating points)")
            return
        
        if self.selected_index >= len(ops):
            self.selected_index = max(0, len(ops) - 1)
        
        rows = []
        for idx, o in enumerate(ops):
            marker = '>' if idx == self.selected_index else ' '
            rows.append(
                f"{marker} {o.op_id:15} "
                f"alt={o.altitude_m or '-'} "
                f"mach={o.mach or '-'} "
                f"tas={o.tas_mps or '-'}"
            )
        
        self.update("Operating Points:\n" + "\n".join(rows))
    
    def on_key(self, event: events.Key):
        """Handle keyboard navigation."""
        if event.key == 'up':
            self.selected_index = max(0, self.selected_index - 1)
            self.redraw()
            event.stop()
        elif event.key == 'down':
            if self.session and self.selected_index < len(self.session.state.op_catalog) - 1:
                self.selected_index += 1
                self.redraw()
                event.stop()
    
    def selected_op_id(self) -> Optional[str]:
        """Get the currently selected operating point ID."""
        if not self.session or not self.session.state.op_catalog:
            return None
        if self.selected_index < len(self.session.state.op_catalog):
            return self.session.state.op_catalog[self.selected_index].op_id
        return None
