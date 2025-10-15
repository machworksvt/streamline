from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.errors import OperatingPointCatalogError
from ..core.logging import get_logger
from ..core.schema import OperatingPoint
from .fs import load_op, load_project_def, write_json


@dataclass
class OperatingPointSummary:
    op_id: str
    path: Path
    altitude_m: float
    mach: Optional[float]
    tas_mps: Optional[float]
    signature: str
    checksum: Optional[str]
    captured_at: Optional[str]
    metadata_path: Optional[Path]
    notes: str


def _op_metadata_path(op_path: Path) -> Path:
    return op_path.with_suffix(op_path.suffix + ".meta")


def load_operating_point_metadata(op_path: Path) -> Dict[str, Any]:
    meta_path = _op_metadata_path(op_path)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_operating_point_json(project_root: Path, op: OperatingPoint, *, captured_at: Optional[datetime] = None) -> Path:
    ops_dir = project_root / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)
    path = ops_dir / f"{op.op_name}.json"
    payload = json.loads(op.model_dump_json(exclude_none=True))
    write_json(payload, path)
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    metadata = {
        "metadata_version": 1,
        "op_id": op.op_name,
        "captured_at": (captured_at or datetime.now(timezone.utc)).isoformat(),
        "checksum_sha256": checksum,
    }
    write_json(metadata, _op_metadata_path(path))
    return path


def load_op_catalog(project_root: Path) -> List[OperatingPointSummary]:
    logger = get_logger(__name__, project=str(project_root))
    project = load_project_def(project_root)
    summaries: List[OperatingPointSummary] = []
    seen: Dict[str, Path] = {}
    for rel_path in project.references.get("ops", []):
        op_path = project_root / rel_path
        try:
            op = load_op(op_path)
        except Exception as exc:
            err = OperatingPointCatalogError(
                f"Failed to load operating point '{rel_path}': {exc}",
                context={"op_path": str(op_path)},
            )
            logger.error(err.message, context=err.context, code=err.code)
            raise err from exc
        if op.op_name in seen:
            err = OperatingPointCatalogError(
                f"Duplicate operating point id '{op.op_name}' in catalog",
                context={
                    "op_id": op.op_name,
                    "path": str(op_path),
                    "other_path": str(seen[op.op_name]),
                },
            )
            logger.error(err.message, context=err.context, code=err.code)
            raise err
        seen[op.op_name] = op_path
        metadata = load_operating_point_metadata(op_path)
        checksum = metadata.get("checksum_sha256")
        captured_at = metadata.get("captured_at")
        meta_path = _op_metadata_path(op_path)
        metadata_path = meta_path if meta_path.exists() else None
        try:
            stat = op_path.stat()
            signature = f"{int(stat.st_mtime_ns)}:{stat.st_size}"
        except FileNotFoundError:
            signature = "missing"
        summaries.append(
            OperatingPointSummary(
                op_id=op.op_name,
                path=op_path,
                altitude_m=op.altitude_m,
                mach=op.mach,
                tas_mps=op.tas_mps,
                signature=signature,
                checksum=checksum,
                captured_at=captured_at,
                metadata_path=metadata_path,
                notes=op.notes,
            )
        )
    return summaries


def get_operating_point(project_root: Path, op_id: str) -> OperatingPoint:
    catalog = load_op_catalog(project_root)
    for summary in catalog:
        if summary.op_id == op_id:
            return load_op(summary.path)
    available = ", ".join(op.op_id for op in catalog)
    err = OperatingPointCatalogError(
        f"Operating point '{op_id}' not found",
        context={"op_id": op_id, "project": str(project_root), "available": available},
        hint="Check the ops/ directory for the expected JSON file.",
    )
    get_logger(__name__).error(err.message, context=err.context, code=err.code, hint=err.hint)
    raise err
