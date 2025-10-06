from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.logging import get_logger
from ..core.schema import RunManifest


INDEX_FILENAME = "index.json"


def _index_path(project_root: Path) -> Path:
    return project_root / "results" / INDEX_FILENAME


@dataclass
class ResultIndexEntry:
    analysis: str
    ticket_sha256: str
    artifact_dir: Optional[str]
    summary: Dict[str, Any] = field(default_factory=dict)
    manifest: Optional[RunManifest] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "analysis": self.analysis,
            "ticket_sha256": self.ticket_sha256,
            "artifact_dir": self.artifact_dir,
            "summary": self.summary,
        }
        if self.manifest is not None:
            data["manifest"] = json.loads(self.manifest.model_dump_json())
        return data


def load_results_index(project_root: Path) -> Dict[str, Any]:
    path = _index_path(project_root)
    if not path.exists():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_results_index(project_root: Path, data: Dict[str, Any]) -> None:
    path = _index_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def append_result_entry(project_root: Path, entry: ResultIndexEntry) -> None:
    data = load_results_index(project_root)
    entries: List[Dict[str, Any]] = data.setdefault("entries", [])
    entries = [raw for raw in entries if raw.get("ticket_sha256") != entry.ticket_sha256]
    entries.append(entry.to_dict())
    entries.sort(key=lambda raw: raw.get("manifest", {}).get("started_utc", ""))
    data["entries"] = entries
    save_results_index(project_root, data)


def load_result_entries(project_root: Path) -> List[ResultIndexEntry]:
    logger = get_logger(__name__, project=str(project_root))
    data = load_results_index(project_root)
    entries: List[ResultIndexEntry] = []
    for raw in data.get("entries", []):
        manifest_raw = raw.get("manifest")
        manifest = None
        if manifest_raw:
            try:
                manifest = RunManifest.model_validate(manifest_raw)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to validate manifest for result entry",
                    context={
                        "ticket_sha256": raw.get("ticket_sha256"),
                        "analysis": raw.get("analysis"),
                    },
                    hint=str(exc),
                )
                manifest = None
        entries.append(
            ResultIndexEntry(
                analysis=raw.get("analysis", "unknown"),
                ticket_sha256=raw.get("ticket_sha256", ""),
                artifact_dir=raw.get("artifact_dir"),
                summary=raw.get("summary", {}) or {},
                manifest=manifest,
            )
        )
    return entries


def remove_result_entries(project_root: Path, *, ticket_shas: Iterable[str]) -> None:
    """Remove any index entries whose ticket SHA matches ``ticket_shas``."""

    sha_set = {sha for sha in ticket_shas if sha}
    if not sha_set:
        return

    data = load_results_index(project_root)
    entries: List[Dict[str, Any]] = data.get("entries", []) or []
    filtered = [raw for raw in entries if raw.get("ticket_sha256") not in sha_set]
    if len(filtered) == len(entries):
        return

    data["entries"] = filtered
    save_results_index(project_root, data)
