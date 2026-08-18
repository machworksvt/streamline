"""The evaluator reproduces the model the tables were built from; lint and signs catch injected faults."""

import copy
import math

import numpy as np
import pytest

from aerodb_contract import completeness as comp, lint, load, signs, synthetic
from aerodb_contract.synthetic import CONTROL, DERIVS


@pytest.fixture(scope="module")
def adb():
    return load.AeroDB.from_doc(synthetic.synthetic_aerodb())


def test_multilinear_is_exact_on_a_linear_table():
    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 2.0]))
    table = np.array([[0.0, 2.0], [1.0, 3.0], [2.0, 4.0]])  # x + y
    assert load.multilinear(axes, table, (0.5, 1.0)) == pytest.approx(1.5)
    assert load.multilinear(axes, table, (1.75, 0.5)) == pytest.approx(2.25)
    # clamped, never extrapolated
    assert load.multilinear(axes, table, (-3.0, 9.0)) == pytest.approx(0.0 + 2.0)


def test_the_evaluator_reproduces_the_generating_model_between_grid_points(adb):
    """The synthetic base is linear in α, β and flap for Cm, Cl, Cn, so multilinear interpolation
    must be exact off-grid there — and the rate/control terms are exact by construction."""
    a, b, f = math.radians(3.0), math.radians(-7.5), math.radians(7.5)
    c = adb.evaluate(alpha=a, beta=b, V=25.0, flap=f, rates={"q_hat": 0.02, "p_hat": -0.01},
                     deltas={"stabilator": 0.05, "aileron_left": 0.1})
    d = DERIVS
    cm = d["Cm0"] + d["Cm_a"] * a + d["dCm_f"] * f + d["Cm_q"] * 0.02 + CONTROL["stabilator"][4] * 0.05
    cl = d["Cl_b"] * b + d["Cl_p"] * (-0.01) + CONTROL["aileron_left"][3] * 0.1
    cn = d["Cn_b"] * b + d["Cn_p"] * (-0.01) + CONTROL["aileron_left"][5] * 0.1
    assert c["Cm"] == pytest.approx(cm, abs=1e-12)
    assert c["Cl"] == pytest.approx(cl, abs=1e-12)
    assert c["Cn"] == pytest.approx(cn, abs=1e-12)


def test_flaps_are_not_accepted_as_a_delta(adb):
    with pytest.raises(KeyError, match="flaps enter via the axis"):
        adb.evaluate(alpha=0.0, beta=0.0, V=30.0, deltas={"flap_left": 0.1})


def test_lift_drag_recovers_the_wind_axis_numbers(adb):
    a = math.radians(4.0)
    c = adb.evaluate(alpha=a, beta=0.0, V=30.0)
    cl, cd = adb.lift_drag(c, a)
    want_cl = DERIVS["CL0"] + DERIVS["CL_a"] * a
    assert cl == pytest.approx(want_cl, rel=1e-9)
    assert cd == pytest.approx(DERIVS["CD0"] + DERIVS["K"] * want_cl ** 2, rel=1e-9)


def test_moment_transfer_is_the_textbook_formula():
    m = load.transfer_moment([0, 0, 0], [0, 0, -10.0], r_ref=[-0.5, 0, 0], r_cg=[-0.6, 0, 0])
    # F up (−Z) applied 0.1 m ahead of the CG → nose-up (+M)
    assert m == pytest.approx([0.0, 1.0, 0.0])


def test_the_synthetic_passes_every_sign_fixture_and_lint_check(adb):
    res = signs.check_signs(adb)
    assert not signs.failures(res), [r for r in res if r.status != "pass"]
    rows = lint.run_lint(adb)
    assert not lint.blocking(rows), lint.blocking(rows)
    # the synthetic grid reaches α = 16°, so a few points are beyond the CL_max guess: a warning
    assert any(r["check"] == "stall_points" and r["status"] == "warn" for r in rows)


def _mutated(mutate):
    d = synthetic.synthetic_aerodb()
    mutate(d)
    return load.AeroDB.from_doc(d)


