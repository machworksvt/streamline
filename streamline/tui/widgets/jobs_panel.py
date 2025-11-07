from __future__ import annotations

"""Jobs panel widget with expandable job details and live timers."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static, ListView, ListItem

from ..context import SessionJob

# Type hints for session - avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..session import ProjectSession


# --- Helper functions for formatting ---

def _format_elapsed_time(start: datetime, end: Optional[datetime] = None) -> str:
    """Format elapsed time as human-readable string"""
    try:
        if end:
            delta = end - start
        else:
            delta = datetime.now(timezone.utc) - start
        
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "0s"
        elif seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}m {secs}s"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m"
    except Exception:
        return "-"


def _format_json_data(obj: Any, max_depth: int = 10) -> str:
    """Format any object as pretty JSON for display"""
    if obj is None:
        return "(not available)"
    
    try:
        if isinstance(obj, dict):
            return json.dumps(obj, indent=2, default=str)
        elif hasattr(obj, 'model_dump'):  # Pydantic v2
            return json.dumps(obj.model_dump(exclude_none=True), indent=2, default=str)
        elif hasattr(obj, 'dict'):  # Pydantic v1
            return json.dumps(obj.dict(exclude_none=True), indent=2, default=str)
        elif hasattr(obj, '__dict__'):
            return json.dumps(vars(obj), indent=2, default=str)
        else:
            return str(obj)
    except Exception as e:
        return f"(formatting error: {e})"


def _format_dict_readable(data: Dict[str, Any], indent: int = 0) -> str:
    """Format a dictionary in a more readable way than JSON"""
    if not data:
        return "(empty)"
    
    lines = []
    indent_str = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict) and value:
            lines.append(f"{indent_str}{key}:")
            lines.append(_format_dict_readable(value, indent + 1))
        elif isinstance(value, (list, tuple)) and value:
            lines.append(f"{indent_str}{key}: [{len(value)} items]")
        elif value is not None:
            # Truncate very long values
            str_val = str(value)
            if len(str_val) > 60:
                str_val = str_val[:57] + "..."
            lines.append(f"{indent_str}{key}: {str_val}")
    
    return "\n".join(lines) if lines else "(empty)"


def _format_object_readable(obj: Any) -> str:
    """Format any object in a readable way"""
    if obj is None:
        return "(not available)"
    
    try:
        if isinstance(obj, dict):
            return _format_dict_readable(obj)
        elif hasattr(obj, 'model_dump'):  # Pydantic v2
            return _format_dict_readable(obj.model_dump(exclude_none=True))
        elif hasattr(obj, 'dict'):  # Pydantic v1
            return _format_dict_readable(obj.dict(exclude_none=True))
        elif hasattr(obj, '__dict__'):
            return _format_dict_readable(vars(obj))
        else:
            return str(obj)
    except Exception as e:
        return f"(formatting error: {e})"


def _get_status_badge(status: str) -> str:
    """Get colored status badge for job"""
    status_lower = status.lower()
    badges = {
        "pending": "[cyan]●[/cyan]",
        "running": "[#39ff14]●[/#39ff14]",
        "completed": "[#24ff64]✓[/#24ff64]",
        "cached": "[#72ffab]✓[/#72ffab]",
        "failed": "[red]✗[/red]",
    }
    return badges.get(status_lower, "[white]●[/white]")


# --- Widgets ---

class JobListItem(ListItem):
    """Expandable job list item showing summary + detailed info when selected"""
    
    # Use reactive property so Textual knows to re-render when it changes
    is_expanded: reactive[bool] = reactive(False)
    
    def __init__(self, job: SessionJob):
        super().__init__()
        self.job = job
    
    def compose(self) -> ComposeResult:
        """Build the job item UI"""
        # Summary row (always visible) - use Static instead of Label for better rendering
        status_badge = _get_status_badge(self.job.status)
        timer_text = self._get_timer_text()
        summary_text = f"{status_badge} {self.job.status:12} {self.job.analysis_key:25} {timer_text:>10}"
        
        yield Static(summary_text, classes="job-summary")
        
        # Details section (conditionally visible based on is_expanded)
        if self.is_expanded:
            with Vertical(classes="job-details"):
                # Context section
                if self.job.context:
                    yield Static("[bold cyan]Context:[/bold cyan]", classes="detail-header")
                    yield Static(_format_object_readable(self.job.context), classes="detail-content")
                
                # Ticket section
                yield Static("[bold cyan]Ticket:[/bold cyan]", classes="detail-header")
                yield Static(_format_object_readable(self.job.ticket_payload), classes="detail-content")
                
                # Receipt section (if completed)
                if self.job.receipt is not None:
                    yield Static("[bold green]Receipt:[/bold green]", classes="detail-header")
                    yield Static(_format_object_readable(self.job.receipt), classes="detail-content")
                
                # Error section (if failed)
                if self.job.error:
                    yield Static("[bold red]Error:[/bold red]", classes="detail-header")
                    yield Static(str(self.job.error), classes="detail-error")
    
    def _get_timer_text(self) -> str:
        """Get timer text based on job status"""
        if self.job.status == "pending":
            return _format_elapsed_time(self.job.submitted_at)
        elif self.job.status == "running" and self.job.started_at:
            return _format_elapsed_time(self.job.started_at)
        elif self.job.started_at and self.job.ended_at:
            return _format_elapsed_time(self.job.started_at, self.job.ended_at)
        else:
            return "-"
    
    def on_click(self) -> None:
        """Toggle expansion when clicked"""
        self.is_expanded = not self.is_expanded
    
    def watch_is_expanded(self, new_value: bool) -> None:
        """Called automatically when is_expanded changes - triggers recompose"""
        self.refresh(layout=True, recompose=True)
    
    def update_timer(self) -> None:
        """Update the timer display (called periodically)"""
        if not self.is_expanded:
            try:
                summary = self.query_one(".job-summary", Static)
                status_badge = _get_status_badge(self.job.status)
                timer_text = self._get_timer_text()
                summary_text = f"{status_badge} {self.job.status:12} {self.job.analysis_key:25} {timer_text:>10}"
                summary.update(summary_text)
            except Exception:
                pass


class JobsPanel(Vertical):
    """Enhanced jobs panel with expandable job details"""
    
    session: Optional['ProjectSession'] = None
    
    def compose(self) -> ComposeResult:
        yield Static("Jobs", id="jobs_header", classes="panel-header")
        yield ListView(id="jobs_list")
    
    def on_mount(self) -> None:
        """Set up timer for live updates"""
        self.set_interval(1.0, self._update_timers)
    
    def redraw(self):
        if not self.session:
            try:
                self.query_one("#jobs_header", Static).update("Jobs (No project loaded)")
            except Exception:
                pass
            return
        
        jobs = list(self.session.state.jobs.values())
        
        # Update header
        try:
            header = self.query_one("#jobs_header", Static)
            if not jobs:
                header.update("Jobs (0 total)")
            else:
                running = sum(1 for j in jobs if j.status in ["running", "pending"])
                header.update(f"Jobs ({len(jobs)} total, {running} active)")
        except Exception:
            pass
        
        # Rebuild list
        try:
            jobs_list = self.query_one("#jobs_list", ListView)
            jobs_list.clear()
            
            if not jobs:
                return
            
            # Sort by submission time (newest first)
            sorted_jobs = sorted(
                jobs,
                key=lambda j: j.submitted_at.timestamp() if isinstance(j.submitted_at, datetime) else 0,
                reverse=True
            )
            
            for job in sorted_jobs:
                jobs_list.append(JobListItem(job))
        except Exception:
            pass
    
    def _update_timers(self) -> None:
        """Update timers for running/pending jobs"""
        try:
            for item in self.query(JobListItem):
                if item.job.status in ["running", "pending"]:
                    item.update_timer()
        except Exception:
            pass
