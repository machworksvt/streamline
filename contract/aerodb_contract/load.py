"""Loaders and a numpy reference evaluator.

`AeroDB.evaluate` is multilinear interpolation over the four axes plus the linear rate/control
terms — the contract's own definition of what the tables MEAN, in a form the lint, the sign
fixtures, the report and any consumer's ingest test can compare against. It is deliberately not
fast and not smooth; a consumer builds its own (bspline) interpolants and checks them against this.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from . import canonical_json, conventions as cv, schema


# --- multilinear interpolation on a regular (non-uniform) grid ---------------------------------

def _bracket(axis: np.ndarray, x: float) -> tuple[int, float]:
    """Index i and weight t such that x ≈ axis[i]*(1-t) + axis[i+1]*t, clamped to the ends
    (no extrapolation — a table is only knowable where it was solved)."""
    n = axis.size
    if n == 1:
        return 0, 0.0
    if x <= axis[0]:
        return 0, 0.0
    if x >= axis[-1]:
        return n - 2, 1.0
    i = int(np.searchsorted(axis, x, side="right") - 1)
    i = min(max(i, 0), n - 2)
    t = (x - axis[i]) / (axis[i + 1] - axis[i])
    return i, float(t)


def multilinear(axes: tuple[np.ndarray, ...], table: np.ndarray, point: tuple[float, ...]) -> float:
    """Multilinear interpolation of `table` (shape = lens of axes) at `point`, clamped."""
    assert table.ndim == len(axes) == len(point)
    idx_w = [_bracket(a, float(x)) for a, x in zip(axes, point)]
    val = 0.0
    n = len(axes)
    for corner in range(1 << n):
        w = 1.0
        idx = []
        for d in range(n):
            i, t = idx_w[d]
            hi = (corner >> d) & 1
            if axes[d].size == 1:
                if hi:
                    w = 0.0
                    break
                idx.append(0)
                continue
            w *= t if hi else (1.0 - t)
            idx.append(i + hi)
        if w:
            val += w * float(table[tuple(idx)])
    return val


# --- the artifact --------------------------------------------------------------------------------

@dataclass(frozen=True)
class AeroDB:
    doc: dict
    alpha: np.ndarray
    beta: np.ndarray
    airspeed: np.ndarray
    flap: np.ndarray
    base: dict[str, np.ndarray]                    # coef -> table
    rate: dict[str, dict[str, np.ndarray]]         # rate -> coef -> table
    control: dict[str, dict[str, np.ndarray]]      # surface -> coef -> table

    @property
    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return (self.flap, self.airspeed, self.beta, self.alpha)

    @property
    def reference(self) -> dict:
        return self.doc["reference"]

    def _at(self, table: np.ndarray, alpha: float, beta: float, V: float, flap: float) -> float:
        return multilinear(self.axes, table, (flap, V, beta, alpha))

    def evaluate(self, *, alpha: float, beta: float, V: float, flap: float = 0.0,
                 rates: Mapping[str, float] | None = None,
                 deltas: Mapping[str, float] | None = None) -> dict[str, float]:
        """The composition in conventions.md, evaluated with multilinear tables. `rates` keys are
        p_hat/q_hat/r_hat (non-dimensional); `deltas` keys are control-surface names, radians."""
        rates = dict(rates or {})
        deltas = dict(deltas or {})
        for s in deltas:
            if s not in self.control:
                raise KeyError(f"{s!r} is not a control surface with a derivative table"
                               + (" (flaps enter via the axis)" if s.startswith("flap") else ""))
        out = {}
        for c in cv.COEFFICIENTS:
            v = self._at(self.base[c], alpha, beta, V, flap)
            for r, rv in rates.items():
                v += self._at(self.rate[r][c], alpha, beta, V, flap) * rv
            for s, d in deltas.items():
                v += self._at(self.control[s][c], alpha, beta, V, flap) * d
            out[c] = v
        return out

    def lift_drag(self, coefs: Mapping[str, float], alpha: float, beta: float = 0.0) -> tuple[float, float]:
        """Wind-axis lift and drag from body-axis coefficients (β=0 formulae are exact; with β the
        drag is along the air-relative velocity)."""
        ca, sa, cb, sb = np.cos(alpha), np.sin(alpha), np.cos(beta), np.sin(beta)
        cx, cy, cz = coefs["CX"], coefs["CY"], coefs["CZ"]
        cl = -cz * ca + cx * sa
        cd = -(cx * ca * cb + cy * sb + cz * sa * cb)
        return float(cl), float(cd)

    @classmethod
    def from_doc(cls, doc: dict) -> "AeroDB":
        schema.check(doc, "aerodb")
        ax = doc["axes"]
        t = doc["tables"]
        arr = lambda x: np.asarray(x, dtype=float)
        return cls(
            doc=doc,
            alpha=arr(ax["alpha_rad"]), beta=arr(ax["beta_rad"]),
            airspeed=arr(ax["airspeed_m_s"]), flap=arr(ax["flap_rad"]),
            base={c: arr(t["base"][c]) for c in cv.COEFFICIENTS},
            rate={r: {c: arr(t["rate"][r][c]) for c in cv.COEFFICIENTS} for r in cv.RATES},
            control={s: {c: arr(t["control"][s][c]) for c in cv.COEFFICIENTS} for s in cv.CONTROL_SURFACES},
        )

    @classmethod
    def from_json(cls, path: Path | str) -> "AeroDB":
        return cls.from_doc(canonical_json.read(path))


@dataclass(frozen=True)
class MassProps:
    doc: dict
    mass_kg: float
    cg_m: np.ndarray
    inertia_kg_m2: np.ndarray

    @classmethod
    def from_doc(cls, doc: dict) -> "MassProps":
        schema.check(doc, "massprops")
        return cls(doc=doc, mass_kg=float(doc["mass_kg"]), cg_m=np.asarray(doc["cg_m"], float),
                   inertia_kg_m2=np.asarray(doc["inertia_kg_m2"], float))

    @classmethod
    def from_json(cls, path: Path | str) -> "MassProps":
        return cls.from_doc(canonical_json.read(path))


@dataclass(frozen=True)
class EngineDeck:
    doc: dict
    setting: np.ndarray
    thrust_N: np.ndarray
    fuel_flow_kg_s: np.ndarray | None = None

    def thrust(self, setting: float) -> float:
        return float(np.interp(setting, self.setting, self.thrust_N))

    def fuel_flow(self, setting: float) -> float:
        """kg/s at a setting; raises if the deck carries no fuel-flow column."""
        if self.fuel_flow_kg_s is None:
            raise KeyError("engine deck has no static.fuel_flow_kg_s")
        return float(np.interp(setting, self.setting, self.fuel_flow_kg_s))

    @property
    def spool_time_constants_s(self) -> tuple[float, float] | None:
        """(τ_up, τ_down) if the deck carries dynamics parameters, else None. The consumer's
        first-order lag uses these; the deck records how they were obtained in dynamics.spool_fit."""
        d = self.doc.get("dynamics") or {}
        if "spool_up_time_constant_s" in d and "spool_down_time_constant_s" in d:
            return float(d["spool_up_time_constant_s"]), float(d["spool_down_time_constant_s"])
        return None

    @classmethod
    def from_doc(cls, doc: dict) -> "EngineDeck":
        schema.check(doc, "engine_deck")
        ff = doc["static"].get("fuel_flow_kg_s")
        return cls(doc=doc, setting=np.asarray(doc["static"]["setting"], float),
                   thrust_N=np.asarray(doc["static"]["thrust_N"], float),
                   fuel_flow_kg_s=None if ff is None else np.asarray(ff, float))

    @classmethod
    def from_json(cls, path: Path | str) -> "EngineDeck":
        return cls.from_doc(canonical_json.read(path))


def transfer_moment(moment_ref: np.ndarray, force: np.ndarray, r_ref: np.ndarray, r_cg: np.ndarray) -> np.ndarray:
    """M_cg = M_ref + (r_ref − r_cg) × F — the consumer's obligation, written once."""
    return np.asarray(moment_ref, float) + np.cross(np.asarray(r_ref, float) - np.asarray(r_cg, float),
                                                    np.asarray(force, float))
