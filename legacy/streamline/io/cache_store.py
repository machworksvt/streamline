from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.logging import get_logger


_CACHE_DIRNAME = "_cache"
_CACHE_FILENAME = "cache_index.json"


def _cache_index_path(results_root: Path) -> Path:
    return results_root / _CACHE_DIRNAME / _CACHE_FILENAME


@dataclass
class CacheRecord:
    analysis: str
    ticket_sha256: str
    stored_at: str
    dependency_keys: List[str] = field(default_factory=list)
    receipt: Dict[str, Any] = field(default_factory=dict)
    receipt_model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis": self.analysis,
            "ticket_sha256": self.ticket_sha256,
            "stored_at": self.stored_at,
            "dependency_keys": list(self.dependency_keys),
            "receipt": self.receipt,
            "receipt_model": self.receipt_model,
        }


def load_cache_records(results_root: Path) -> List[CacheRecord]:
    logger = get_logger(__name__, results_root=str(results_root))
    path = _cache_index_path(results_root)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read cache index", hint=str(exc))
        return []

    raw_entries = data.get("entries") or []
    records: List[CacheRecord] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        analysis = raw.get("analysis")
        ticket_sha = raw.get("ticket_sha256")
        if not analysis or not ticket_sha:
            continue
        stored_at = raw.get("stored_at") or ""
        dependency_keys = raw.get("dependency_keys") or []
        if not isinstance(dependency_keys, list):
            dependency_keys = list(dependency_keys)
        receipt = raw.get("receipt") or {}
        if not isinstance(receipt, dict):
            logger.debug(
                "Skipping cache record with invalid receipt payload",
                context={"analysis": analysis, "ticket_sha": ticket_sha},
            )
            continue
        records.append(
            CacheRecord(
                analysis=analysis,
                ticket_sha256=str(ticket_sha),
                stored_at=str(stored_at),
                dependency_keys=[str(dep) for dep in dependency_keys if dep],
                receipt=receipt,
                receipt_model=raw.get("receipt_model"),
            )
        )
    return records


def save_cache_records(results_root: Path, records: Iterable[CacheRecord]) -> None:
    path = _cache_index_path(results_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": [record.to_dict() for record in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
