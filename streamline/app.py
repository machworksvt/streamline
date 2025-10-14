from __future__ import annotations

"""Textual TUI scaffold (initial).

Goals (MVP):
- Start with an empty screen prompting user to open a project (press 'o').
- After project load + validation, spin up ProjectSession (AnalysisManager + VSP lock) and open the OpenVSP GUI.
- Provide tabbed panes: Configurations, Operating Points, Jobs.
- Provide a bottom log pane continuously streaming log/event messages.
- Basic key bindings: 'o' = open project id prompt, 'r' = refresh catalogs, 'q' = quit.

Formatting intentionally minimal; will iterate later.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from time import time as _time

from textual.app import App, ComposeResult
from textual.widgets import Static, Header, Footer, Input, ListView, ListItem, Button, Tabs, Tab, ContentSwitcher
from textual.reactive import reactive
from textual import events
from textual.containers import Horizontal, Vertical
from textual.timer import Timer

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
    LOG_MESSAGE,
)
from .vsp import session as vsp_session
from .main import create_new_project  # reuse project scaffolder
from .io.fs import load_project_def, load_config
from .io.config_catalog import load_config_catalog
from .io.op_catalog import load_op_catalog
from .vsp.configure import revalidate_existing_configs_with_lock

# --- Log bridge ---

class EventBusLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - UI side effect
        bus = get_global_event_bus()
        if not bus:
            return
        try:
            bus.emit(LOG_MESSAGE, {
                'level': record.levelname,
                'name': record.name,
                'message': record.getMessage(),
            })
        except Exception:
            pass

# --- Widgets ---

class Placeholder(Static):
    pass

class LogPanel(Static):
    lines: List[str] = reactive([])  # type: ignore
    max_lines: int = 500
    def append(self, text: str, level: str | None = None) -> None:
        if level:
            lvl = level.upper()
            color = {
                'DEBUG': 'dim',
                'INFO': 'green',
                'WARNING': 'yellow', 'WARN': 'yellow',
                'ERROR': 'red', 'ERR': 'red',
                'CRITICAL': 'red bold'
            }.get(lvl, 'white')
            text = f"[{color}][{lvl}][/]: {text}"
        self.lines.append(text)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self.update("\n".join(self.lines[-60:]))  # show last ~60 lines now to help debug

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

class StatusBar(Static):
    def update_status(self, *, active_cfg: str | None, active_op: str | None, jobs: Dict[str, Any], active_tab: str, last_test_duration: float | None):
        pending = sum(1 for j in jobs.values() if j.status == 'pending')
        running = sum(1 for j in jobs.values() if j.status == 'running')
        completed = sum(1 for j in jobs.values() if j.status == 'completed')
        failed = sum(1 for j in jobs.values() if j.status == 'failed')
        dur = f" test:{last_test_duration:.2f}s" if last_test_duration is not None else ''
        self.update(f"TAB={active_tab} CFG={active_cfg or '-'} OP={active_op or '-'} Jobs P:{pending} R:{running} C:{completed} F:{failed}{dur}")

# --- Input modal for project id ---

class ProjectOpenPrompt(Static):
    def compose(self) -> ComposeResult:  # type: ignore
        yield Static("Enter project id and press Enter (Esc to cancel):")
        yield Input(placeholder="project_id", id="project_id_input")
    def on_mount(self) -> None:  # pragma: no cover - UI
        self.query_one(Input).focus()
    def on_input_submitted(self, event: Input.Submitted) -> None:  # pragma: no cover - UI
        self.app.post_message(ProjectChosen(event.value))
        self.remove()
    def on_key(self, event: events.Key) -> None:  # pragma: no cover - UI
        if event.key == "escape":
            self.remove()

class ProjectListPrompt(Static):
    def compose(self) -> ComposeResult:  # type: ignore
        yield Static("Select project (Enter), or type new id, Esc to cancel:")
        projects_root = Path('projects')
        items = []
        if projects_root.exists():
            for d in sorted([p for p in projects_root.iterdir() if p.is_dir()]):
                items.append(ListItem(Static(d.name)))
        # Provide items at construction to avoid mount-time append errors
        yield ListView(*items, id="proj_list")
        yield Input(placeholder="new_project_id", id="new_proj_id")
    def on_mount(self):
        try:
            lst = self.query_one(ListView)
            if len(lst.children) > 0:
                lst.index = 0
                lst.focus()
            else:
                self.query_one(Input).focus()
        except Exception:
            pass
    def on_list_view_selected(self, event: ListView.Selected):  # pick existing
        name = None
        try:
            # Attempt to find a Static child and extract its rendered text
            static_child = event.item.query_one(Static)
            rend = getattr(static_child, 'renderable', None)
            if rend is not None:
                name = getattr(rend, 'plain', None) or str(rend)
            else:
                name = static_child.render() if hasattr(static_child, 'render') else None
        except Exception:
            pass
        if not name:
            # Fallback: string representation
            name = getattr(event.item, 'id', None) or str(event.item)
        name = str(name).strip()
        if name:
            self.app.post_message(ProjectChosen(name))
        self.remove()
    def on_input_submitted(self, event: Input.Submitted):  # new project
        val = event.value.strip()
        if val:
            self.app.post_message(ProjectChosen(val))
        self.remove()
    def on_key(self, event: events.Key):
        if event.key == 'escape':
            self.remove()

# --- Custom messages ---

from textual.message import Message  # after textual import

class ProjectChosen(Message):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__()

# --- Main App ---

class StreamlineApp(App):
    CSS = """
    Screen { layout: vertical; }
    #layout_main { layout: vertical; height: 1fr; }
    #panels_region { height: 1fr; }
    #log_panel { height: 25%; min-height: 6; border: solid gray; }
    #status_bar { height: 1; }
    #action_bar { height: 3; }
    """
    BINDINGS = [
        ("q", "quit_app", "Quit"),
        ("o", "open_project", "Open Project"),
        ("n", "new_project", "New Project"),
        ("r", "refresh", "Refresh Catalogs"),
        ("1", "focus_tab_configs", "Configs"),
        ("2", "focus_tab_ops", "Ops"),
        ("3", "focus_tab_jobs", "Jobs"),
        ("t", "run_test", "Run Test"),
        ("d", "diff_config", "Diff"),
        ("u", "update_config", "Update"),
    ]

    session: Optional[ProjectSession] = None
    configs_panel: ConfigsPanel
    ops_panel: OpsPanel
    jobs_panel: JobsPanel
    log_panel: LogPanel
    last_test_duration: float | None = None
    tabs: Tabs
    switcher: ContentSwitcher

    def compose(self) -> ComposeResult:  # type: ignore
        yield Header()
        # Layout main region
        yield Vertical(
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
            Horizontal(
                Button("Run Test", id="btn_run_test"),
                Button("Refresh", id="btn_refresh"),
                Button("Diff", id="btn_diff"),
                Button("Update", id="btn_update"),
                id="action_bar",
            ),
            id="layout_main",
        )
        self.status_bar = StatusBar(id="status_bar")
        yield self.status_bar
        yield LogPanel(id="log_panel")  # docked bottom via CSS height constraint
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
        self.log_panel = self.query_one("#log_panel", LogPanel)
        self.configs_panel = self.query_one("#configs_panel", ConfigsPanel)
        self.ops_panel = self.query_one("#ops_panel", OpsPanel)
        self.jobs_panel = self.query_one("#jobs_panel", JobsPanel)
        self.tabs = self.query_one("#main_tabs", Tabs)
        self.switcher = self.query_one("#main_switcher", ContentSwitcher)
        self.log_panel.update("Press 'o' to open a project.")
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
        if self.query(ProjectListPrompt):
            return
        self.mount(ProjectListPrompt(id="proj_list_prompt"))
    def action_new_project(self) -> None:
        if self.query(ProjectOpenPrompt):
            return
        self.mount(ProjectOpenPrompt(id="proj_prompt_new"))
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

    # --- Project loading ---
    def _load_project(self, project_id: str) -> None:
        projects_root = Path('projects')
        target = projects_root / project_id
        if not target.exists():
            self.log_panel.append(f"Project '{project_id}' not found. Creating new project...")
            try:
                create_new_project(projects_root, project_id)
            except Exception as exc:
                self.log_panel.append(f"Failed to create project: {exc}")
                return
        self.log_panel.append(f"Loading project '{project_id}' ...")
        self.session = create_project_session(project_id, projects_root=projects_root, open_gui=True)
        # Validate catalogs immediately
        try:
            cfg_models = []
            for c in self.session.state.config_catalog:
                try:
                    cfg_models.append(load_config(c.path))
                except Exception as ce:
                    self.log_panel.append(f"Failed to load config {c.config_id}: {ce}", level='WARN')
            stale_map = revalidate_existing_configs_with_lock(cfg_models, analysis_manager=self.session.manager)
            for cfg_id, errs in stale_map.items():
                if errs:
                    for e in errs:
                        self.log_panel.append(f"CONFIG INVALID {cfg_id}: {e}")
        except Exception as exc:
            self.log_panel.append(f"Validation exception: {exc}")
        # open GUI and assert user should only edit inside Streamline session
        vsp = vsp_session.get_vsp()
        if vsp is not None:
            try:
                proj_file = self.session.project_root / f"{project_id}.vsp3"
                if proj_file.exists():
                    vsp.ReadVSPFile(str(proj_file))
                else:
                    vsp.WriteVSPFile(str(proj_file))
            except Exception as exc:
                self.log_panel.append(f"OpenVSP load warning: {exc}")
        self.log_panel.append("Geometry edits must be performed while this TUI session is active; do not modify the .vsp3 externally.")
        self.configs_panel.session = self.session
        self.ops_panel.session = self.session
        self.jobs_panel.session = self.session
        self._refresh_all()
        self.log_panel.append(f"Project '{project_id}' loaded.")

    # --- Refresh helpers ---
    def _refresh_all(self):
        self.configs_panel.redraw()
        self.ops_panel.redraw()
        self.jobs_panel.redraw()

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
            if isinstance(evt, JobFailedEvent):
                self._schedule_log_append(f"JOB FAILED {evt.job_id}: {evt.error}", level='ERR')
            if isinstance(evt, ReceiptAddedEvent) and evt.analysis_key == 'test_noop':
                receipt = evt.receipt_summary or {}
                dur = receipt.get('duration_s') or receipt.get('duration') or None
                if isinstance(dur, (int, float)):
                    self.last_test_duration = float(dur)
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

        et = getattr(evt, 'type', None)
        payload = getattr(evt, 'payload', {})
        if et == LOG_MESSAGE:
            msg = payload.get('message')
            lvl = payload.get('level')
            self._schedule_log_append(msg, level=lvl)
        # Future: op catalog change events -> self._mark_refresh('ops')

    def _schedule_log_append(self, text: str, level: str | None = None):
        now_epoch = int(_time())
        if now_epoch != self._log_epoch:
            # new second: flush suppression summary if any
            if self._log_suppressed:
                summary = f"(suppressed {self._log_suppressed} log lines)"
                try:
                    self.call_from_thread(lambda: self.log_panel.append(summary))
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
            self.log_panel.append(text, level=level)
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
        # update status bar
        if self.session:
            active_tab_name = self.tabs.active.replace('tab-','') if hasattr(self, 'tabs') else 'configs'
            self.status_bar.update_status(
                active_cfg=self.configs_panel.selected_config_id(),
                active_op=self.ops_panel.selected_op_id(),
                jobs=self.session.state.jobs,
                active_tab=active_tab_name,
                last_test_duration=self.last_test_duration,
            )
        for k in self._refresh_flags: self._refresh_flags[k] = False
        self._refresh_timer = None

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
    def on_tabs_tab_activated(self, event):  # pragma: no cover
        self._sync_tab_switch()

    # --- Button press handler ---
    def on_button_pressed(self, event):  # pragma: no cover
        bid = getattr(event.button, 'id', '')
        if bid == 'btn_run_test':
            self.action_run_test()
        elif bid == 'btn_refresh':
            self.action_refresh()
        elif bid == 'btn_diff':
            self.action_diff_config()
        elif bid == 'btn_update':
            self.action_update_config()

# Entrypoint helper

def run_app():  # pragma: no cover - manual execution path
    app = StreamlineApp()
    app.run()

if __name__ == "__main__":  # pragma: no cover
    run_app()
