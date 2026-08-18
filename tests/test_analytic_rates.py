"""The analytic q̂/r̂ tail-volume columns: hand-computed numbers, shapes, and the campaign-side
validation of the `analytic_rates` block. Fast — no OpenVSP."""

import json

import numpy as np
import pytest

from streamline.backends import analytic
from streamline.campaign import definition

SPEC = {
    "horizontal_tails": [{"name": "ht", "S_m2": 0.06, "arm_m": 0.65, "a_per_rad": 3.3, "eta": 0.9}],
    "vertical_tails": [{"name": "vt", "S_m2": 0.05, "arm_m": 0.65, "a_per_rad": 2.5, "eta": 0.9}],
    "depsilon_dalpha": 0.3,
}
S, CBAR, B = 0.5, 0.25, 2.0


def test_q_hat_hand_numbers():
    """x̄ = 0.65/0.25 = 2.6:  CZ = −2·0.9·3.3·0.12·2.6·1.3 = −2.4093;  Cm = ·2.6 → −6.2641."""
    col = analytic.q_hat_column(SPEC, S, CBAR, (2, 1, 3, 2))
    assert col["Cm"].shape == (2, 1, 3, 2)
    assert float(col["Cm"][0, 0, 0, 0]) == pytest.approx(-6.264086, rel=1e-6)
    assert float(col["CZ"][0, 0, 0, 0]) == pytest.approx(-2.409264, rel=1e-6)
    assert np.ptp(col["Cm"]) == 0.0
    for c in ("CX", "CY", "Cl", "Cn"):
        assert np.all(col[c] == 0.0)


def test_r_hat_hand_numbers_and_cl_r():
    """x̄v = 0.65/2 = 0.325:  CY = +2·0.9·2.5·0.1·0.325 = +0.146250;  Cn = ·0.325 → −0.0475313;
    Cl_r = CL/4 per point."""
    cl = np.array([[0.2, 0.8]])
    col = analytic.r_hat_column(SPEC, S, B, cl)
    assert float(col["CY"][0, 0]) == pytest.approx(+0.146250, rel=1e-5)
    assert float(col["Cn"][0, 0]) == pytest.approx(-0.0475313, rel=1e-5)
    assert col["Cl"][0, 0] == pytest.approx(0.05) and col["Cl"][0, 1] == pytest.approx(0.2)
    for c in ("CX", "CZ", "Cm"):
        assert np.all(col[c] == 0.0)


def test_two_tails_sum():
    two = dict(SPEC)
    two["horizontal_tails"] = SPEC["horizontal_tails"] * 2
    one = analytic.q_hat_column(SPEC, S, CBAR, (1,))
    both = analytic.q_hat_column(two, S, CBAR, (1,))
    assert float(both["Cm"][0]) == pytest.approx(2 * float(one["Cm"][0]), rel=1e-12)


def _campaign_doc(analytic_rates):
    return {
        "aircraft": "x", "geometry_rev": "A", "geometry_file": "x.vsp3", "geometry_sha256": "0" * 64,
        "grid": {"alpha_deg": [0.0, 2.0], "beta_deg": [0.0], "airspeed_m_s": [30.0], "flap_deg": [0.0]},
        "altitude_m": 0.0, "cref_m": 0.25, "moment_reference_point_m": [0, 0, 0],
        "reference_wing": "W", "vlm_set": "All", "parasite_set": "All",
        "surface_groups": {}, "solver": {"ncpu": 1, "wake_iters": 1, "num_wake_nodes": 8},
        "analytic_rates": analytic_rates, "cl_max_estimate": [1.2], "taper_ratio": 1.0,
        "validity": {"alpha_deg": [-1, 3], "delta_deg_max": 10.0},
    }


def _load(tmp_path, doc):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return definition.load(p)


def test_campaign_accepts_a_valid_analytic_rates_block(tmp_path):
    c = _load(tmp_path, _campaign_doc(SPEC))
    assert c.analytic_rates["depsilon_dalpha"] == 0.3


@pytest.mark.parametrize("mutate, msg", [
    (lambda ar: ar.pop("depsilon_dalpha"), "depsilon_dalpha"),
    (lambda ar: ar.update(horizontal_tails=[]), "non-empty"),
    (lambda ar: ar["horizontal_tails"][0].pop("arm_m"), "arm_m"),
    (lambda ar: ar["horizontal_tails"][0].update(arm_m=-0.5), "AFT"),
    (lambda ar: ar["vertical_tails"][0].update(a_per_rad=25.0), "implausible"),
])
def test_campaign_refuses_broken_analytic_rates(tmp_path, mutate, msg):
    doc = _campaign_doc(json.loads(json.dumps(SPEC)))
    mutate(doc["analytic_rates"])
    with pytest.raises(definition.CampaignError, match=msg):
        _load(tmp_path, doc)
