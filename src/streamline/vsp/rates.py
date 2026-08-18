"""Rate (damping) derivatives — QUARANTINED. Every VSPAERO rate channel on this pin is unusable
for the pipeline; ALL rate tables ship from `backends/analytic.py` and say so in
`per_table_source`. This wrapper stays for diagnostics and for the regression tests that pin the
defects, so an OpenVSP bump that fixes any of them fails a test loudly and we revisit.

The evidence, all measured on this pin (3.51.2 / VSPAERO 7.2.2):

1. STEADY stability mode `C*_p/q/r` columns: Vinf-contaminated (`CL_q` 44→301 as Vinf 15→120 on
   the AR-8 wing; fixed absolute rate step in `vspaero.C` is the cause).
2. `STABILITY_P_ANALYSIS` (roll): all-NaN for thin-surface models regardless of settings.
3. `STABILITY_Q_ANALYSIS` / `R_ANALYSIS` — the subtle one. The solver pitches/yaws the body
   sinusoidally about `X_cg` (ω = 4π/(N·dt), θ_max = 5°, N = 128 — ALL hardcoded in the
   `-qstab` CLI branch of `vspaero.C`; the API's NumTimeSteps/wake settings never reach it,
   which is why runs at wake 3/16, 5/16 and 5/64 agree to 4 decimals) and projects the response
   onto cos(ωt) over the second half. On a WING ALONE the physics comes out right (−2.84 vs
   thin-wing −2.7 after the per-axis sign below — how this passed calibration). But a surface
   at a LEVER ARM responds wrong-phased: wing + tail 2.6 c̄ aft measured Cm_(q+α̇) = −1.95
   where classical is ≈ −11 — the tail made damping WEAKER. On icarus-B: Cm_q = +1.05
   (unphysical, gate-blocked) with a plausible CZ_q = −4.6, and Cn_r at ~55% of classical.
   An independent least-squares re-extraction from the raw time histories reproduces VSPAERO's
   own numbers exactly — the defect is in the rendered response physics, not the projection.
   Reproducer: tests/test_rates.py::test_a_tail_makes_vspaero_pitch_damping_weaker_…

Public-record research (2026-08-17, docs/vspaero-unsteady-stab-research.md): the defect is NOT
known upstream (zero matching GitHub issues; an unanswered Jul 2026 forum post corroborates the
hardcoded steps and implausible numbers without diagnosing it), NOT fixed anywhere (3.51.2 is
the newest release and the defect is in the v7 rewrite that shipped in 3.45.0), and the unsteady
modes have NO published validation at all. An upstream-issue draft is appended to that memo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from . import frames, settings as settings_mod
from .geometry import Geometry
from .session import Session

#: Per-axis sign calibration for the unsteady modes' published columns (see module docstring).
SIGN = {"q_hat": -1.0, "r_hat": +1.0}

#: Result-key suffix per axis — the combined oscillatory derivative each mode measures.
SUFFIX = {"q_hat": "q+alpha_dot", "r_hat": "r-beta_dot"}

_VSP6 = ("CFx", "CFy", "CFz", "CMx", "CMy", "CMz")


@dataclass(frozen=True)
class RateColumn:
    axis: str                      # 'q_hat' | 'r_hat'
    combined: str                  # what it physically is: 'q_hat+alpha_dot' | 'r_hat-beta_dot'
    values: dict                   # coef -> derivative per unit non-dim rate, FRD, calibrated sign
    resolved_settings: dict


def unsteady_overrides(session: Session, geometry: Geometry, *, axis: str, alpha_rad: float,
                       airspeed_m_s: float, density_kg_m3: float, reynolds_cref: float, mach: float,
                       wing_id: str, moment_ref_m, ncpu: int, num_time_steps: int,
                       wake_iters: int, num_wake_nodes: int,
                       vlm_set: str = "All", extra: Mapping | None = None) -> dict:
    """The overrides for one unsteady rate run. β is 0 by construction — the oscillation supplies
    the lateral excitation for the r case.

    `wake_iters` / `num_wake_nodes` are REQUIRED: this wrapper originally left them to OpenVSP's
    defaults (5 / 64) while the campaign said 3 / 16, and nobody noticed until a real Q run spent
    ~25 minutes in wake startup (the startup length scales with the wake-node count). The exact
    silent-default failure the settings register exists to prevent — so no default here.

    `num_time_steps` is recorded but VSPAERO IGNORES it for the P/Q/R stability cases — the case
    file gets no time-step block at all (measured on 3.51.2); the solver runs its own schedule."""
    api = session.api
    mode = {"q_hat": api.STABILITY_Q_ANALYSIS, "r_hat": api.STABILITY_R_ANALYSIS}[axis]
    mref = frames.frd_to_vsp(moment_ref_m)
    deg = 180.0 / np.pi
    s = {
        "AlphaStart": alpha_rad * deg, "AlphaEnd": alpha_rad * deg, "AlphaNpts": 1,
        "BetaStart": 0.0, "BetaEnd": 0.0, "BetaNpts": 1,
        "MachStart": mach, "MachEnd": mach, "MachNpts": 1,
        "ReCref": reynolds_cref, "ReCrefEnd": reynolds_cref, "ReCrefNpts": 1,
        "Vinf": airspeed_m_s, "Rho": density_kg_m3, "Machref": max(mach, 1e-3),
        "RefFlag": 1, "WingID": wing_id,
        "Xcg": float(mref[0]), "Ycg": float(mref[1]), "Zcg": float(mref[2]),
        "GeomSet": -1, "ThinGeomSet": geometry.set_index(vlm_set),
        "UnsteadyType": int(mode),
        "NCPU": ncpu, "NumTimeSteps": num_time_steps,
        "WakeNumIter": wake_iters, "NumWakeNodes": num_wake_nodes,
    }
    if extra:
        s.update(extra)
    return s


def run_unsteady_rate(session: Session, geometry: Geometry, *, axis: str, overrides: dict) -> RateColumn:
    """One unsteady oscillatory run → the six-coefficient damping column for `axis`, FRD, per unit
    non-dimensional rate, with the calibrated sign. ComputeGeometry must already have run."""
    if axis not in SIGN:
        raise ValueError(f"axis must be one of {sorted(SIGN)} (roll is analytic — backends/analytic.py)")
    api = session.api
    full = settings_mod.complete(session, "VSPAEROSweep", overrides)
    resolved = settings_mod.resolve(session, "VSPAEROSweep", full, overrides=overrides)
    session.fresh_results()
    api.ExecAnalysis("VSPAEROSweep")
    rid = session.latest("VSPAERO_Stab")

    suffix = SUFFIX[axis]
    vsp = {}
    for k in _VSP6:
        vals = api.GetDoubleResults(rid, f"{k}_{suffix}")
        if vals is None or len(vals) == 0:
            raise KeyError(f"VSPAERO_Stab has no key {k}_{suffix!r} — the unsteady output changed")
        vsp[k] = float(vals[0])
    frd = frames.coefficients_to_frd(vsp)
    sign = SIGN[axis]
    values = {c: sign * v for c, v in frd.items()}
    if not all(np.isfinite(v) for v in values.values()):
        raise ValueError(f"unsteady {axis} run produced non-finite derivatives: {values} — "
                         "this is the failure mode the roll axis has; do not ship it")
    return RateColumn(axis=axis, combined={"q_hat": "q_hat+alpha_dot", "r_hat": "r_hat-beta_dot"}[axis],
                      values=values, resolved_settings=resolved.as_json())
