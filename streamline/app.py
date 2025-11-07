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

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Iterable
from time import time as _time
from datetime import datetime, timezone

from textual.app import App, ComposeResult, SystemCommand
from textual.widgets import Static, Footer, Input, ListView, ListItem, Tabs, Tab, ContentSwitcher, RichLog, Label
from textual.reactive import reactive
from rich.text import Text
from rich.table import Table
from rich import box
from textual import events
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.timer import Timer
from textual.command import Provider, Hit, DiscoveryHit, Hits
from textual.screen import Screen
from textual.style import Style

from .tui import ProjectSession, create_project_session
from .tui.context import SessionJob
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
    AnalysisJobQueued,
    AnalysisJobStatusChanged,
    ReceiptAddedEvent,
    WorkerFailed,
    LogMessageEvent,
)
from .tui.widgets.jobs_panel import JobsPanel, JobListItem
from .tui.widgets.ops_panel import OpsPanel
from .tui.widgets.configs_panel import ConfigsPanel
from .tui.widgets.collapsible_log import CollapsibleLog
from .tui.widgets.project_header import ProjectHeader
from .tui.widgets.project_views import ProjectSelectionView, NewProjectView, ProjectChosen
from .tui.widgets.commands import ProjectCommandProvider
from .core.logging import LoggingConfig, setup_logging
from .vsp import session as vsp_session
from .main import create_new_project  # reuse project scaffolder
from .io.fs import load_project_def, load_config
from .io.config_catalog import load_config_catalog, get_configuration
from .io.op_catalog import load_op_catalog, get_operating_point
from .vsp.configure import revalidate_existing_configs_with_lock
from .vsp.contracts.stability import StabilityTicket

# --- Log bridge ---

class EventBusLogHandler(logging.Handler):
    """Logging handler that publishes log records as LogMessageEvent to the event bus."""
    
    def emit(self, record: logging.LogRecord) -> None:
        bus = get_global_event_bus()
        if not bus:
            return
        try:
            # Extract structured context from the log record
            context = getattr(record, "context", None)
            hint = getattr(record, "hint", None)
            error_code = getattr(record, "error_code", None)
            
            # Format exception info if present
            exc_info = None
            if record.exc_info:
                import traceback
                exc_info = ''.join(traceback.format_exception(*record.exc_info))
            
            bus.publish(
                LogMessageEvent(
                    level=record.levelname,
                    name=record.name,
                    message=record.getMessage(),
                    timestamp=record.created,
                    context=context if isinstance(context, dict) else None,
                    hint=hint,
                    error_code=error_code,
                    exc_info=exc_info,
                )
            )
        except Exception:
            # Prevent logging errors from crashing the handler
            self.handleError(record)


def _resolve_logging_level(debug: bool, cli_level: Optional[str]) -> str:
    if (debug):
        return "DEBUG"
    if (cli_level):
        return cli_level.upper()
    env_level = os.environ.get("STREAMLINE_LOG_LEVEL")
    if (env_level):
        return env_level.upper()
    return "INFO"


def _resolve_logfile(cli_logfile: Optional[str]) -> Optional[Path]:
    source = cli_logfile or os.environ.get("STREAMLINE_LOG_FILE")
    if (not source):
        return None
    return Path(source)


def _install_event_log_bridge(level: int) -> None:
    root_logger = logging.getLogger()
    handler = next((h for h in root_logger.handlers if isinstance(h, EventBusLogHandler)), None)
    if (handler is None):
        handler = EventBusLogHandler()
        root_logger.addHandler(handler)
    handler.setLevel(level)
    root_logger.setLevel(level)
    streamline_logger = logging.getLogger("streamline")
    streamline_logger.propagate = True
    textual_logger = logging.getLogger("textual")
    textual_logger.handlers.clear()
    textual_logger.setLevel(level)
    textual_logger.propagate = True


def _configure_logging(debug: bool, cli_level: Optional[str], cli_logfile: Optional[str]) -> int:
    level_name = _resolve_logging_level(debug, cli_level)
    logfile = _resolve_logfile(cli_logfile)
    level_key = level_name.upper()
    if (level_key not in logging._nameToLevel):
        raise SystemExit(f"Unknown log level '{level_name}'")
    # Disable console logging for TUI - all logs go through EventBusLogHandler instead
    config = LoggingConfig(level=level_key, logfile=logfile, propagate=True, console=False)
    setup_logging(config, force=True)
    resolved = logging._nameToLevel[level_key]
    _install_event_log_bridge(resolved)
    return resolved
