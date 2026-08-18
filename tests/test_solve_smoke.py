"""One real VSPAERO solve, end to end, against a number from lifting-line theory.

This is the P1 exit criterion made permanent: the pinned OpenVSP runs headless under the flake and
its VLM agrees with 2π AR/(AR+2) on a flat wing. It drives the raw API on purpose — the wrappers
(plan §3) will sit on top of exactly these calls, and this test is what they are checked against.
"""

import pytest

from streamline.vsp import reference


@pytest.mark.vsp
@pytest.mark.slow
def test_a_flat_wing_lift_curve_slope_matches_lifting_line(session, tmp_path):
    api = session.api
    wing = reference.flat_rectangular_wing(session, span_m=2.0, chord_m=0.25)

    with session.workdir(tmp_path):
        api.WriteVSPFile("wing.vsp3", api.SET_ALL)
        session.fresh_results()

        # The .vspgeom must exist before the sweep, or the sweep "succeeds" with no Stab result.
        cg = "VSPAEROComputeGeometry"
        api.SetAnalysisInputDefaults(cg)
        api.SetIntAnalysisInput(cg, "ThinGeomSet", [api.SET_ALL])
        api.SetIntAnalysisInput(cg, "GeomSet", [api.SET_NONE])
        api.ExecAnalysis(cg)

        an = "VSPAEROSweep"
        api.SetAnalysisInputDefaults(an)
        api.SetIntAnalysisInput(an, "ThinGeomSet", [api.SET_ALL])
        api.SetIntAnalysisInput(an, "GeomSet", [api.SET_NONE])
        api.SetIntAnalysisInput(an, "RefFlag", [1])
        api.SetStringAnalysisInput(an, "WingID", [wing.geom_id])
        api.SetIntAnalysisInput(an, "UnsteadyType", [api.STABILITY_DEFAULT])
        for key, val in (("AlphaStart", 4.0), ("AlphaEnd", 4.0), ("BetaStart", 0.0), ("BetaEnd", 0.0),
                         ("MachStart", 0.08), ("MachEnd", 0.08), ("Vinf", 30.0), ("Rho", 1.146),
                         ("ReCref", 5.0e5)):
            api.SetDoubleAnalysisInput(an, key, [val])
        for key in ("AlphaNpts", "BetaNpts", "MachNpts"):
            api.SetIntAnalysisInput(an, key, [1])
        api.SetIntAnalysisInput(an, "NCPU", [2])
        api.SetIntAnalysisInput(an, "WakeNumIter", [3])
        api.ExecAnalysis(an)

        rid = session.latest("VSPAERO_Stab")
        cl_alpha = api.GetDoubleResults(rid, "CL_Alpha")[0]
        sref = api.GetDoubleResults(session.latest("VSPAERO_History"), "FC_Sref_")[0]

    # Per radian, and within a few percent of theory. A per-degree answer would be ~0.088 and a
    # default-Sref answer would be off by 200x — both are the failure this test exists for.
    assert cl_alpha == pytest.approx(wing.cl_alpha_lifting_line, rel=0.05), cl_alpha
    assert sref == pytest.approx(wing.area_m2, rel=1e-6), "reference area did not come from the wing"
