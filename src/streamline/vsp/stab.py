"""The VSPAERO stability wrapper: one (α, β, V) point → base coefficients and derivatives, in FRD.

This is the critical path (the user's word). What it does that the legacy code did not:

1. **Every solver input is set through the register** (`settings.resolve`) — no silent default — and
   the resolved set is returned for the artifact's provenance.
2. **Results are read by key with a parser that RAISES on a missing key** rather than writing NaN,
   so a VSPAERO output rename is a loud failure, not an all-NaN table.
3. **It only returns what the steady solve computes trustworthily**: the base coefficients, the
   α/β derivatives, and the per-surface control derivatives. All three are per radian and
   Vinf-invariant (AR-8 wing: CL_α 5.04 vs lifting-line 5.03; control derivatives flat across V).

RATE DERIVATIVES ARE NOT HERE. VSPAERO's steady stability mode reports `C*_p/q/r` per unit
non-dimensional rate, but the reported value carries a spurious velocity dependence: on the AR-8
wing `CL_q` runs 44 → 81 → 154 → 301 as Vinf 15 → 30 → 60 → 120 (a clean linear ramp), and `Cl_p`
runs −0.77 → −1.04 → −1.34 → −1.53 over the same span, when the true non-dimensional derivative is
Vinf-invariant. Root cause (OpenVSP `src/vsp_aero/Solver/vspaero.C`, 3.51.2): the driver perturbs
the ABSOLUTE rate by a fixed `0.01 rad/Tunit` and divides ΔC by `0.01·Lref·0.5/Vinf`, so the
finite-difference step in q̂ shrinks with Vinf and a term that scales as Vinf⁰ leaks through as
`derivative ∝ Vinf`. The dedicated unsteady modes (`STABILITY_Q_ANALYSIS`, `..._R_ANALYSIS`) return
the physically-correct COMBINED damping (`CMm_q+alpha_dot`, `CMl_r-beta_dot`, …) and ARE
Vinf-invariant (Cm_q+α̇ = 2.84 at V=30, 2.85 at V=45), but cost ~16 s each and `STABILITY_P_ANALYSIS`
(roll) returns NaN for a thin wing. Rate derivatives therefore live in `rates.py`, which owns that
decision and its provenance; the campaign chooses the method. `run_stability` deliberately does not
touch the steady rate columns.

FRAME. VSPAERO `Base_Aero_C{Fx,Fy,Fz,Mx,My,Mz}` are body-axis (X aft, Z up); `frames.py` rotates
them to FRD. α/β and control derivatives are per radian.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from . import frames, settings as settings_mod
from .geometry import Geometry
from .session import Session

_COEFS = ("CX", "CY", "CZ", "Cl", "Cm", "Cn")
_VSP6 = ("CFx", "CFy", "CFz", "CMx", "CMy", "CMz")


@dataclass(frozen=True)
class StabPoint:
    alpha_rad: float
    beta_rad: float
    airspeed_m_s: float
    base: dict                      # coef -> value, FRD
    d_alpha: dict                   # coef -> ∂/∂α (per rad), FRD
    d_beta: dict                    # coef -> ∂/∂β (per rad), FRD
    d_control: dict                 # surface (VSPAERO group name) -> coef -> ∂/∂δ (per rad), FRD
    static_margin: float
    neutral_point_x_m: float        # FRD X of the neutral point
    resolved_settings: dict         # the full VSPAEROSweep input set, for provenance
    flight_condition: dict          # FC_* echo, for the mismatch check


def _read(session: Session, rid: str, key: str) -> float:
    vals = session.api.GetDoubleResults(rid, key)
    if vals is None or len(vals) == 0:
        raise KeyError(f"VSPAERO_Stab has no key {key!r} — the output format changed; do not guess")
    return float(vals[0])


def _rotate(session: Session, rid: str, suffix: str) -> dict:
    """Read the six VSPAERO body-axis columns `<CF*/CM*>_<suffix>` and rotate to FRD coefficients."""
    vsp = {k: _read(session, rid, f"{k}_{suffix}") for k in _VSP6}
    return frames.coefficients_to_frd(vsp)


def compute_geometry_overrides(geometry: Geometry, *, vlm_set: str = "All") -> dict:
    """`vlm_set` names the OpenVSP set solved as thin VLM surfaces. "All" is only right for
    models that contain nothing but lifting surfaces (the test fixtures); campaigns must name a
    real set — icarus rev A carries fuel-mass conformals, servo CAD meshes and stowed gear that
    "All" would lift. GeomSet −1 (SET_NONE) keeps the thick/panel side empty: v0 is pure VLM."""
    return {"GeomSet": -1, "ThinGeomSet": geometry.set_index(vlm_set)}


def run_compute_geometry(session: Session, geometry: Geometry, *, overrides: dict) -> dict:
    """VSPAEROComputeGeometry — writes the .vspgeom the sweep reads. Must precede every stab run."""
    full = settings_mod.complete(session, "VSPAEROComputeGeometry", overrides)
    resolved = settings_mod.resolve(session, "VSPAEROComputeGeometry", full, overrides=overrides)
    session.api.ExecAnalysis("VSPAEROComputeGeometry")
    return resolved.as_json()


def steady_overrides(session: Session, geometry: Geometry, *, alpha_rad: float, beta_rad: float,
                     airspeed_m_s: float, density_kg_m3: float, reynolds_cref: float, mach: float,
                     wing_id: str, moment_ref_m, ncpu: int, wake_iters: int, num_wake_nodes: int,
                     vlm_set: str = "All", extra: Mapping | None = None) -> dict:
    """The physically-meaningful VSPAEROSweep inputs for one steady stability point — the overrides
    the campaign chooses. `settings.complete` fills the rest from OpenVSP's defaults so the full set
    is recorded (plan §3.1). Positions FRD → VSP for the moment reference; α/β in degrees."""
    mref = frames.frd_to_vsp(moment_ref_m)
    deg = 180.0 / np.pi
    s = {
        "AlphaStart": alpha_rad * deg, "AlphaEnd": alpha_rad * deg, "AlphaNpts": 1,
        "BetaStart": beta_rad * deg, "BetaEnd": beta_rad * deg, "BetaNpts": 1,
        "MachStart": mach, "MachEnd": mach, "MachNpts": 1,
        "ReCref": reynolds_cref, "ReCrefEnd": reynolds_cref, "ReCrefNpts": 1,
        "Vinf": airspeed_m_s, "Rho": density_kg_m3, "Machref": max(mach, 1e-3),
        "RefFlag": 1, "WingID": wing_id,
        "Xcg": float(mref[0]), "Ycg": float(mref[1]), "Zcg": float(mref[2]),
        "GeomSet": -1, "ThinGeomSet": geometry.set_index(vlm_set),
        "UnsteadyType": int(session.api.STABILITY_DEFAULT),   # 1, not 0 (0 is STABILITY_OFF)
        "NCPU": ncpu, "WakeNumIter": wake_iters, "NumWakeNodes": num_wake_nodes,
        "FixedWakeFlag": 0, "Symmetry": 0,
    }
    if extra:
        s.update(extra)
    return s


def run_stability(session: Session, geometry: Geometry, *, overrides: dict) -> StabPoint:
    """One steady stability point. `overrides` names the inputs that matter; the register fills and
    records the rest and refuses a missing or unknown input. ComputeGeometry must already have run."""
    api = session.api
    full = settings_mod.complete(session, "VSPAEROSweep", overrides)
    resolved = settings_mod.resolve(session, "VSPAEROSweep", full, overrides=overrides)
    settings = full
    session.fresh_results()
    api.ExecAnalysis("VSPAEROSweep")
    rid = session.latest("VSPAERO_Stab")
    hid = session.latest("VSPAERO_History")

    base = frames.coefficients_to_frd({k: _read(session, rid, f"Base_Aero_{k}") for k in _VSP6})
    d_alpha = _rotate(session, rid, "Alpha")
    d_beta = _rotate(session, rid, "Beta")

    d_control = {}
    for group in geometry.control_groups:
        try:
            d_control[group.name] = _rotate(session, rid, group.name)
        except KeyError:
            continue   # a group defined in geometry but not present in this run's columns

    flight = {k: _read(session, hid, k) for k in
              ("FC_Vinf_", "FC_Mach_", "FC_Sref_", "FC_Bref_", "FC_Cref_", "FC_AoA_", "FC_Beta_",
               "FC_Rho_", "FC_ReCref_", "FC_Xcg_")}
    _check_echo(settings, flight)
    return StabPoint(
        alpha_rad=float(settings["AlphaStart"]) * np.pi / 180.0,
        beta_rad=float(settings["BetaStart"]) * np.pi / 180.0,
        airspeed_m_s=flight["FC_Vinf_"], base=base, d_alpha=d_alpha, d_beta=d_beta,
        d_control=d_control, static_margin=_read(session, rid, "SM"),
        neutral_point_x_m=float(frames.vsp_to_frd([_read(session, rid, "X_np"), 0.0, 0.0])[0]),
        resolved_settings=resolved.as_json(), flight_condition=flight)


def _check_echo(settings: dict, flight: dict) -> None:
    """VSPAERO echoes the flight condition it actually ran; a mismatch means an input was ignored
    or unit-slipped (the failure the register exists to catch, here confirmed against the output)."""
    checks = [("Vinf", "FC_Vinf_", 1e-6), ("Rho", "FC_Rho_", 1e-6),
              ("AlphaStart", "FC_AoA_", 1e-4), ("BetaStart", "FC_Beta_", 1e-4)]
    bad = []
    for set_key, fc_key, tol in checks:
        want = float(settings[set_key])
        got = float(flight[fc_key])
        if abs(want - got) > tol * max(1.0, abs(want)):
            bad.append(f"{set_key}={want} but VSPAERO ran {fc_key}={got}")
    if bad:
        raise ValueError("VSPAERO ignored or altered an input:\n  " + "\n  ".join(bad))