def test_a_flipped_elevator_sign_fails_the_fixture_and_the_lint():
    adb = _mutated(lambda d: d["tables"]["control"].__setitem__(
        "stabilator", {c: (-np.asarray(t)).tolist() for c, t in d["tables"]["control"]["stabilator"].items()}))
    names = {r.name for r in signs.failures(signs.check_signs(adb))}
    assert {"stabilator_te_down_is_nose_down", "stabilator_te_down_lifts"} <= names
    assert any(r["check"] == "sign:stabilator_te_down_is_nose_down" and r["status"] == "fail" for r in lint.run_lint(adb))


def test_static_stability_signs_are_waivable_but_frame_signs_are_not():
    adb = _mutated(lambda d: d["tables"]["base"].__setitem__("Cn", (-np.asarray(d["tables"]["base"]["Cn"])).tolist()))
    assert "weathercock" in {r.name for r in signs.failures(signs.check_signs(adb))}
    res = signs.check_signs(adb, waivers=("weathercock",))
    assert not signs.failures(res) and any(r.status == "waived" for r in res)

    adb = _mutated(lambda d: d["tables"]["base"].__setitem__("CZ", (-np.asarray(d["tables"]["base"]["CZ"])).tolist()))
    res = signs.check_signs(adb, waivers=("lift_up_is_negative_CZ",))
    assert "lift_up_is_negative_CZ" in {r.name for r in signs.failures(res)}, "frame facts cannot be waived"


def test_lint_catches_a_per_degree_lift_slope():
    adb = _mutated(lambda d: d["tables"]["base"].__setitem__("CZ", (np.asarray(d["tables"]["base"]["CZ"]) / 57.3).tolist()))
    bad = {r["check"] for r in lint.blocking(lint.run_lint(adb))}
    assert "cl_alpha_band" in bad


def test_lint_catches_a_dimensional_pitch_rate():
    adb = _mutated(lambda d: d["tables"]["rate"]["q_hat"].__setitem__("Cm", (np.asarray(d["tables"]["rate"]["q_hat"]["Cm"]) * 60.0).tolist()))
    assert "cm_q_band" in {r["check"] for r in lint.blocking(lint.run_lint(adb))}


def test_lint_catches_a_lateral_asymmetry_at_zero_sideslip():
    d = synthetic.synthetic_aerodb()
    cn = np.asarray(d["tables"]["base"]["Cn"]); cn[0, 1, 3, 4] = 0.05
    d["tables"]["base"]["Cn"] = cn.tolist()
    adb = load.AeroDB.from_doc(d)
    assert "symmetry_beta0" in {r["check"] for r in lint.blocking(lint.run_lint(adb))}


def test_lint_catches_a_broken_left_right_mirror():
    d = synthetic.synthetic_aerodb()
    d["tables"]["control"]["aileron_right"]["Cl"] = d["tables"]["control"]["aileron_left"]["Cl"]  # same sign
    assert "lr_mirror" in {r["check"] for r in lint.blocking(lint.run_lint(load.AeroDB.from_doc(d)))}


def test_an_unpinned_solver_or_an_open_required_item_blocks_release():
    d = synthetic.synthetic_aerodb()
    d["provenance"]["backend"]["unpinned"] = True
    assert "pinned" in {r["check"] for r in lint.blocking(lint.run_lint(load.AeroDB.from_doc(d)))}
    d = synthetic.synthetic_aerodb()
    for f in d["completeness"]["flags"]:
        if f["item"] == "surfaces_hinged":
            f["status"] = "open"
    assert "completeness_required" in {r["check"] for r in lint.blocking(lint.run_lint(load.AeroDB.from_doc(d)))}


def test_completeness_flags_are_validated_structurally():
    flags = [{"item": it.id, "status": "clear", "note": ""} for it in comp.CHECKLIST]
    assert comp.validate_flags(flags) == []
    assert comp.validate_flags(flags[1:])  # missing one
    bad = copy.deepcopy(flags); bad[0]["status"] = "waived"; bad[0]["note"] = ""
    assert any("waived without a note" in e for e in comp.validate_flags(bad))
