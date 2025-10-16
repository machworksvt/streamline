from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from streamline.analysis.manager import AnalysisManager
from streamline.core.schema import RunManifest
from streamline.io.results_index import ResultIndexEntry, append_result_entry
from streamline.analysis.contracts import Ticket, Receipt
from streamline.vsp.run_utils import dump_json, prepare_results_dir, relativize


class DummyReceipt(Receipt):
    value: str


def _manifest(ticket_sha: str, started: datetime, ended: datetime, manager: AnalysisManager) -> RunManifest:
    started_iso = started.astimezone(timezone.utc).isoformat(timespec="seconds")
    ended_iso = ended.astimezone(timezone.utc).isoformat(timespec="seconds")
    return RunManifest(
        tool_versions=manager.versions,
        inputs_sha256=ticket_sha,
        started_utc=f"{started_iso}Z",
        ended_utc=f"{ended_iso}Z",
        source_paths=[],
    )


def dummy_runner(_vsp: object, ticket: Ticket, *, value: str = "cached") -> Dict[str, str]:
    _ = ticket.sha256({"analysis": "dummy"})
    return {"value": value}


def dummy_materializer(
    manager: AnalysisManager,
    job,
    ticket_sha: str,
    payload: Dict[str, str],
    started: datetime,
    ended: datetime,
) -> DummyReceipt:
    started = started.astimezone(timezone.utc) if started.tzinfo else started.replace(tzinfo=timezone.utc)
    ended = ended.astimezone(timezone.utc) if ended.tzinfo else ended.replace(tzinfo=timezone.utc)
    manifest = _manifest(ticket_sha, started, ended, manager)
    results_root = manager.results_root
    artifact_dir = None
    artifacts: Dict[str, str] = {}

    if results_root is not None:
        run_dir = prepare_results_dir(results_root, job.analysis_key, ticket_sha, started)
        artifact_dir = relativize(run_dir, results_root)
        dump_json(run_dir / "summary.json", {"value": payload["value"]})
        artifacts["summary_json"] = relativize(run_dir / "summary.json", results_root)
        append_result_entry(
            results_root.parent,
            ResultIndexEntry(
                analysis=job.analysis_key,
                ticket_sha256=ticket_sha,
                artifact_dir=artifact_dir,
                summary={"value": payload["value"]},
                manifest=manifest,
            ),
        )
        manifest = RunManifest(
            tool_versions=manager.versions,
            inputs_sha256=ticket_sha,
            started_utc=manifest.started_utc,
            ended_utc=manifest.ended_utc,
            source_paths=[artifact_dir],
        )

    return DummyReceipt(
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=artifact_dir,
        artifacts=artifacts,
        value=payload["value"],
    )


def register_dummy_analysis(manager: AnalysisManager) -> None:
    manager.register_analysis(
        "dummy",
        dummy_runner,
        materializer=dummy_materializer,
        default_dependency_keys={"vsp_model"},
        receipt_model=DummyReceipt,
        uses_vsp_lock=False,
    )

