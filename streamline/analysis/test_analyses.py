from __future__ import annotations

import time
from typing import Optional

from ..vsp.contracts.base import Receipt, Ticket
from .manager import AnalysisManager


class NoopTicket(Ticket):
    label: str = "noop"
    duration_s: float = 0.0


class NoopReceipt(Receipt):
    label: str
    duration_s: float
    note: Optional[str] = None


def run_noop(vsp, ticket: NoopTicket):  # vsp ignored
    start = time.time()
    if ticket.duration_s > 0:
        time.sleep(min(ticket.duration_s, 5.0))
    elapsed = time.time() - start
    return NoopReceipt(
        label=ticket.label,
        duration_s=elapsed,
        artifact_dir=None,
        run_manifest=None,
    )


def register_test_analyses(manager: AnalysisManager) -> None:
    """Register lightweight test analyses for TUI job testing."""
    try:
        manager.register_analysis(
            "test_noop",
            run_noop,
            materializer=None,
            default_dependency_keys={"test"},
            receipt_model=NoopReceipt,
            description="No-op test analysis (sleep)",
            uses_vsp_lock=False,
        )
    except Exception:
        pass
