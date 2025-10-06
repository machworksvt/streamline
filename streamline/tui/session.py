from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..analysis import AnalysisManager
from ..core import StreamlineError, get_logger
from ..io.fs import load_project_def
from ..io.results_index import load_result_entries


@dataclass(slots=True)
class ProjectSummary:
    project_id: str
    path: Path
    description: str
    has_model: bool
    last_run: Optional[datetime]


class StreamlineSession:
    """Owns shared state for the Textual application."""

    def __init__(self, projects_root: Path, *, open_gui: bool = False) -> None:
        self.logger = get_logger(__name__)
        self.projects_root = projects_root
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self._analysis_manager: Optional[AnalysisManager] = None
        self._open_gui = open_gui

    @property
    def analysis_manager(self) -> AnalysisManager:
        if self._analysis_manager is None:
            self._analysis_manager = AnalysisManager(
                results_root=None,
                open_gui=self._open_gui,
            )
        return self._analysis_manager

    def discover_projects(self) -> List[ProjectSummary]:
        summaries: List[ProjectSummary] = []
        for candidate in sorted(self.projects_root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                project_def = load_project_def(candidate)
            except FileNotFoundError:
                continue
            except StreamlineError as exc:
                self.logger.warning(
                    "Failed to load project definition", context={"project": str(candidate)}, hint=str(exc)
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "Unhandled error loading project definition",
                    context={"project": str(candidate)},
                    hint=str(exc),
                )
                continue

            vsp_path = candidate / f"{candidate.name}.vsp3"
            last_run = None
            try:
                entries = load_result_entries(candidate)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "Failed to load project results index",
                    context={"project_id": project_def.project_id},
                    hint=str(exc),
                )
                entries = []
            if entries:
                entries = [e for e in entries if e.manifest and e.manifest.started_utc]
                if entries:
                    entries.sort(key=lambda e: e.manifest.started_utc or "", reverse=True)
                    last = entries[0].manifest.started_utc
                    if last:
                        try:
                            last_run = datetime.fromisoformat(last.replace("Z", ""))
                        except ValueError:
                            last_run = None

            summaries.append(
                ProjectSummary(
                    project_id=project_def.project_id,
                    path=candidate,
                    description=project_def.description or "",
                    has_model=vsp_path.exists(),
                    last_run=last_run,
                )
            )
        return summaries

    def pending_jobs(self) -> Dict[str, object]:
        if self._analysis_manager is None:
            return {}
        try:
            return self._analysis_manager.pending_jobs()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Failed to query pending jobs", hint=str(exc))
            return {}

    def bind_results_root(self, project: Optional[ProjectSummary]) -> None:
        if self._analysis_manager is None or project is None:
            return
        results_root = project.path / "results"
        results_root.mkdir(parents=True, exist_ok=True)
        self._analysis_manager.set_results_root(results_root)

    def shutdown(self) -> None:
        self._analysis_manager = None
