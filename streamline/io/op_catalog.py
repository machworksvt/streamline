from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

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


class OperatingPointCatalogError(RuntimeError):
    pass


def load_op_catalog(project_root: Path) -> List[OperatingPointSummary]:
    project = load_project_def(project_root)
    summaries: List[OperatingPointSummary] = []
    seen: Dict[str, Path] = {}
    for rel_path in project.references.get("ops", []):
        op_path = project_root / rel_path
        try:
            op = load_op(op_path)
        except Exception as exc:
            raise OperatingPointCatalogError(f"Failed to load operating point '{rel_path}': {exc}") from exc
        if op.op_name in seen:
            raise OperatingPointCatalogError(
                f"Duplicate operating point id '{op.op_name}' in catalog: {rel_path} and {seen[op.op_name]}"
            )
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
    raise OperatingPointCatalogError(
        f"Operating point '{op_id}' not found. Available: {available if available else 'none'}"
    )
