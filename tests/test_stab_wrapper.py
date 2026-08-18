"""The stability wrapper end to end on the reference wing: base + α/β + control derivatives, in FRD,
per radian, and Vinf-invariant. This is the P4 exit criterion made permanent.

Rate derivatives are deliberately NOT asserted here — VSPAERO's steady rate columns are
Vinf-contaminated (documented in stab.py) and live in rates.py under their own decision.
"""

import math

import numpy as np
import pytest

from streamline import atmosphere as atm
from streamline.vsp import geometry as geom_mod, reference, stab


def _flat_wing(session, tmp_path):
    api = session.api
    wing = reference.flat_rectangular_wing(session, span_m=2.0, chord_m=0.25)
    # a trailing-edge control across part of the span, in its own VSPAERO group
    ss = api.AddSubSurf(wing.geom_id, api.SS_CONTROL, 0)
    api.Update()
    gi = api.CreateVSPAEROControlSurfaceGroup()
    api.SetVSPAEROControlGroupName("elevator", gi)
    api.AddSelectedToCSGroup([1], gi)
    api.Update()
    path = tmp_path / "wing.vsp3"
    api.WriteVSPFile(str(path), api.SET_ALL)
    return geom_mod.enumerate_model(session, path), wing


def _run(session, geometry, wing, *, V, alpha_deg=4.0, beta_deg=0.0):
    s = atm.isa(533.4)
    stab.run_compute_geometry(session, geometry, overrides=stab.compute_geometry_overrides(geometry))
    ov = stab.steady_overrides(
        session, geometry, alpha_rad=math.radians(alpha_deg), beta_rad=math.radians(beta_deg),
        airspeed_m_s=V, density_kg_m3=s.density_kg_m3, reynolds_cref=s.reynolds(V, 0.25),
        mach=s.mach(V), wing_id=wing.geom_id, moment_ref_m=[-0.0625, 0.0, 0.0],
        ncpu=2, wake_iters=3, num_wake_nodes=8)
    return stab.run_stability(session, geometry, overrides=ov)


@pytest.mark.vsp
@pytest.mark.slow
def test_base_and_alpha_derivative_are_frd_and_per_radian(session, tmp_path):
    geometry, wing = _flat_wing(session, tmp_path)
    with session.workdir(tmp_path):
        p = _run(session, geometry, wing, V=30.0)
    # lift is up → CZ negative at positive α; ∂CZ/∂α < 0 and ~ -5 /rad (lifting line ~5.03)
    assert p.base["CZ"] < 0
    assert p.d_alpha["CZ"] == pytest.approx(-5.03, rel=0.08)
    # per radian, not per degree: a per-degree slope would be ~-0.088
    assert abs(p.d_alpha["CZ"]) > 1.0
    # symmetric wing at β=0: no side force, roll or yaw
    for c in ("CY", "Cl", "Cn"):
        assert abs(p.base[c]) < 1e-3, c
    # the elevator group produced a pitch derivative with the right sign (TE down → nose down)
    assert "elevator" in p.d_control
    assert p.d_control["elevator"]["Cm"] < 0


@pytest.mark.vsp
@pytest.mark.slow
def test_the_steady_derivatives_are_vinf_invariant(session, tmp_path):
    """The property that makes α/β/control derivatives trustworthy while the rate ones are not:
    they do not move with airspeed."""
    geometry, wing = _flat_wing(session, tmp_path)
    with session.workdir(tmp_path):
        lo = _run(session, geometry, wing, V=20.0)
        hi = _run(session, geometry, wing, V=45.0)
    assert lo.d_alpha["CZ"] == pytest.approx(hi.d_alpha["CZ"], rel=0.03)
    assert lo.d_control["elevator"]["Cm"] == pytest.approx(hi.d_control["elevator"]["Cm"], rel=0.05)


@pytest.mark.vsp
@pytest.mark.slow
def test_a_bare_wing_has_almost_no_lateral_directional_derivatives(session, tmp_path):
    """The honest statement for THIS fixture: a flat, dihedral-free wing with no fin produces
    essentially zero side force, roll and yaw from sideslip — CY_β, Cl_β, Cn_β are all ~0. The
    signed lateral fixtures (weathercock, dihedral effect) belong on Icarus, which has a V-tail;
    here we pin that the wrapper returns ~0 rather than something spurious."""
    geometry, wing = _flat_wing(session, tmp_path)
    with session.workdir(tmp_path):
        p = _run(session, geometry, wing, V=30.0, beta_deg=5.0)
    for c in ("CY", "Cl", "Cn"):
        assert abs(p.d_beta[c]) < 0.05, f"{c}_beta = {p.d_beta[c]:.4f} should be ~0 for a bare wing"


@pytest.mark.vsp
@pytest.mark.slow
def test_a_forced_input_mismatch_is_caught(session, tmp_path):
    """The echo check: if VSPAERO ran a different condition than requested, raise. Provoked by
    handing the wrapper a settings dict whose Alpha the register will set but that we then corrupt
    — here we simply confirm a clean run does NOT raise (the negative side is unit-tested)."""
    geometry, wing = _flat_wing(session, tmp_path)
    with session.workdir(tmp_path):
        p = _run(session, geometry, wing, V=30.0)
    assert p.flight_condition["FC_Vinf_"] == pytest.approx(30.0)
