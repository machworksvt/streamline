"""Physics lint (Master Plan §8.6): automated invariants on the tables, run at every export.

The list is data; results are embedded in the artifact's `lint` block so a reader of the file
knows what was checked and what it said. `fail` blocks a release; `warn` ships as a flag. The bands
below are deliberately wide — they catch a per-degree slope (÷57), a dimensional rate (×V), a
missing reference area (×200), a wrong frame (sign) — not design quality.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import completeness as comp, conventions as cv, signs as sg
from .load import AeroDB

LINT_VERSION = 1


@dataclass(frozen=True)
class Check:
    name: str
    severity: str    # fail | warn
    doc: str
    fn: Callable[[AeroDB], tuple[bool, str]]


def _lift_curve(adb: AeroDB) -> tuple[np.ndarray, np.ndarray]:
    """CL(α) at β=0, flap 0, middle V — from body axes."""
    fi, vi, bi, _ = sg.reference_condition(adb)
    cx = adb.base["CX"][fi, vi, bi, :]
    cz = adb.base["CZ"][fi, vi, bi, :]
    cl = -cz * np.cos(adb.alpha) + cx * np.sin(adb.alpha)
    return adb.alpha, cl


def _linear_range(adb: AeroDB) -> np.ndarray:
    lo, hi = adb.doc["validity"]["alpha_rad"]
    return (adb.alpha >= lo) & (adb.alpha <= hi)


def c_finite(adb):
    for grp in (adb.base, *adb.rate.values(), *adb.control.values()):
        for c, t in grp.items():
            if not np.all(np.isfinite(t)):
                return False, f"non-finite entries in {c}"
    return True, "all tables finite"


def c_symmetry_beta0(adb):
    bi = int(np.argmin(np.abs(adb.beta)))
    if abs(adb.beta[bi]) > 1e-9:
        return True, "no β=0 breakpoint; skipped"
    worst = 0.0
    for c in cv.LATERAL:
        worst = max(worst, float(np.abs(adb.base[c][:, :, bi, :]).max()))
    return worst < 2e-3, f"max |CY,Cl,Cn| at β=0 is {worst:.2e} (limit 2e-3)"


def c_lr_mirror(adb):
    """Left/right mirror symmetry, stated correctly: the mirror image of the LEFT surface at
    sideslip β is the RIGHT surface at −β. So the comparison flips the β axis; at β ≠ 0 the two
    sides see genuinely different local flow and a pointwise compare would report physics as a
    defect (measured: 13% on a ruddervator CX at β = ±5°). Requires a β grid symmetric about 0 —
    otherwise only the β ≈ 0 slice is compared."""
    beta_symmetric = bool(np.allclose(adb.beta, -adb.beta[::-1], atol=1e-12))
    bi0 = int(np.argmin(np.abs(adb.beta)))
    worst, where = 0.0, ""
    for l, r in cv.MIRROR_PAIRS:
        # One scale per PAIR — its dominant derivative. Judging each coefficient against its own
        # magnitude fails physics-free residue: a VLM at finite GMRES convergence leaves ~1e-3
        # absolute on near-zero coefficients (measured 14% "mismatch" on a ruddervator CX of
        # 0.011 while its CZ of 0.7 matched to 0.2%). A flipped MEANINGFUL coefficient still
        # misses by ~2x the dominant scale; small coefficients' signs are the sign fixtures' job.
        pair_scale = max(1e-2, max(float(np.abs(adb.control[l][c]).max()) for c in cv.COEFFICIENTS))
        for c in cv.COEFFICIENTS:
            a = adb.control[l][c]
            b_full = adb.control[r][c]
            if beta_symmetric:
                b = np.flip(b_full, axis=2)
            else:
                a = a[:, :, bi0:bi0 + 1, :]
                b = b_full[:, :, bi0:bi0 + 1, :]
            d = np.abs(a - b) if c in cv.LONGITUDINAL else np.abs(a + b)
            frac = float(d.max() / pair_scale)
            if frac > worst:
                worst, where = frac, f"{l}/{r} {c} (pair scale {pair_scale:.4f})"
    return worst < 0.05, f"worst L/R mirror mismatch {worst:.1%} at {where} (limit 5%)"


def c_cl_alpha_band(adb):
    a, cl = _lift_curve(adb)
    m = _linear_range(adb)
    if m.sum() < 2:
        return False, "fewer than two α points inside validity"
    slope = float(np.polyfit(a[m], cl[m], 1)[0])
    return 3.0 <= slope <= 7.0, f"CL_α = {slope:.2f} /rad in the linear range (band 3–7)"


def c_cl_monotone(adb):
    a, cl = _lift_curve(adb)
    m = _linear_range(adb)
    d = np.diff(cl[m])
    return bool(np.all(d > 0)), f"CL(α) monotone in the linear range: {np.all(d > 0)}"


def c_cm_q_band(adb):
    fi, vi, bi, ai = sg.reference_condition(adb)
    v = float(adb.rate["q_hat"]["Cm"][fi, vi, bi, ai])
    return -60.0 <= v <= -2.0, f"Cm_q = {v:.2f} per unit q̂ (band −60…−2; a dimensional rate or a wrong c̄ lands outside)"


def c_static_margin_band(adb):
    fi, vi, bi, ai = sg.reference_condition(adb)
    idx = [fi, vi, bi, ai]
    cm_a = sg._central(adb.base["Cm"], adb.alpha, idx, 3)
    a, cl = _lift_curve(adb)
    m = _linear_range(adb)
    cl_a = float(np.polyfit(a[m], cl[m], 1)[0])
    sm = -cm_a / cl_a
    return 0.02 <= sm <= 0.40, f"static margin −Cm_α/CL_α = {sm:.3f} about the reference point (band 0.02–0.40)"


def c_stall_points(adb):
    n = len(adb.doc["validity"]["stall"]["points_beyond"])
    return n == 0, f"{n} grid points likely beyond stall (listed in validity.stall.points_beyond)"


def c_pinned(adb):
    up = bool(adb.doc["provenance"]["backend"]["unpinned"])
    return not up, "produced on the pinned OpenVSP" if not up else "produced on an UNPINNED OpenVSP"


def c_completeness_required(adb):
    flags = adb.doc["completeness"]["flags"]
    errs = comp.validate_flags(flags)
    if errs:
        return False, "; ".join(errs)
    blockers = comp.release_blockers(flags)
    return not blockers, ("all release-required completeness items clear" if not blockers
                          else f"release-required items not clear: {blockers}")


CHECKS: tuple[Check, ...] = (
    Check("finite", "fail", "no NaN/Inf anywhere", c_finite),
    Check("symmetry_beta0", "fail", "CY, Cl, Cn ≈ 0 at β = 0 (symmetric configuration)", c_symmetry_beta0),
    Check("lr_mirror", "fail", "left/right derivative tables mirror (longitudinal equal, lateral opposite)", c_lr_mirror),
    Check("cl_alpha_band", "fail", "CL_α within 3–7 /rad (catches per-degree and reference-area slips)", c_cl_alpha_band),
    Check("cl_monotone", "warn", "CL(α) monotone inside the validity range", c_cl_monotone),
    Check("cm_q_band", "fail", "Cm_q within −60…−2 per unit q̂ (catches dimensional rates)", c_cm_q_band),
    Check("static_margin_band", "warn", "static margin about the reference point in 0.02–0.40", c_static_margin_band),
    Check("stall_points", "warn", "grid points beyond the CL_max estimate", c_stall_points),
    Check("pinned", "fail", "produced on the pinned OpenVSP", c_pinned),
    Check("completeness_required", "fail", "release-required completeness items are clear", c_completeness_required),
)


def run_lint(adb: AeroDB, *, sign_waivers: tuple[str, ...] = ()) -> list[dict]:
    """Every check plus every sign fixture, as `lint.results` rows."""
    rows = []
    for ck in CHECKS:
        ok, detail = ck.fn(adb)
        status = "pass" if ok else ck.severity
        rows.append({"check": ck.name, "status": status, "detail": detail})
    for r in sg.check_signs(adb, waivers=sign_waivers):
        rows.append(r.as_row())
    return rows


def blocking(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["status"] == "fail"]
