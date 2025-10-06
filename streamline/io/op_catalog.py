from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..core.errors import OperatingPointCatalogError
from ..core.logging import get_logger
from ..core.schema import OperatingPoint
from .fs import load_op, load_project_def


@dataclass
class OperatingPointSummary:
    op_id: str
    path: Path
    altitude_m: float
    mach: Optional[float]
    tas_mps: Optional[float]
    notes: str


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
        summaries.append(
            OperatingPointSummary(
                op_id=op.op_name,
                path=op_path,
                altitude_m=op.altitude_m,
                mach=op.mach,
                tas_mps=op.tas_mps,
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
