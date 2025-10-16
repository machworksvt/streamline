from __future__ import annotations

"""Textual TUI scaffold (initial).

Goals (MVP):
- Start with an empty screen prompting user to open a project (press 'o').
- After project load + validation, spin up ProjectSession (AnalysisManager + VSP lock) and open the OpenVSP GUI.
- Provide tabbed panes: Configurations, Operating Points, Jobs.
- Provide a bottom log pane continuously streaming log/event messages.
- Basic key bindings: 'q' = quit; project actions live in the command palette (Ctrl+P).

Formatting intentionally minimal; will iterate later.
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Iterable
from time import time as _time

from textual.app import App, ComposeResult, SystemCommand
from textual.widgets import Static, Footer, Input, ListView, ListItem, Tabs, Tab, ContentSwitcher, RichLog
from textual.reactive import reactive
from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.timer import Timer
from textual.command import Provider, Hit, DiscoveryHit, Hits
from textual.screen import Screen
from textual.style import Style

from .tui import ProjectSession, create_project_session
from .tui.event_bus import get_global_event_bus, set_global_event_bus
from .tui.events import (
    CatalogChangedEvent,
    ConfigurationCreatedEvent,
    ConfigurationRemovedEvent,
    ConfigurationStaleEvent,
    ConfigurationUpdatedEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobStartedEvent,
    JobSubmittedEvent,
    ReceiptAddedEvent,
    WorkerFailed,
    LogMessageEvent,
)
from .vsp import session as vsp_session
from .main import create_new_project  # reuse project scaffolder
from .io.fs import load_project_def, load_config
from .io.config_catalog import load_config_catalog
from .io.op_catalog import load_op_catalog
from .vsp.configure import revalidate_existing_configs_with_lock

# --- Log bridge ---

class EventBusLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        bus = get_global_event_bus()
        if not bus:
            return
        try:
            bus.publish(LogMessageEvent(level=record.levelname,
                                        name=record.name,
                                        message=record.getMessage()))
        except Exception:
            pass
# --- Widgets ---

class Placeholder(Static):
    pass

class CollapsibleLog(Vertical):
    collapsed: bool = reactive(False)  # type: ignore

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
        self.collapsed = not self.collapsed
        self._apply_collapse_state()

    def _apply_collapse_state(self) -> None:
        self._rich.display = not self.collapsed
        self.set_class(self.collapsed, "collapsed")
        self._header.update("Log (hidden)" if self.collapsed else "Log")
    def on_click(self, event: events.Click) -> None:  # pragma: no cover - UI
        if event.control is self._header:
            self.toggle()
            event.stop()


    def log(self, message: str, level: str | None = None) -> None:
        tag = (level or "INFO").upper()
        color = {
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "WARN": "yellow",
            "ERROR": "red",
            "ERR": "red",
            "CRITICAL": "red",
        }.get(tag, "white")
        styled_tag = f"[{color}][{tag}][/]"
        self._rich.write(f"{styled_tag} {message}")


class ProjectHeader(Static):
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
        style = "bold #9bffc7"
        parts: List[str] = ["Streamline"]
        if self.project_name:
            parts.append(f"Project: {self.project_name}")
        if self.job_summary:
            parts.append(self.job_summary)
        return Text(" | ".join(parts), style=style)

class ConfigsPanel(Static):
    session: Optional[ProjectSession] = None
    selected_index: int = 0
    stale_ids: set[str] = set()
    def redraw(self):
        if not self.session:
            self.update("No project loaded")
            return
        cfgs = self.session.state.config_catalog
        if not cfgs:
            self.update("(no configurations)")
            return
        if self.selected_index >= len(cfgs):
            self.selected_index = max(0, len(cfgs)-1)
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
        if event.key == 'up':
            self.selected_index = max(0, self.selected_index - 1)
            self.redraw(); event.stop()
        elif event.key == 'down':
            if self.session and self.selected_index < len(self.session.state.config_catalog)-1:
                self.selected_index += 1
                self.redraw(); event.stop()
    def selected_config_id(self) -> Optional[str]:
        if not self.session or not self.session.state.config_catalog:
            return None
        if self.selected_index < len(self.session.state.config_catalog):
            return self.session.state.config_catalog[self.selected_index].config_id
        return None

class OpsPanel(Static):
    session: Optional[ProjectSession] = None
    selected_index: int = 0
    def redraw(self):
        if not self.session:
            self.update("No project loaded")
            return
        ops = self.session.state.op_catalog
        if not ops:
            self.update("(no operating points)")
            return
        if self.selected_index >= len(ops):
            self.selected_index = max(0, len(ops)-1)
        rows = []
        for idx, o in enumerate(ops):
            marker = '>' if idx == self.selected_index else ' '
            rows.append(f"{marker} {o.op_id:15} alt={o.altitude_m or '-'} mach={o.mach or '-'} tas={o.tas_mps or '-'}")
        self.update("Operating Points:\n" + "\n".join(rows))
    def on_key(self, event: events.Key):
        if event.key == 'up':
            self.selected_index = max(0, self.selected_index - 1)
            self.redraw(); event.stop()
        elif event.key == 'down':
            if self.session and self.selected_index < len(self.session.state.op_catalog)-1:
                self.selected_index += 1
                self.redraw(); event.stop()
    def selected_op_id(self) -> Optional[str]:
        if not self.session or not self.session.state.op_catalog:
            return None
        if self.selected_index < len(self.session.state.op_catalog):
            return self.session.state.op_catalog[self.selected_index].op_id
        return None

class JobsPanel(Static):
    session: Optional[ProjectSession] = None
    def redraw(self):
        if not self.session:
            self.update("No project loaded")
            return
        jobs = self.session.state.jobs.values()
        if not jobs:
            self.update("(no jobs submitted)")
            return
        lines = []
        for j in sorted(jobs, key=lambda x: x.submitted_at):
            base = f"{j.job_id[:8]} {j.analysis_key:20} {j.status:10} sha={j.ticket_sha or '-'}"
            if j.status == 'failed':
                base = f"[red]{base}[/red]"
            elif j.status == 'running':
                base = f"[cyan]{base}[/cyan]"
            elif j.status == 'completed':
                base = f"[green]{base}[/green]"
            lines.append(base)
        self.update("Jobs:\n" + "\n".join(lines))

# --- Input modal for project id ---

class ProjectSelectionView(Static):
    """Full-screen view for selecting an existing project."""

    def compose(self) -> ComposeResult:  # type: ignore
        yield Static("Select a project (Enter). Press Esc to cancel. Use the command palette for new projects.", id="project_selector_hint")
        yield ListView(id="project_selector_list")

    def on_mount(self) -> None:  # pragma: no cover - UI
        self.refresh_projects()

    def refresh_projects(self) -> None:
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
        else:
            list_view.index = None

    def focus_list(self) -> None:
        try:
            self.query_one(ListView).focus()
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
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
        if event.key == "escape":
            self.app._hide_project_selector()
            event.stop()


class NewProjectView(Static):
    """Full-screen view for creating a new project."""

    def compose(self) -> ComposeResult:  # type: ignore
        yield Static("Create a new project id. Press Enter to confirm or Esc to cancel.", id="new_project_hint")
        yield Input(placeholder="project_id", id="new_project_input")

    def on_mount(self) -> None:  # pragma: no cover - UI
        self.reset()
        self.focus_input()

    def reset(self) -> None:
        try:
            self.query_one(Input).value = ""
        except Exception:
            pass

    def focus_input(self) -> None:
        try:
            self.query_one(Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        project_id = event.value.strip()
        if project_id:
            self.app._hide_new_project()
            self.app.post_message(ProjectChosen(project_id))
        else:
            self.focus_input()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.app._hide_new_project()
            event.stop()

# --- Custom messages ---

from textual.message import Message  # after textual import

class ProjectChosen(Message):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__()


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
        matcher = self.matcher(query)
        for title, handler, help_text in self._entries:
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), handler, help=help_text)

    async def discover(self) -> Hits:
        for title, handler, help_text in self._entries:
            yield DiscoveryHit(title, handler, help=help_text)

    def _open_project(self) -> None:
        self.app.action_open_project()

    def _new_project(self) -> None:
        self.app.action_new_project()

# --- Main App ---

class StreamlineApp(App):
    COMMANDS = App.COMMANDS | {ProjectCommandProvider}
    CSS_PATH = str(Path(__file__).parent / "tui" / "styles" / "app.tcss")
    BINDINGS = [
        ("q", "quit_app", "Quit"),
        ("t", "run_test", "Run Test"),
        ("u", "update_config", "Update"),
    ]

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        suppress = {
            "Maximize",
            "Change theme",
            "Show keys and help panel",
            "Hide keys and help panel",
        }
        for command in super().get_system_commands(screen):
            if command.title in suppress:
                continue
            yield command

    session: Optional[ProjectSession] = None
    configs_panel: ConfigsPanel
    ops_panel: OpsPanel
    jobs_panel: JobsPanel
    log_panel: CollapsibleLog
    project_header: ProjectHeader
    last_test_duration: float | None = None
    tabs: Tabs
    switcher: ContentSwitcher
    primary_switcher: ContentSwitcher
    project_selector: ProjectSelectionView
    new_project_view: NewProjectView
    footer_bar: Footer

    def compose(self) -> ComposeResult:  # type: ignore
        main_view = Vertical(
            Tabs(
                Tab("Configs", id="tab-configs"),
                Tab("Ops", id="tab-ops"),
                Tab("Jobs", id="tab-jobs"),
                id="main_tabs",
            ),
            ContentSwitcher(
                ConfigsPanel(id="configs_panel"),
                OpsPanel(id="ops_panel"),
                JobsPanel(id="jobs_panel"),
                id="main_switcher",
                initial="configs_panel",
            ),
            id="layout_main",
        )
        selector_view = ProjectSelectionView(id="project_selector")
        yield ProjectHeader(id="project_header")
        yield ContentSwitcher(
            main_view,
            selector_view,
            NewProjectView(id="new_project_view"),
            id="primary_switcher",
            initial="layout_main",
        )
        yield CollapsibleLog(id="log_panel")  # docked bottom via CSS height constraint
        yield Footer()

    # --- Lifecycle ---
    def on_mount(self) -> None:  # pragma: no cover - UI
        # Elevate logging verbosity globally
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        for h in list(root_logger.handlers):
            try:
                h.setLevel(logging.DEBUG)
            except Exception:
                pass
        # Attach / replace EventBusLogHandler for full level capture
        if not any(isinstance(h, EventBusLogHandler) for h in root_logger.handlers):
            handler = EventBusLogHandler()
            handler.setLevel(logging.DEBUG)
            root_logger.addHandler(handler)
        else:
            for h in root_logger.handlers:
                if isinstance(h, EventBusLogHandler):
                    h.setLevel(logging.DEBUG)
        # Provide feedback
        logging.getLogger(__name__).debug("TUI logging configured for DEBUG level capture")
        # ...existing code (initial panel/query setup follows)...
        self.log_panel = self.query_one("#log_panel", CollapsibleLog)
        self.configs_panel = self.query_one("#configs_panel", ConfigsPanel)
        self.ops_panel = self.query_one("#ops_panel", OpsPanel)
        self.jobs_panel = self.query_one("#jobs_panel", JobsPanel)
        self.tabs = self.query_one("#main_tabs", Tabs)
        self.switcher = self.query_one("#main_switcher", ContentSwitcher)
        self.primary_switcher = self.query_one("#primary_switcher", ContentSwitcher)
        self.project_selector = self.query_one("#project_selector", ProjectSelectionView)
        self.new_project_view = self.query_one("#new_project_view", NewProjectView)
        self.project_header = self.query_one("#project_header", ProjectHeader)
        self.footer_bar = self.query_one(Footer)
        self.footer_bar.bindings_changed(self.screen)
        self.log_panel.log("Use Ctrl+P to open a project via the command palette.")
        self.project_header.update_context(project_id=None, active_tab="Configs")
        # Attach logging handler
        root_logger = logging.getLogger()
        if not any(isinstance(h, EventBusLogHandler) for h in root_logger.handlers):
            handler = EventBusLogHandler()
            handler.setLevel(logging.INFO)
            root_logger.addHandler(handler)
        # Setup event bus listener
        bus = get_global_event_bus()
        if bus is None:
            from .tui.event_bus import EventBus
            bus = EventBus()
            set_global_event_bus(bus)
        self._bus_subscription = bus.subscribe_any(self._handle_event)  # store for cleanup
        # Debounce state
        self._refresh_flags = {"configs": False, "ops": False, "jobs": False}
        self._refresh_timer: Timer | None = None
        # Rate limit state
        self._log_epoch = int(_time())
        self._log_count = 0
        self._log_suppressed = 0
        self.tabs.active = "tab-configs"
        self.switcher.current = "configs_panel"

    # --- Actions ---
    def action_quit_app(self) -> None:
        self.exit()
    def action_open_project(self) -> None:
        self._show_project_selector()
    def action_new_project(self) -> None:
        self._show_new_project()
    def action_refresh(self) -> None:
        if self.session:
            self.session.refresh_catalogs()
            self._refresh_all()
    def action_focus_tab_configs(self):
        self.tabs.active = "tab-configs"; self._sync_tab_switch()
    def action_focus_tab_ops(self):
        self.tabs.active = "tab-ops"; self._sync_tab_switch()
    def action_focus_tab_jobs(self):
        self.tabs.active = "tab-jobs"; self._sync_tab_switch()
    def action_run_test(self):
        if not self.session:
            self._schedule_log_append("No session for test analysis", level='WARN'); return
        from .analysis.test_analyses import NoopTicket
        try:
            ticket = NoopTicket(label='quick', duration_s=0.5)
            self.session.submit('test_noop', ticket)
            self._schedule_log_append("Submitted test_noop", level='INFO')
        except Exception as exc:
            self._schedule_log_append(f"Test submit failed: {exc}", level='ERR')
    def action_diff_config(self):
        cfg_id = self.configs_panel.selected_config_id()
        if not cfg_id:
            self._schedule_log_append("No configuration selected for diff", level='WARN'); return
        self._schedule_log_append(f"(diff placeholder) Config {cfg_id}", level='INFO')
    def action_update_config(self):
        cfg_id = self.configs_panel.selected_config_id()
        if not cfg_id:
            self._schedule_log_append("No configuration selected for update", level='WARN'); return
        self._schedule_log_append(f"(update placeholder) Config {cfg_id}", level='INFO')

    def _show_project_selector(self) -> None:
        if not hasattr(self, "primary_switcher"):
            return
        if self.primary_switcher.current == "project_selector":
            self.project_selector.refresh_projects()
            self.project_selector.focus_list()
            return
        self.project_selector.refresh_projects()
        self.primary_switcher.current = "project_selector"
        self.project_selector.focus_list()

    def _hide_project_selector(self) -> None:
        if not hasattr(self, "primary_switcher"):
            return
        self.primary_switcher.current = "layout_main"
        try:
            self.tabs.focus()
        except Exception:
            pass

    def _show_new_project(self) -> None:
        if not hasattr(self, "primary_switcher"):
            return
        self.new_project_view.reset()
        self.primary_switcher.current = "new_project_view"
        self.new_project_view.focus_input()

    def _hide_new_project(self) -> None:
        if not hasattr(self, "primary_switcher"):
            return
        self.primary_switcher.current = "layout_main"
        try:
            self.tabs.focus()
        except Exception:
            pass

    # --- Project loading ---
    def _load_project(self, project_id: str) -> None:
        projects_root = Path('projects')
        target = projects_root / project_id
        if not target.exists():
            self.log_panel.log(f"Project '{project_id}' not found. Creating new project...")
            try:
                create_new_project(projects_root, project_id)
                self._show_notification(f"Created project '{project_id}'", level="success", duration=4.0)
            except Exception as exc:
                self.log_panel.log(f"Failed to create project: {exc}")
                return
        self.log_panel.log(f"Loading project '{project_id}' ...")
        self.session = create_project_session(project_id, projects_root=projects_root, open_gui=True)
        # Validate catalogs immediately
        try:
            cfg_models = []
            for c in self.session.state.config_catalog:
                try:
                    cfg_models.append(load_config(c.path))
                except Exception as ce:
                    self.log_panel.log(f"Failed to load config {c.config_id}: {ce}", level='WARN')
            stale_map = revalidate_existing_configs_with_lock(cfg_models, analysis_manager=self.session.manager)
            for cfg_id, errs in stale_map.items():
                if errs:
                    for e in errs:
                        self.log_panel.log(f"CONFIG INVALID {cfg_id}: {e}")
        except Exception as exc:
            self.log_panel.log(f"Validation exception: {exc}")
        # open GUI and assert user should only edit inside Streamline session
        vsp = vsp_session.get_vsp()
        if vsp is not None:
            try:
                if not vsp_session.ensure_gui_started(vsp):
                    self.log_panel.log("OpenVSP GUI not started (headless binding?)", level="WARN")
            except Exception as exc:
                self.log_panel.log(f"OpenVSP GUI start warning: {exc}", level="WARN")
            try:
                proj_file = self.session.project_root / f"{project_id}.vsp3"
                if proj_file.exists():
                    vsp.ReadVSPFile(str(proj_file))
                else:
                    vsp.WriteVSPFile(str(proj_file))
            except Exception as exc:
                self.log_panel.log(f"OpenVSP load warning: {exc}")
        self.log_panel.log("Geometry edits must be performed while this TUI session is active; do not modify the .vsp3 externally.")
        self.configs_panel.session = self.session
        self.ops_panel.session = self.session
        self.jobs_panel.session = self.session
        self._refresh_all()
        self.log_panel.log(f"Project '{project_id}' loaded.")
        self._show_notification(f"Project '{project_id}' ready", level="success", duration=4.0)

    # --- Refresh helpers ---
    def _refresh_all(self):
        self.configs_panel.redraw()
        self.ops_panel.redraw()
        self.jobs_panel.redraw()
        self._update_header()

    # --- Event handling ---
    def _handle_event(self, evt):  # evt is generic from bus
        # Handle typed events first
        if isinstance(
            evt,
            (
                JobSubmittedEvent, 
                JobStartedEvent,
                JobCompletedEvent,
                JobFailedEvent,
                ReceiptAddedEvent,
            ),
        ):
            self._mark_refresh('jobs')
            if isinstance(evt, JobSubmittedEvent):
                self._show_notification(
                    f"Queued {evt.analysis_key} ({evt.job_id[:8]})",
                    level="info",
                    duration=3.0,
                )
            if isinstance(evt, JobStartedEvent):
                self._show_notification(
                    f"Started {evt.analysis_key} ({evt.job_id[:8]})",
                    level="info",
                    duration=3.0,
                )
            if isinstance(evt, JobFailedEvent):
                self._schedule_log_append(f"JOB FAILED {evt.job_id}: {evt.error}", level='ERR')
                self._show_notification(
                    f"Job {evt.analysis_key} failed",
                    level="error",
                    duration=6.0,
                )
            if isinstance(evt, JobCompletedEvent):
                self._show_notification(
                    f"Completed {evt.analysis_key}",
                    level="success",
                    duration=4.0,
                )
            if isinstance(evt, ReceiptAddedEvent) and evt.analysis_key == 'test_noop':
                receipt = evt.receipt_summary or {}
                dur = receipt.get('duration_s') or receipt.get('duration') or None
                if isinstance(dur, (int, float)):
                    self.last_test_duration = float(dur)
            return

        if isinstance(evt, WorkerFailed):
            detail = f": {evt.details}" if evt.details else ""
            self._schedule_log_append(f"Worker failure{detail}", level="ERR")
            self._show_notification("Analysis worker encountered an error", level="error", duration=6.0)
            return

        if isinstance(
            evt,
            (
                CatalogChangedEvent,
                ConfigurationCreatedEvent,
                ConfigurationUpdatedEvent,
                ConfigurationRemovedEvent,
            ),
        ):
            self._mark_refresh('configs')
            return

        if isinstance(evt, ConfigurationStaleEvent):
            if evt.config_id:
                self.configs_panel.stale_ids.add(evt.config_id)
            self._mark_refresh('configs')
            return

        if isinstance(evt, LogMessageEvent):
            self._schedule_log_append(evt.message, level=evt.level)
        # Future: op catalog change events -> self._mark_refresh('ops')

    def _show_notification(self, message: str, *, level: str = "info", duration: float = 4.0) -> None:
        severity_map = {
            "info": "information", # the only options for textual are information, warning, and error
            "debug": "information",
            "success": "information",
            "warning": "warning",
            "error": "error",
        }
        severity = severity_map.get(level.lower(), "information")
        try:
            self.notify(message, severity=severity, timeout=duration)
        except Exception:
            pass

    def _schedule_log_append(self, text: str, level: str | None = None):
        now_epoch = int(_time())
        if now_epoch != self._log_epoch:
            # new second: flush suppression summary if any
            if self._log_suppressed:
                summary = f"(suppressed {self._log_suppressed} log lines)"
                try:
                    self.call_from_thread(lambda: self.log_panel.log(summary))
                except Exception:
                    pass
            self._log_epoch = now_epoch
            self._log_count = 0
            self._log_suppressed = 0
        if self._log_count > 120:  # raise per-second threshold for verbose DEBUG output
            self._log_suppressed += 1
            return
        self._log_count += 1
        def _apply():
            self.log_panel.log(text, level=level)
        try:
            self.call_from_thread(_apply)
        except Exception:
            pass

    def _mark_refresh(self, key: str):
        self._refresh_flags[key] = True
        if not self._refresh_timer:
            self._refresh_timer = self.set_timer(0.1, self._apply_refresh_flags)  # removed repeat kw
    def _apply_refresh_flags(self):
        if self._refresh_flags.get('configs'): self.configs_panel.redraw()
        if self._refresh_flags.get('ops'): self.ops_panel.redraw()
        if self._refresh_flags.get('jobs'): self.jobs_panel.redraw()
        self._update_header()
        for k in self._refresh_flags: self._refresh_flags[k] = False
        self._refresh_timer = None

    def _update_header(self) -> None:
        header = getattr(self, "project_header", None)
        if header is None:
            return
        project_id = None
        total_jobs = None
        running_jobs = 0
        if self.session:
            project_id = self.session.state.project_id
            jobs = list(self.session.state.jobs.values())
            total_jobs = len(jobs)
            running_jobs = sum(
                1
                for job in jobs
                if job.status not in {"completed", "cached", "failed"}
            )
        active_label = "Configs"
        tabs = getattr(self, "tabs", None)
        if tabs is not None:
            try:
                active_label = tabs.active.replace("tab-", "").title()
            except Exception:
                pass
        header.update_context(
            project_id=project_id,
            active_tab=active_label,
            running_jobs=running_jobs if total_jobs is not None else None,
            total_jobs=total_jobs,
        )

    # --- Message handlers ---
    def on_project_chosen(self, msg: ProjectChosen) -> None:  # pragma: no cover - UI event
        self._load_project(msg.project_id.strip())

    def on_exit(self) -> None:  # graceful shutdown
        try:
            if self.session:
                self.session.stop()
        except Exception:
            pass
        try:
            if getattr(self, '_bus_subscription', None):
                self._bus_subscription.cancel()
        except Exception:
            pass

    # --- Tab switching helpers ---
    def _sync_tab_switch(self):
        active = self.tabs.active
        mapping = {
            'tab-configs': 'configs_panel',
            'tab-ops': 'ops_panel',
            'tab-jobs': 'jobs_panel',
        }
        target = mapping.get(active, 'configs_panel')
        self.switcher.current = target
        self._mark_refresh('configs'); self._mark_refresh('ops'); self._mark_refresh('jobs')
        self._update_header()
    def on_tabs_tab_activated(self, event):  # pragma: no cover
        self._sync_tab_switch()

    # --- Button press handler ---
    def on_button_pressed(self, event):  # pragma: no cover
        pass # no buttons

# Entrypoint helper

def run_app():  # pragma: no cover - manual execution path
    app = StreamlineApp()
    app.run()

if __name__ == "__main__":  # pragma: no cover
    run_app()








