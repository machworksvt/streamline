"""The QUARANTINED unsteady rate channel, pinned as evidence (see vsp/rates.py — the pipeline
ships analytic rate tables and never calls this wrapper).

Each test here pins one measured VSPAERO behaviour against pencil-and-paper physics. The
load-bearing one is the wing+tail reproducer: VSPAERO's Q analysis renders a WRONG-PHASED
response for surfaces at a lever arm, so adding a tail weakens its pitch damping. If an OpenVSP
bump fixes that upstream, that test fails loudly — and the quarantine decision gets revisited.
"""

import math

import numpy as np
import pytest

from streamline import atmosphere as atm
from streamline.backends import analytic
from streamline.vsp import geometry as geom_mod, rates, reference, stab


def _wing(session, tmp_path, with_fin=False):
    api = session.api
    wing = reference.flat_rectangular_wing(session, span_m=2.0, chord_m=0.25)
    if with_fin:
        tid = api.AddGeom("WING", "")
        api.SetParmVal(tid, "TotalSpan", "WingGeom", 0.7)
        api.SetParmVal(tid, "TotalChord", "WingGeom", 0.15)
        api.SetParmVal(tid, "Sweep", "XSec_1", 0.0)
        api.SetParmVal(tid, "X_Rel_Location", "XForm", 1.0)
        api.SetParmVal(tid, "X_Rel_Rotation", "XForm", 90.0)
        api.Update()
    path = tmp_path / "m.vsp3"
    api.WriteVSPFile(str(path), api.SET_ALL)
    return geom_mod.enumerate_model(session, path), wing


def _rate(session, geometry, wing, *, axis, V):
    s = atm.isa(533.4)
    stab.run_compute_geometry(session, geometry, overrides=stab.compute_geometry_overrides(geometry))
    ov = rates.unsteady_overrides(
        session, geometry, axis=axis, alpha_rad=math.radians(2.0), airspeed_m_s=V,
        density_kg_m3=s.density_kg_m3, reynolds_cref=s.reynolds(V, 0.25), mach=s.mach(V),
        wing_id=wing.geom_id, moment_ref_m=[-0.0625, 0.0, 0.0], ncpu=4, num_time_steps=64,
        # The values the SIGN calibration was measured under (they were OpenVSP's defaults when
        # this wrapper still let defaults through) — pinned explicitly now.
        wake_iters=5, num_wake_nodes=64)
    return rates.run_unsteady_rate(session, geometry, axis=axis, overrides=ov)


@pytest.mark.vsp
@pytest.mark.slow
def test_pitch_damping_matches_thin_wing_theory_after_calibration(session, tmp_path):
    """A bare wing about its quarter chord: thin-wing theory gives Cm_q+Cm_α̇ ≈ −(π/2 + π/2) with a
    3-D knockdown, so a few units negative; CL_q+CL_α̇ correspondingly positive. This pins
    SIGN['q_hat'] = −1 against physics — and documents how the lever-arm defect slipped past
    calibration: the wing-alone case is the one configuration VSPAERO renders correctly."""
    geometry, wing = _wing(session, tmp_path)
    with session.workdir(tmp_path):
        col = _rate(session, geometry, wing, axis="q_hat", V=30.0)
    assert -4.5 < col.values["Cm"] < -1.5, col.values
    # CZ is FRD: lift up from positive q̂ is negative CZ
    assert col.values["CZ"] < -4.0, col.values
    assert col.combined == "q_hat+alpha_dot"


@pytest.mark.vsp
@pytest.mark.slow
def test_pitch_damping_is_vinf_invariant(session, tmp_path):
    """The property the steady columns lack (44→301 over 15→120 m/s). Measured 2.8418 vs 2.8511
    at 30 vs 45 m/s in the spike; 2% covers solver noise."""
    geometry, wing = _wing(session, tmp_path)
    with session.workdir(tmp_path):
        lo = _rate(session, geometry, wing, axis="q_hat", V=30.0)
        hi = _rate(session, geometry, wing, axis="q_hat", V=45.0)
    assert lo.values["Cm"] == pytest.approx(hi.values["Cm"], rel=0.02)


