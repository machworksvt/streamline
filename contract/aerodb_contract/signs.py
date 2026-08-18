"""Round-trip sign fixtures (Master Plan §8.6): the sign statements of conventions.md as data.

Asserted by streamline at export and by the consumer at ingest. A fixture failing at export is a
hinge/gain/frame problem in the geometry or the exporter and is fixed THERE; a fixture failing at
ingest against a released artifact means the two sides do not share this file, which is the exact
situation the pin exists to make impossible.

Frame facts (lift is −Z, TE-down elevator is nose-down, damping is negative) are not waivable.
Static-stability signs (Cm_α, Cn_β, Cl_β) are properties of a design and are waivable by name in
the campaign definition — silently passing a positive Cn_β would hide a frame error, so the waiver
has to be explicit and it shows in the artifact as `waived`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .load import AeroDB

SIGNS_VERSION = 1


@dataclass(frozen=True)
class SignFixture:
    name: str
    kind: str          # d_alpha | d_beta | rate | control | control_sum | static
    coef: str
    sign: int          # +1 or -1
    arg: object = None  # rate name / surface / tuple of surfaces / (alpha_rad) for static
    doc: str = ""
    waivable: bool = False


FIXTURES: tuple[SignFixture, ...] = (
    SignFixture("lift_up_is_negative_CZ", "d_alpha", "CZ", -1, doc="∂CZ/∂α < 0: lift up is −Z"),
    SignFixture("drag_is_negative_CX", "static", "CX", -1, arg=0.0, doc="CX < 0 at α = 0: drag points aft"),
    SignFixture("sideforce_opposes_sideslip", "d_beta", "CY", -1, doc="∂CY/∂β < 0"),
    SignFixture("weathercock", "d_beta", "Cn", +1, doc="∂Cn/∂β > 0 (directional stability)", waivable=True),
    SignFixture("dihedral_effect", "d_beta", "Cl", -1, doc="∂Cl/∂β < 0", waivable=True),
    SignFixture("static_longitudinal_stability", "d_alpha", "Cm", -1, doc="∂Cm/∂α < 0", waivable=True),
    SignFixture("roll_damping", "rate", "Cl", -1, arg="p_hat", doc="∂Cl/∂p̂ < 0"),
    SignFixture("pitch_damping", "rate", "Cm", -1, arg="q_hat", doc="∂Cm/∂q̂ < 0"),
    SignFixture("yaw_damping", "rate", "Cn", -1, arg="r_hat", doc="∂Cn/∂r̂ < 0"),
    SignFixture("stabilator_te_down_is_nose_down", "control", "Cm", -1, arg="stabilator", doc="∂Cm/∂δ_stab < 0"),
    SignFixture("stabilator_te_down_lifts", "control", "CZ", -1, arg="stabilator", doc="∂CZ/∂δ_stab < 0 (tail lift up)"),
    SignFixture("ruddervators_together_are_an_elevator", "control_sum", "Cm", -1,
                arg=("ruddervator_left", "ruddervator_right"), doc="Σ ∂Cm/∂δ_rv < 0"),
    SignFixture("left_aileron_te_down_rolls_right", "control", "Cl", +1, arg="aileron_left", doc="∂Cl/∂δ_aL > 0"),
    SignFixture("right_aileron_te_down_rolls_left", "control", "Cl", -1, arg="aileron_right", doc="∂Cl/∂δ_aR < 0"),
    SignFixture("ailerons_lift_when_te_down", "control_sum", "CZ", -1,
                arg=("aileron_left", "aileron_right"), doc="Σ ∂CZ/∂δ_a < 0"),
)


@dataclass(frozen=True)
class SignResult:
    name: str
    status: str   # pass | fail | waived
    value: float
    doc: str

    def as_row(self) -> dict:
        return {"check": f"sign:{self.name}", "status": self.status, "detail": f"{self.doc}: {self.value:+.4g}"}


def reference_condition(adb: AeroDB) -> tuple[int, int, int, int]:
    """Indices (flap, V, beta, alpha) of the condition fixtures are evaluated at: flap 0 (first
    detent), the middle airspeed, β nearest 0, α nearest 0."""
    ia = int(np.argmin(np.abs(adb.alpha)))
    ib = int(np.argmin(np.abs(adb.beta)))
    iv = adb.airspeed.size // 2
    return 0, iv, ib, ia


def _central(table: np.ndarray, axis_vals: np.ndarray, idx: list[int], axis_pos: int) -> float:
    """Central (or one-sided at the ends) finite difference of a table along one axis."""
    n = axis_vals.size
    i = idx[axis_pos]
    lo, hi = max(i - 1, 0), min(i + 1, n - 1)
    if lo == hi:
        raise ValueError("axis has one point; no derivative")
    a, b = list(idx), list(idx)
    a[axis_pos], b[axis_pos] = lo, hi
    return float((table[tuple(b)] - table[tuple(a)]) / (axis_vals[hi] - axis_vals[lo]))


def evaluate_fixture(adb: AeroDB, fx: SignFixture) -> float:
    fi, vi, bi, ai = reference_condition(adb)
    idx = [fi, vi, bi, ai]
    if fx.kind == "d_alpha":
        return _central(adb.base[fx.coef], adb.alpha, idx, 3)
    if fx.kind == "d_beta":
        return _central(adb.base[fx.coef], adb.beta, idx, 2)
    if fx.kind == "rate":
        return float(adb.rate[fx.arg][fx.coef][tuple(idx)])
    if fx.kind == "control":
        return float(adb.control[fx.arg][fx.coef][tuple(idx)])
    if fx.kind == "control_sum":
        return float(sum(adb.control[s][fx.coef][tuple(idx)] for s in fx.arg))
    if fx.kind == "static":
        # nearest grid α to the requested one, β = 0
        j = int(np.argmin(np.abs(adb.alpha - float(fx.arg))))
        idx[3] = j
        return float(adb.base[fx.coef][tuple(idx)])
    raise ValueError(fx.kind)  # pragma: no cover


def check_signs(adb: AeroDB, *, waivers: tuple[str, ...] = ()) -> list[SignResult]:
    out = []
    for fx in FIXTURES:
        v = evaluate_fixture(adb, fx)
        ok = (v > 0) if fx.sign > 0 else (v < 0)
        if ok:
            status = "pass"
        elif fx.waivable and fx.name in waivers:
            status = "waived"
        else:
            status = "fail"
        out.append(SignResult(fx.name, status, v, fx.doc))
    return out


def failures(results: list[SignResult]) -> list[SignResult]:
    return [r for r in results if r.status == "fail"]
