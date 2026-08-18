"""Analytic backend for ALL rate-derivative tables: strip theory for roll, tail volumes for
pitch and yaw.

VSPAERO cannot produce any usable rate derivative on this pin, each for its own measured reason
(see vsp/rates.py for the full evidence chain):

* steady rate columns — Vinf-contaminated (root cause in vspaero.C);
* unsteady P analysis — NaN on thin-surface models;
* unsteady Q/R analyses — the oscillating-body response of surfaces at a LEVER ARM comes out
  wrong-phased: measured on a textbook wing+tail (tail 2.6 c̄ aft), adding the tail made
  Cm_(q+α̇) WEAKER (−2.84 → −1.95) where classical physics adds ≈ −8. On icarus-B that produced
  Cm_q = +1.05 (unphysical, gate-blocked) with a plausible-looking CZ_q — the worst kind of
  wrong. The wing-alone case reproduces thin-wing theory, which is how the defect slipped past
  the original calibration fixtures.

The tail-dominated q̂/r̂ derivatives have well-conditioned textbook forms (Etkin/Nelson tail
volumes) whose inputs — areas, arms, slopes, projections — are explicit in the campaign and
auditable against the geometry. The artifact says so: `per_table_source` marks every rate table
analytic, `confidence: low`. This is the §8.5 multi-fidelity story doing its job on day one — a
table whose source is a formula is honest in a way a wrong-phased solver output never is.

Formulas (Etkin/Nelson, per unit p̂ = pb/2V, TE-down/right-hand conventions as the contract):

* `Cl_p = −(CL_α/12)·(1+3λ)/(1+λ)` — strip theory over a linearly-tapered wing, with the 3-D
  lift-curve slope standing in for the section slope (the standard finite-wing correction).
  Rectangular (λ=1) → −CL_α/6; the placeholder deck's invented −0.45 sat in the same decade.
* `Cn_p = −CL/8` — the lift-vector tilt on the down-going wing; evaluated per grid point from the
  local CL, so the column keeps its α and flap dependence.
* `CY_p = 0` — wing contribution negligible; the fin term is small at this geometry and omitted
  rather than invented. Recorded in `validity.notes`.
* `CX_p = CZ_p = Cm_p = 0` by lateral/longitudinal symmetry.

All of it is per-radian-equivalent (p̂ is dimensionless), Vinf-invariant by construction, and
flagged `confidence: low` pending AVL cross-check (v1) and flight sys-ID (§8.10).
"""

from __future__ import annotations

import numpy as np

SOURCE_ID = "analytic-strip-theory"


def cl_p(cl_alpha_per_rad: float, taper_ratio: float) -> float:
    """Roll damping per unit p̂, strip theory over a linearly tapered wing."""
    if not 0.0 < taper_ratio <= 1.5:
        raise ValueError(f"taper ratio {taper_ratio} is not a planform")
    if not 1.0 <= cl_alpha_per_rad <= 8.0:
        raise ValueError(f"CL_alpha {cl_alpha_per_rad} /rad is outside any plausible wing")
    lam = taper_ratio
    return -(cl_alpha_per_rad / 12.0) * (1.0 + 3.0 * lam) / (1.0 + lam)


def cn_p(cl_local: float) -> float:
    """Yaw-from-roll-rate cross derivative from the lift-vector tilt."""
    return -cl_local / 8.0


def p_hat_column(cl_alpha_per_rad: float, taper_ratio: float, cl_grid: np.ndarray) -> dict:
    """The six-coefficient p̂ tables. `cl_grid` is CL per grid point (any shape); `Cl` is constant,
    `Cn` varies with the local CL, the rest are identically zero."""
    cl_grid = np.asarray(cl_grid, dtype=float)
    zeros = np.zeros_like(cl_grid)
    return {
        "CX": zeros, "CY": zeros, "CZ": zeros,
        "Cl": np.full_like(cl_grid, cl_p(cl_alpha_per_rad, taper_ratio)),
        "Cm": zeros,
        "Cn": cn_p(cl_grid),
    }


SOURCE_ID_TAIL = "analytic-tail-volume"

#: campaign `analytic_rates` schema, validated in campaign.definition:
#:   horizontal_tails / vertical_tails: [{name, S_m2, arm_m, a_per_rad, eta}], arm_m measured
#:   from the MOMENT REFERENCE to the surface aerodynamic centre, positive aft; projections
#:   (e.g. a V-tail's cos²Γ / sin²Γ split) are baked into S_m2 by the campaign author and
#:   documented there. depsilon_dalpha: wing downwash gradient at the horizontal tail.


def _tail_sum(tails: list, ref_area_m2: float, ref_len_m: float, power: int) -> float:
    """Σ η·a·(S/S_ref)·(arm/ref_len)^power over tail entries."""
    total = 0.0
    for t in tails:
        total += float(t["eta"]) * float(t["a_per_rad"]) * (float(t["S_m2"]) / ref_area_m2) \
                 * (float(t["arm_m"]) / ref_len_m) ** power
    return total


def q_hat_column(spec: dict, ref_area_m2: float, cbar_m: float, grid_shape) -> dict:
    """The combined (q̂ + α̇) tables from horizontal-tail volumes (Etkin/Nelson):

        CZ_q+α̇ = −2·Σ η·a_t·(S_t/S)·(l_t/c̄)      · (1 + dε/dα)
        Cm_q+α̇ = −2·Σ η·a_t·(S_t/S)·(l_t/c̄)²     · (1 + dε/dα)

    Wing contributions (small at a near-AC reference) are omitted, not invented — recorded in
    validity.notes; the estimate understates pitch damping by O(10%), the conservative side for
    damping-critical design."""
    de_da = float(spec["depsilon_dalpha"])
    hs = spec["horizontal_tails"]
    zeros = np.zeros(grid_shape)
    czq = -2.0 * _tail_sum(hs, ref_area_m2, cbar_m, 1) * (1.0 + de_da)
    cmq = -2.0 * _tail_sum(hs, ref_area_m2, cbar_m, 2) * (1.0 + de_da)
    return {"CX": zeros, "CY": zeros, "CZ": np.full(grid_shape, czq),
            "Cl": zeros, "Cm": np.full(grid_shape, cmq), "Cn": zeros}


def r_hat_column(spec: dict, ref_area_m2: float, span_m: float, cl_grid: np.ndarray) -> dict:
    """The r̂ tables from vertical-tail volumes plus the classical wing term:

        CY_r = +2·Σ η·a_v·(S_v/S)·(l_v/b)
        Cn_r = −2·Σ η·a_v·(S_v/S)·(l_v/b)²
        Cl_r = +CL/4                       (wing lift-vector tilt, per grid point)

    Sidewash and the fin z-arm roll coupling are omitted, not invented (validity.notes)."""
    vs = spec["vertical_tails"]
    cl_grid = np.asarray(cl_grid, dtype=float)
    zeros = np.zeros_like(cl_grid)
    cyr = +2.0 * _tail_sum(vs, ref_area_m2, span_m, 1)
    cnr = -2.0 * _tail_sum(vs, ref_area_m2, span_m, 2)
    return {"CX": zeros, "CY": np.full_like(cl_grid, cyr), "CZ": zeros,
            "Cl": cl_grid / 4.0, "Cm": zeros, "Cn": np.full_like(cl_grid, cnr)}
