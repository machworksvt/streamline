"""Code-built reference geometries with pencil-and-paper answers.

These exist to check the SOLVER WRAPPERS, not the aircraft (plan §3.1): a flat rectangular wing has
a lift-curve slope lifting-line theory can predict, so a run that comes back per-degree, or with
the reference area from a default, or in the wrong frame, fails against a number nobody had to
trust VSPAERO for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .session import Session


@dataclass(frozen=True)
class ReferenceWing:
    geom_id: str
    span_m: float
    chord_m: float

    @property
    def area_m2(self) -> float:
        return self.span_m * self.chord_m

    @property
    def aspect_ratio(self) -> float:
        return self.span_m / self.chord_m

    @property
    def cl_alpha_lifting_line(self) -> float:
        """Helmbold/lifting-line: 2π AR / (AR + 2), per radian. VSPAERO's VLM on the same planform
        lands within a few percent of this (5.04 vs 5.03 at AR 8 in the 2026-08-16 spike)."""
        ar = self.aspect_ratio
        return 2.0 * math.pi * ar / (ar + 2.0)


def flat_rectangular_wing(session: Session, *, span_m: float = 2.0, chord_m: float = 0.25) -> ReferenceWing:
    """Replace the model with one unswept, untwisted, flat rectangular wing at the origin, root
    leading edge at x = 0. Returns its ids and the numbers the checks compare against."""
    api = session.api
    api.ClearVSPModel()
    wid = api.AddGeom("WING", "")
    api.SetParmVal(wid, "TotalSpan", "WingGeom", float(span_m))
    api.SetParmVal(wid, "TotalChord", "WingGeom", float(chord_m))
    api.SetParmVal(wid, "Sweep", "XSec_1", 0.0)
    api.Update()
    return ReferenceWing(geom_id=wid, span_m=float(span_m), chord_m=float(chord_m))
