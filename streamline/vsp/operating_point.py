from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..core.schema import OperatingPoint


@dataclass
class AppliedOperatingPoint:
    op_id: Optional[str]
    altitude_m: Optional[float]
    mach: Optional[float]
    tas_mps: Optional[float]
    mass_override_kg: Optional[float]
    atmosphere_overrides: Dict[str, float]
    notes: str

    def to_summary(self) -> Dict[str, Any]:
        return {
            "op_id": self.op_id,
            "altitude_m": self.altitude_m,
            "mach": self.mach,
            "tas_mps": self.tas_mps,
            "mass_override_kg": self.mass_override_kg,
            "notes": self.notes,
        }


def apply_operating_point(op: OperatingPoint) -> AppliedOperatingPoint:
    return AppliedOperatingPoint(
        op_id=op.op_name,
        altitude_m=op.altitude_m,
        mach=op.mach,
        tas_mps=op.tas_mps,
        mass_override_kg=op.mass_override_kg,
        atmosphere_overrides=dict(op.atmosphere_overrides or {}),
        notes=op.notes,
    )
