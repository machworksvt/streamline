"""The one VSPAERO→FRD rotation, and the coefficient bookkeeping that depends on it.

OpenVSP/VSPAERO model axes: X aft, Y right, Z up. Body FRD: X forward, Y right, Z down. The
proper rotation between them is `R = diag(-1, +1, -1)` (det +1 — a 180° turn about Y, not a
reflection), and it is applied to positions, force coefficients and moment coefficients alike.
Nothing downstream ever sees the VSP frame (contract conventions.md §1).

VSPAERO's own `CMl, CMm, CMn` are its "aircraft" roll/pitch/yaw moments and happen to equal
`(-CMx, CMy, -CMz)` at the small angles probed so far, but this module rotates the body-axis set
`(CFx, CFy, CFz, CMx, CMy, CMz)` explicitly and never relies on that coincidence.
"""

from __future__ import annotations

import numpy as np

R_VSP_TO_FRD = np.diag([-1.0, 1.0, -1.0])

#: VSPAERO body-axis result keys, in the order that maps onto the contract's coefficient names.
VSP_FORCE_KEYS = ("CFx", "CFy", "CFz")
VSP_MOMENT_KEYS = ("CMx", "CMy", "CMz")
FRD_FORCE = ("CX", "CY", "CZ")
FRD_MOMENT = ("Cl", "Cm", "Cn")


def vsp_to_frd(v) -> np.ndarray:
    """Rotate a position, force or moment vector from VSP model axes into FRD."""
    return R_VSP_TO_FRD @ np.asarray(v, dtype=float)


def coefficients_to_frd(vsp: dict) -> dict:
    """Map a dict holding VSPAERO body-axis keys (CFx..CMz) onto the six contract coefficients."""
    f = vsp_to_frd([vsp["CFx"], vsp["CFy"], vsp["CFz"]])
    m = vsp_to_frd([vsp["CMx"], vsp["CMy"], vsp["CMz"]])
    return {"CX": float(f[0]), "CY": float(f[1]), "CZ": float(f[2]),
            "Cl": float(m[0]), "Cm": float(m[1]), "Cn": float(m[2])}


def frd_to_vsp(v) -> np.ndarray:
    """R is its own inverse."""
    return R_VSP_TO_FRD @ np.asarray(v, dtype=float)
