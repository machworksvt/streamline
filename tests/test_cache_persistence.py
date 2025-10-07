from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from streamline.analysis.manager import AnalysisManager
from streamline.core.schema import RunManifest
from streamline.vsp.contracts.base import Receipt, Ticket


class DummyReceipt(Receipt):
    value: str


def _make_manifest(ticket_sha: str) -> RunManifest:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return RunManifest(
        tool_versions={"streamline": "test"},
        inputs_sha256=ticket_sha,
        started_utc=now,
        ended_utc=now,
        source_paths=[],
    )


def _dummy_runner(_vsp: object, ticket: Ticket, *, value: str = "cached") -> DummyReceipt:
    ticket_sha = ticket.sha256({"analysis": "dummy"})
    manifest = _make_manifest(ticket_sha)
    return DummyReceipt(
        run_manifest=manifest,
        ticket_sha256=ticket_sha,
        artifact_dir=None,
        artifacts={},
        value=value,
    )


@pytest.fixture()
def temp_results_root(tmp_path: Path) -> Path:
    results_root = tmp_path / "results"
    results_root.mkdir(parents=True, exist_ok=True)
    return results_root


def test_analysis_manager_persists_cache_across_sessions(temp_results_root: Path) -> None:
    manager = AnalysisManager(
        vsp=object(),
        results_root=temp_results_root,
        auto_init_vsp=False,
        open_gui=False,
    )
    manager.register_analysis(
        "dummy",
        _dummy_runner,
        receipt_model=DummyReceipt,
        uses_vsp_lock=False,
    )

    ticket = Ticket()
    manager.submit("dummy", ticket, runtime_kwargs={"value": "persisted"})
    manager.run_next()

    ticket_sha = ticket.sha256({"analysis": "dummy"})
    entry = manager.cache_entry("dummy", ticket_sha)
    assert entry is not None
    assert entry.receipt.value == "persisted"

    cache_index = temp_results_root / "_cache" / "cache_index.json"
    assert cache_index.exists()

    # Rehydrate a fresh manager and ensure the cache loads from disk
    manager_two = AnalysisManager(
        vsp=object(),
        results_root=temp_results_root,
        auto_init_vsp=False,
        open_gui=False,
    )
    manager_two.register_analysis(
        "dummy",
        _dummy_runner,
        receipt_model=DummyReceipt,
        uses_vsp_lock=False,
    )

    cached_entry = manager_two.cache_entry("dummy", ticket_sha)
    assert cached_entry is not None
    assert cached_entry.receipt.value == "persisted"
