from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from streamline.analysis.manager import AnalysisManager
from streamline.io.cache_store import CacheRecord, save_cache_records
from streamline.io.results_index import load_result_entries
from streamline.vsp.contracts.base import Ticket

from tests.support.dummy_analysis import DummyReceipt, register_dummy_analysis


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "results").mkdir(parents=True, exist_ok=True)
    return root


def _ticket_sha(ticket: Ticket, manager: AnalysisManager, job_id: str) -> str:
    context = manager.job_state(job_id).job.context_extras
    return ticket.sha256(context)


def test_cache_persists_and_rehydrates(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_id = manager.submit("dummy", ticket, runtime_kwargs={"value": "persisted"})
    manager.run_next()

    ticket_sha = _ticket_sha(ticket, manager, job_id)
    entry = manager.cache_entry("dummy", ticket_sha)
    assert entry is not None
    assert entry.receipt.value == "persisted"

    manager_two = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager_two)

    cached_entry = manager_two.cache_entry("dummy", ticket_sha)
    assert cached_entry is not None
    assert cached_entry.receipt.value == "persisted"


def test_invalidate_drops_cached_entry(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_id = manager.submit("dummy", ticket)
    manager.run_next()

    ticket_sha = _ticket_sha(ticket, manager, job_id)
    impacted = manager.invalidate(["vsp_model"])
    assert ticket_sha in impacted
    assert manager.cache_entry("dummy", ticket_sha) is None
    assert manager.cache_summaries() == []


def test_clear_cache_removes_artifacts_and_index(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_id = manager.submit("dummy", ticket, runtime_kwargs={"value": "artifact"})
    receipt = manager.run_next()

    ticket_sha = _ticket_sha(ticket, manager, job_id)
    assert receipt is not None
    assert receipt.artifact_dir is not None
    artifact_path = results_root / receipt.artifact_dir
    assert artifact_path.exists()
    assert any(entry.ticket_sha256 == ticket_sha for entry in load_result_entries(project_root))

    removed = manager.clear_cache(analysis_keys=["dummy"], drop_results=True)
    assert removed == [ticket_sha]
    assert not artifact_path.exists()
    assert all(entry.ticket_sha256 != ticket_sha for entry in load_result_entries(project_root))


def test_clear_cache_keep_results_retains_artifacts(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_id = manager.submit("dummy", ticket, runtime_kwargs={"value": "keep"})
    receipt = manager.run_next()

    ticket_sha = _ticket_sha(ticket, manager, job_id)
    artifact_path = results_root / receipt.artifact_dir
    assert artifact_path.exists()

    removed = manager.clear_cache(analysis_keys=["dummy"], drop_results=False)
    assert removed == [ticket_sha]
    assert artifact_path.exists()
    assert any(entry.ticket_sha256 == ticket_sha for entry in load_result_entries(project_root))


def test_clear_cache_filters_by_ticket(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_one = manager.submit("dummy", ticket, context_extras={"label": "one"}, runtime_kwargs={"value": "one"})
    job_two = manager.submit("dummy", ticket, context_extras={"label": "two"}, runtime_kwargs={"value": "two"})
    manager.run_next()
    manager.run_next()

    sha_one = _ticket_sha(ticket, manager, job_one)
    sha_two = _ticket_sha(ticket, manager, job_two)
    assert manager.cache_entry("dummy", sha_one) is not None
    assert manager.cache_entry("dummy", sha_two) is not None

    removed = manager.clear_cache(ticket_shas=[sha_one], drop_results=False)
    assert removed == [sha_one]
    assert manager.cache_entry("dummy", sha_one) is None
    assert manager.cache_entry("dummy", sha_two) is not None


def test_cache_summaries_reports_entries(project_root: Path) -> None:
    results_root = project_root / "results"
    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    register_dummy_analysis(manager)

    ticket = Ticket()
    job_id = manager.submit("dummy", ticket)
    manager.run_next()
    ticket_sha = _ticket_sha(ticket, manager, job_id)

    summaries = manager.cache_summaries()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["analysis"] == "dummy"
    assert summary["ticket_sha"] == ticket_sha
    assert summary["status"] == "available"

    filtered = manager.cache_summaries(ticket_shas=[ticket_sha])
    assert len(filtered) == 1
    assert filtered[0]["ticket_sha"] == ticket_sha

    assert manager.cache_summaries(analysis_keys=["unknown"]) == []


def test_cache_summaries_include_deferred(project_root: Path) -> None:
    results_root = project_root / "results"
    now = datetime.now(timezone.utc).isoformat()
    record = CacheRecord(
        analysis="custom",
        ticket_sha256="abc123",
        stored_at=now,
        dependency_keys=["vsp_model"],
        receipt={
            "artifact_dir": "custom/run",
            "run_manifest": {
                "tool_versions": {},
                "inputs_sha256": "abc123",
                "started_utc": now,
                "ended_utc": now,
                "source_paths": [],
            },
        },
        receipt_model="custom.Model",
    )
    save_cache_records(results_root, [record])

    manager = AnalysisManager(vsp=object(), results_root=results_root, auto_init_vsp=False, open_gui=False)
    summaries = manager.cache_summaries(include_deferred=True)
    assert any(item["status"] == "deferred" and item["ticket_sha"] == "abc123" for item in summaries)
    assert all(item["status"] != "deferred" for item in manager.cache_summaries(include_deferred=False))