# --- Widgets ---

class Placeholder(Static):
    pass

# --- Main App ---

class StreamlineApp(App):
    COMMANDS = App.COMMANDS | {ProjectCommandProvider}
    CSS_PATH = str(Path(__file__).parent / "tui" / "styles" / "app.tcss")
    BINDINGS = [
        ("q", "quit_app", "Quit"),
        ("s", "save_project", "Save"),
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
            if (command.title in suppress):
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
        logging.getLogger(__name__).debug("Streamline TUI mounted")
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
        # Setup event bus listener
        bus = get_global_event_bus()
        if (bus is None):
            from .tui.event_bus import EventBus
            bus = EventBus()
            set_global_event_bus(bus)
        self._bus_subscription = bus.subscribe_any(self._handle_event_from_bus)  # store for cleanup
        # Debounce state
        self._refresh_flags = {"configs": False, "ops": False, "jobs": False}
        self._refresh_timer: Timer | None = None
        # Rate limit state
        self._log_epoch = int(_time())
        self._log_count = 0
        self._log_suppressed = 0
        # Auto-select configs tab and ensure it's focused
        self.tabs.active = "tab-configs"
        self.switcher.current = "configs_panel"
        # Focus the configs tab to make it visually highlighted
        self.call_after_refresh(lambda: self.tabs.focus())

    # --- Actions ---
    def action_quit_app(self) -> None:
        self.exit()
    def action_open_project(self) -> None:
        self._show_project_selector()
    def action_new_project(self) -> None:
        self._show_new_project()
    def action_save_project(self) -> None:
        """Save the current OpenVSP project file"""
        if not self.session:
            self._schedule_log_append("No project loaded to save", level='WARN')
            return
        
        vsp = vsp_session.get_vsp()
        if vsp is None:
            self._schedule_log_append("OpenVSP not available", level='ERR')
            return
        
        try:
            project_id = self.session.state.project_id
            proj_file = self.session.project_root / f"{project_id}.vsp3"
            vsp.WriteVSPFile(str(proj_file))
            self._schedule_log_append(f"Saved project to {proj_file.name}", level='INFO')
            self._show_notification(f"Saved {project_id}.vsp3", level="success", duration=2.0)
        except Exception as exc:
            self._schedule_log_append(f"Failed to save project: {exc}", level='ERR')
            self._show_notification("Save failed", level="error", duration=3.0)
    def action_refresh(self) -> None:
        if (self.session):
            self.session.refresh_catalogs()
            self._refresh_all()
    def action_focus_tab_configs(self):
        self.tabs.active = "tab-configs"; self._sync_tab_switch()
    def action_focus_tab_ops(self):
        self.tabs.active = "tab-ops"; self._sync_tab_switch()
    def action_focus_tab_jobs(self):
        self.tabs.active = "tab-jobs"; self._sync_tab_switch()
    def action_run_test(self):
        if (not self.session):
            self._schedule_log_append("No session for test analysis", level='WARN'); return
        session = self.session
        if (not session.state.config_catalog):
            self._schedule_log_append("Load a configuration before running test jobs", level='WARN'); return
        if (not session.state.op_catalog):
            self._schedule_log_append("Load an operating point before running test jobs", level='WARN'); return

        config_id = self.configs_panel.selected_config_id()
        if (not config_id):
            config_id = session.state.config_catalog[0].config_id
        op_id = self.ops_panel.selected_op_id()
        if (not op_id):
            op_id = session.state.op_catalog[0].op_id

        try:
            configuration = get_configuration(session.project_root, config_id)
        except Exception as exc:
            self._schedule_log_append(f"Failed to load config '{config_id}': {exc}", level='ERR'); return
        try:
            operating_point = get_operating_point(session.project_root, op_id)
        except Exception as exc:
            self._schedule_log_append(f"Failed to load operating point '{op_id}': {exc}", level='ERR'); return

        # Build stability ticket with configuration defaults
        stability_kwargs: Dict[str, Any] = {"config_id": config_id}
        if (configuration.mode):
            stability_kwargs["mode_id"] = configuration.mode.mode_id
            stability_kwargs["use_mode_flag"] = configuration.mode.use_mode_flag
        if (configuration.geom_set_index is not None):
            stability_kwargs["set_index"] = configuration.geom_set_index
        if (configuration.geom_set_name):
            stability_kwargs["set_name"] = configuration.geom_set_name
        
        stability_kwargs["alpha_deg"] = 2.0
        if (operating_point.mach is not None):
            stability_kwargs["mach"] = operating_point.mach
        elif (operating_point.tas_mps is not None):
            stability_kwargs["vinf_mps"] = operating_point.tas_mps
        
        # Setup log file redirection
        log_display: Optional[str] = None
        project_root = session.project_root
        try:
            logs_dir = (project_root / "results" / "_vsp_logs").resolve()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / f"vspaero_stability_{op_id}_{int(_time())}.log"
            log_display = str(log_file)
            stability_kwargs["redirect_file"] = log_display
        except Exception:
            log_display = None
        
        stability_ticket = StabilityTicket(**stability_kwargs)

        stability_context = {
            "config_id": config_id,
            "operating_point_id": op_id,
            "alpha_deg": stability_ticket.alpha_deg,
        }
        if (operating_point.mach is not None):
            stability_context["mach"] = operating_point.mach
        if (operating_point.tas_mps is not None):
            stability_context["tas_mps"] = operating_point.tas_mps
        if (log_display):
            stability_context["redirect_file"] = log_display

        try:
            stability_job = session.queue_analysis(
                "vspaero_stability",
                stability_ticket,
                context_extras=stability_context,
                runtime_kwargs={
                    "configuration": configuration,
                    "operating_point": operating_point,
                },
            )
        except Exception as exc:
            self._schedule_log_append(f"Stability submit failed: {exc}", level='ERR'); return

        if (log_display):
            self._schedule_log_append(f"Stability analysis output redirected to {log_display}", level="INFO")
        self._schedule_log_append(
            f"Queued stability analysis for config '{config_id}' at op '{op_id}' (job: {stability_job.job_id[:8]})",
            level='INFO',
        )
    def action_diff_config(self):
        cfg_id = self.configs_panel.selected_config_id()
        if (not cfg_id):
            self._schedule_log_append("No configuration selected for diff", level='WARN'); return
        self._schedule_log_append(f"(diff placeholder) Config {cfg_id}", level='INFO')
    def action_update_config(self):
        cfg_id = self.configs_panel.selected_config_id()
        if (not cfg_id):
            self._schedule_log_append("No configuration selected for update", level='WARN'); return
        self._schedule_log_append(f"(update placeholder) Config {cfg_id}", level='INFO')

    def _show_project_selector(self) -> None:
        if (not hasattr(self, "primary_switcher")):
            return
        if (self.primary_switcher.current == "project_selector"):
            self.project_selector.refresh_projects()
            self.project_selector.focus_list()
            return
        self.project_selector.refresh_projects()
        self.primary_switcher.current = "project_selector"
        self.project_selector.focus_list()

    def _hide_project_selector(self) -> None:
        if (not hasattr(self, "primary_switcher")):
            return
        self.primary_switcher.current = "layout_main"
        try:
            self.tabs.focus()
        except Exception:
            pass

    def _show_new_project(self) -> None:
        if (not hasattr(self, "primary_switcher")):
            return
        self.new_project_view.reset()
        self.primary_switcher.current = "new_project_view"
        self.new_project_view.focus_input()

    def _hide_new_project(self) -> None:
        if (not hasattr(self, "primary_switcher")):
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
        if (not target.exists()):
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
                if (errs):
                    for e in errs:
                        self.log_panel.log(f"CONFIG INVALID {cfg_id}: {e}")
        except Exception as exc:
            self.log_panel.log(f"Validation exception: {exc}")
        # open GUI and assert user should only edit inside Streamline session
        vsp = vsp_session.get_vsp()
        if (vsp is not None):
            try:
                if (not vsp_session.ensure_gui_started(vsp)):
                    self.log_panel.log("OpenVSP GUI not started (headless binding?)", level="WARN")
            except Exception as exc:
                self.log_panel.log(f"OpenVSP GUI start warning: {exc}", level="WARN")
            try:
                proj_file = self.session.project_root / f"{project_id}.vsp3"
                if (proj_file.exists()):
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
    def _handle_event_from_bus(self, evt):
        # Check if we're already on the UI thread
        import threading
        if threading.current_thread() == threading.main_thread():
            # Already on UI thread - call directly to avoid deadlock
            self._handle_event(evt)
        else:
            # On background thread - must use call_from_thread
            try:
                self.call_from_thread(lambda e=evt: self._handle_event(e))
            except Exception as exc:
                # Log the error but don't try to handle event on worker thread
                import logging
                logging.getLogger(__name__).error(
                    "Failed to dispatch event to UI thread",
                    extra={"hint": str(exc)}
                )

    def _handle_event(self, evt):  # evt is generic from bus
        # Handle typed events first
        if (isinstance(evt, AnalysisJobQueued)):
            self._mark_refresh('jobs')
            if (self.session and evt.session_id and evt.session_id != getattr(self.session, "session_id", None)):
                return
            message = f"Queued {evt.analysis_key} ({evt.job_id[:8]})"
            self._schedule_log_append(message, level="INFO")
            # DO NOT call sync here - it can block on call_from_thread
            # The job will be synced when it actually starts/completes
            return

        if (isinstance(evt, AnalysisJobStatusChanged)):
            self._mark_refresh('jobs')
            if (self.session and evt.session_id and evt.session_id != getattr(self.session, "session_id", None)):
                return
            status = (evt.status or "unknown").lower()
            message = f"{status.title()} {evt.analysis_key} ({evt.job_id[:8]})"
            level = "INFO"
            if (status == "cached"):
                cache_sha = evt.ticket_sha[:10] + "..." if (evt.ticket_sha and len(evt.ticket_sha) > 10) else evt.ticket_sha
                suffix = f" (cache sha={cache_sha})" if (cache_sha) else ""
                message = f"Reused cached {evt.analysis_key}{suffix}"
            if (status == "failed"):
                level = "ERR"
                if (evt.error):
                    message = f"FAILED {evt.analysis_key} ({evt.job_id[:8]}): {evt.error}"
            elif (status == "running"):
                message = f"Running {evt.analysis_key} ({evt.job_id[:8]})"
            elif (status == "completed"):
                message = f"Completed {evt.analysis_key} ({evt.job_id[:8]})"
            self._schedule_log_append(message, level=level)
            return

        if (isinstance(
            evt,
            (
                JobSubmittedEvent, 
                JobStartedEvent,
                JobCompletedEvent,
                JobFailedEvent,
                ReceiptAddedEvent,
            ),
        )):
            self._mark_refresh('jobs')
            # Only sync for actual state changes (started/completed/failed), NOT for submitted
            if self.session and isinstance(evt, (JobStartedEvent, JobCompletedEvent, JobFailedEvent)):
                try:
                    self.session.sync_job_states()
                except Exception:
                    pass
            if (isinstance(evt, JobSubmittedEvent)):
                self._show_notification(
                    f"Queued {evt.analysis_key} ({evt.job_id[:8]})",
                    level="info",
                    duration=3.0,
                )
            if (isinstance(evt, JobStartedEvent)):
                self._show_notification(
                    f"Started {evt.analysis_key} ({evt.job_id[:8]})",
                    level="info",
                    duration=3.0,
                )
            if (isinstance(evt, JobFailedEvent)):
                self._show_notification(
                    f"Job {evt.analysis_key} failed",
                    level="error",
                    duration=6.0,
                )
            if (isinstance(evt, JobCompletedEvent)):
                self._show_notification(
                    f"Completed {evt.analysis_key}",
                    level="success",
                    duration=4.0,
                )
            if (isinstance(evt, ReceiptAddedEvent) and evt.analysis_key == 'test_noop'):
                receipt = evt.receipt_summary or {}
                dur = receipt.get('duration_s') or receipt.get('duration') or None
                if (isinstance(dur, (int, float))):
                    self.last_test_duration = float(dur)
            return

        if (isinstance(evt, WorkerFailed)):
            detail = f": {evt.details}" if (evt.details) else ""
            self._schedule_log_append(f"Worker failure{detail}", level="ERR")
            self._show_notification("Analysis worker encountered an error", level="error", duration=6.0)
            return

        if (isinstance(
            evt,
            (
                CatalogChangedEvent,
                ConfigurationCreatedEvent,
                ConfigurationUpdatedEvent,
                ConfigurationRemovedEvent,
            ),
        )):
            self._mark_refresh('configs')
            return

        if (isinstance(evt, ConfigurationStaleEvent)):
            if (evt.config_id):
                self.configs_panel.stale_ids.add(evt.config_id)
            self._mark_refresh('configs')
            return

        if isinstance(evt, LogMessageEvent):
            # Use the dedicated event handler method
            try:
                self.call_from_thread(lambda: self.log_panel.log_from_event(evt))
            except Exception:
                # Fallback to direct call if threading fails
                self.log_panel.log_from_event(evt)
            return
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
        if (now_epoch != self._log_epoch):
            # new second: flush suppression summary if any
            if (self._log_suppressed):
                summary = f"(suppressed {self._log_suppressed} log lines)"
                try:
                    self.call_from_thread(lambda: self.log_panel.log(summary))
                except Exception:
                    pass
            self._log_epoch = now_epoch
            self._log_count = 0
            self._log_suppressed = 0
        if (self._log_count > 120):  # raise per-second threshold for verbose DEBUG output
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
        if (not self._refresh_timer):
            self._refresh_timer = self.set_timer(0.1, self._apply_refresh_flags)  # removed repeat kw
    def _apply_refresh_flags(self):
        if (self._refresh_flags.get('configs')): self.configs_panel.redraw()
        if (self._refresh_flags.get('ops')): self.ops_panel.redraw()
        if (self._refresh_flags.get('jobs')): self.jobs_panel.redraw()
        self._update_header()
        for k in self._refresh_flags: self._refresh_flags[k] = False
        self._refresh_timer = None

    def _update_header(self) -> None:
        header = getattr(self, "project_header", None)
        if (header is None):
            return
        project_id = None
        total_jobs = None
        running_jobs = 0
        if (self.session):
            project_id = self.session.state.project_id
            jobs = list(self.session.state.jobs.values())
            total_jobs = len(jobs)
            running_jobs = sum(
                1
                for job in jobs
                if (job.status not in {"completed", "cached", "failed"})
            )
        active_label = "Configs"
        tabs = getattr(self, "tabs", None)
        if (tabs is not None):
            try:
                active_label = tabs.active.replace("tab-", "").title()
            except Exception:
                pass
        header.update_context(
            project_id=project_id,
            active_tab=active_label,
            running_jobs=running_jobs if (total_jobs is not None) else None,
            total_jobs=total_jobs,
        )

    # --- Message handlers ---
    def on_project_chosen(self, msg: ProjectChosen) -> None:  # pragma: no cover - UI event
        self._load_project(msg.project_id.strip())

    def on_exit(self) -> None:  # graceful shutdown
        try:
            if (self.session):
                self.session.stop()
        except Exception:
            pass
        try:
            if (getattr(self, '_bus_subscription', None)):
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

def run_app(argv: Optional[list[str]] = None) -> None:  # pragma: no cover - manual execution path
    args = list(argv if (argv is not None) else sys.argv[1:])
    debug = False
    log_level: Optional[str] = None
    log_file: Optional[str] = None
    passthrough: list[str] = []

    idx = 0
    while (idx < len(args)):
        arg = args[idx]
        if (arg in ("-debug", "--debug")):
            debug = True
        elif (arg.startswith("--log-level=")):
            log_level = arg.split("=", 1)[1]
        elif (arg == "--log-level"):
            if (idx + 1 >= len(args)):
                raise SystemExit("--log-level requires a value")
            idx += 1
            log_level = args[idx]
        elif (arg.startswith("--log-file=")):
            log_file = arg.split("=", 1)[1]
        elif (arg == "--log-file"):
            if (idx + 1 >= len(args)):
                raise SystemExit("--log-file requires a path")
            idx += 1
            log_file = args[idx]
        else:
            passthrough.append(arg)
        idx += 1

    level = _configure_logging(debug, log_level, log_file)
    logging.getLogger(__name__).debug(
        "Logging configured for Streamline TUI",
        extra={"context": {"level": logging.getLevelName(level), "log_file": log_file or os.environ.get("STREAMLINE_LOG_FILE")}},
    )
    if (passthrough):
        logging.getLogger(__name__).warning(
            "Ignoring unrecognized TUI arguments",
            extra={"context": {"args": passthrough}},
        )

    app = StreamlineApp()
    app.run()

if (__name__ == "__main__"):  # pragma: no cover
    run_app()