@pytest.mark.vsp
@pytest.mark.slow
def test_yaw_damping_from_a_fin_is_negative_without_any_sign_flip(session, tmp_path):
    """The r channel is published correctly (SIGN=+1): a fin must damp yaw and push CY with the
    rate. If this starts failing with reversed signs, VSPAERO changed its lateral phase convention
    and the calibration table needs re-deriving — from physics, not from the previous release."""
    geometry, wing = _wing(session, tmp_path, with_fin=True)
    with session.workdir(tmp_path):
        col = _rate(session, geometry, wing, axis="r_hat", V=30.0)
    assert col.values["Cn"] < -0.05, col.values
    assert col.values["CY"] > 0.05, col.values


@pytest.mark.vsp
@pytest.mark.slow
def test_a_tail_makes_vspaero_pitch_damping_weaker_which_is_why_the_channel_is_quarantined(session, tmp_path):
    """THE reproducer (measured 2026-08-17, OpenVSP 3.51.2): add a horizontal tail 2.6 c̄ aft and
    VSPAERO's Cm_(q+α̇) went −2.84 → −1.95, where classical tail-volume physics ADDS ≈ −8 (a
    textbook total ≈ −11). The distant surface responds wrong-phased in the forced oscillation.
    All pipeline rate tables are therefore analytic (backends/analytic.py).

    If THIS test fails with a strongly negative wing+tail value, OpenVSP fixed the defect —
    revisit the quarantine (plan §rate-derivatives; keep the analytic path as cross-check)."""
    geometry, wing = _wing(session, tmp_path)
    with session.workdir(tmp_path):
        alone = _rate(session, geometry, wing, axis="q_hat", V=30.0)
    api = session.api
    tid = api.AddGeom("WING", "")
    api.SetGeomName(tid, "HTail")
    api.SetParmVal(api.FindParm(tid, "TotalSpan", "WingGeom"), 0.8)
    api.SetParmVal(api.FindParm(tid, "TotalChord", "WingGeom"), 0.15)
    api.SetParmVal(api.FindParm(tid, "X_Location", "XForm"), 0.65)
    api.Update()
    path = tmp_path / "m2.vsp3"
    api.WriteVSPFile(str(path), api.SET_ALL)
    geometry2 = geom_mod.enumerate_model(session, path)
    with session.workdir(tmp_path):
        with_tail = _rate(session, geometry2, wing, axis="q_hat", V=30.0)
    assert alone.values["Cm"] < -1.5, alone.values
    # the defect: the tail WEAKENS the published damping instead of deepening it by ~-8
    assert with_tail.values["Cm"] > alone.values["Cm"] + 0.5, (
        f"wing-alone {alone.values['Cm']:.2f}, wing+tail {with_tail.values['Cm']:.2f} — "
        "VSPAERO now deepens damping with a tail: the upstream defect may be FIXED; "
        "revisit the analytic-rates quarantine")


def test_the_roll_axis_is_refused_by_the_unsteady_wrapper():
    with pytest.raises(ValueError, match="analytic"):
        rates.run_unsteady_rate(None, None, axis="p_hat", overrides={})


def test_analytic_roll_damping_is_the_strip_theory_number():
    # rectangular: λ=1 → −CL_α/6
    assert analytic.cl_p(5.03, 1.0) == pytest.approx(-5.03 / 6.0)
    # Icarus-ish taper 0.53: −(CL_α/12)(1+1.6)/1.53
    assert analytic.cl_p(5.0, 0.533) == pytest.approx(-(5.0 / 12.0) * (1 + 3 * 0.533) / (1 + 0.533))
    with pytest.raises(ValueError):
        analytic.cl_p(20.0, 1.0)


def test_the_analytic_p_column_keeps_alpha_dependence_in_cn_only():
    cl = np.array([[0.2, 0.6], [1.0, 1.4]])
    col = analytic.p_hat_column(5.0, 1.0, cl)
    assert np.all(col["Cl"] == pytest.approx(-5.0 / 6.0))
    assert col["Cn"] == pytest.approx(-cl / 8.0)
    for c in ("CX", "CY", "CZ", "Cm"):
        assert np.all(col[c] == 0.0)
