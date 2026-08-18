"""The whole pipeline on a synthetic 5-group wing: campaign JSON → runner → raw.jsonl → assemble →
contract-valid aerodb.json → export with MANIFEST → byte-identical re-assembly (determinism).

The aircraft is fake (five control strips on one wing standing in for Icarus's surfaces), so this
does NOT assert the sign fixtures pass — it asserts the machinery: every table filled from the
right rows, CD0 folded in, all-analytic rate tables from the campaign's declared volumes, lint
EMBEDDED and reporting honestly, manifest hashes matching bytes. Icarus's own signs are P3's exit
criterion.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from aerodb_contract import canonical_json, load as contract_load
from streamline.campaign import assemble as asm, definition, export, runner
from streamline.vsp import geometry as geom_mod, reference

#: Three subsurfaces (left/right realised as the wing's symmetric copies: Surf1 = left, Surf0 =
#: right — determined empirically, aileron TE-down on Surf1 rolls right / +Cl), five groups.
#:
#: U-SPAN RULE, found the hard way: a control subsurface must sit inside the wing SECTION's part
#: of the U parameterization. On a one-section wing that is roughly U ∈ (0.45, 0.65); a strip
#: reaching the root/tip cap bands (e.g. 0.36–0.44 or 0.75–0.92) produces degenerate control
#: geometry and VSPAERO dies with "adb file not found" and NO Stab result. Icarus's audit (P3)
#: must check this for every real surface.
_SUBSURFACES = {"ail": (0.58, 0.64), "rv": (0.52, 0.56), "stab": (0.46, 0.50)}
#: group name -> (subsurface, gains per copy). Handedness lives in the GAINS (see
#: geometry.group_gains): right = (1, 0), left = (0, −1) — the mirrored copy un-mirrored —
#: symmetric = (1, −1). Both copies are always members; the gains select and orient.
_GROUPS = {
    "ail_L": ("ail", (0.0, -1.0)), "ail_R": ("ail", (1.0, 0.0)),
    "rv_L": ("rv", (0.0, -1.0)), "rv_R": ("rv", (1.0, 0.0)),
    "stab": ("stab", (1.0, -1.0)),
}
_SURFACE_TO_GROUP = {"aileron_left": "ail_L", "aileron_right": "ail_R", "stabilator": "stab",
                     "ruddervator_left": "rv_L", "ruddervator_right": "rv_R"}


def _build_five_group_wing(session, tmp_path):
    api = session.api
    wing = reference.flat_rectangular_wing(session, span_m=2.0, chord_m=0.25)
    for name, (u0, u1) in _SUBSURFACES.items():
        ss = api.AddSubSurf(wing.geom_id, api.SS_CONTROL, 0)
        api.SetSubSurfName(ss, name)
        api.SetParmVal(api.FindParm(ss, "UStart", "SS_Control"), u0)
        api.SetParmVal(api.FindParm(ss, "UEnd", "SS_Control"), u1)
        api.Update()
    for gname, (sub, gains) in _GROUPS.items():
        gi = api.CreateVSPAEROControlSurfaceGroup()
        api.SetVSPAEROControlGroupName(gname, gi)
        avail = list(api.GetAvailableCSNameVec(gi))
        picks = [i + 1 for i, n in enumerate(avail) if n.endswith(f"_{sub}")]
        assert len(picks) == 2, (gname, avail)
        api.AddSelectedToCSGroup(picks, gi)
        api.Update()
        geo = geom_mod.enumerate_model(session, tmp_path / "unused")
        geom_mod.set_group_gains(session, geo.group(gname), list(gains))
    # Ship the file with a stored non-zero deflection, the way a real model arrives (icarus rev A
    # has its elevator trimmed at −6°). The runner must zero it; if it doesn't, the baseline is
    # biased and symmetry_beta0 / lr_mirror / the sign assertions below all fail.
    geo = geom_mod.enumerate_model(session, tmp_path / "unused")
    geom_mod.set_group_deflection(session, geo.group("stab"), math.radians(-6.0))
    gdir = tmp_path / "geometry"
    gdir.mkdir(parents=True, exist_ok=True)
    path = gdir / "testwing-A.vsp3"
    api.WriteVSPFile(str(path), api.SET_ALL)
    return path, wing


def _campaign_json(tmp_path, geometry_path):
    doc = {
        "aircraft": "testwing", "geometry_rev": "A", "geometry_file": geometry_path.name,
        "geometry_sha256": canonical_json.sha256_file(geometry_path),
        "grid": {"alpha_deg": [0.0, 4.0], "beta_deg": [-5.0, 0.0, 5.0],
                 "airspeed_m_s": [30.0], "flap_deg": [0.0]},
        "altitude_m": 533.4, "cref_m": 0.25,
        "moment_reference_point_m": [0.0, 0.0, 0.0], "moment_reference_is_datum": True,
        "reference_wing": "WingGeom", "vlm_set": "All", "parasite_set": "All",
        "surface_groups": dict(_SURFACE_TO_GROUP),
        "solver": {"ncpu": 4, "wake_iters": 3, "num_wake_nodes": 8},
        # The fixture wing has no tail; the DECLARED tail below is fictional-but-plausible so the
        # analytic q̂/r̂ machinery (and the cm_q_band lint) is exercised with in-band numbers.
        # Hand values: x̄=0.65/0.25=2.6 → Cm_q=−2·0.9·3.3·(0.06/0.5)·2.6²·1.3 = −6.264,
        # CZ_q=−2.409; x̄v=0.65/2=0.325 → Cn_r=−2·0.9·2.5·(0.05/0.5)·0.325²=−0.04753, CY_r=+0.14625.
        "analytic_rates": {
            "horizontal_tails": [{"name": "ht", "S_m2": 0.06, "arm_m": 0.65, "a_per_rad": 3.3, "eta": 0.9}],
            "vertical_tails": [{"name": "vt", "S_m2": 0.05, "arm_m": 0.65, "a_per_rad": 2.5, "eta": 0.9}],
            "depsilon_dalpha": 0.3,
        },
        "cl_max_estimate": [1.2], "taper_ratio": 1.0,
        "sign_waivers": ["weathercock", "dihedral_effect"],
        "validity": {"alpha_deg": [-1.0, 5.0], "delta_deg_max": 25.0, "notes": "pipeline test"},
    }
    cdir = tmp_path / "campaign"
    cdir.mkdir(parents=True, exist_ok=True)
    p = cdir / "test.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def pipeline(session, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("pipe")
    gpath, wing = _build_five_group_wing(session, tmp_path)
    campaign = definition.load(_campaign_json(tmp_path, gpath))
    raw = tmp_path / "raw" / "shard0.jsonl"
    runner.run(session, campaign, raw, log=lambda *a: None)
    geometry = geom_mod.load(session, gpath)
    flags = asm.audit_completeness(geometry, campaign, has_ledger=False)
    rows = asm.read_rows(raw)
    doc = asm.assemble(campaign, rows, streamline_commit="deadbeef" * 5, completeness_flags=flags)
    return tmp_path, campaign, rows, doc, flags


@pytest.mark.vsp
@pytest.mark.slow
def test_the_assembled_document_is_contract_valid_and_fully_populated(pipeline):
    _, campaign, _, doc, _ = pipeline
    adb = contract_load.AeroDB.from_doc(doc)   # schema.check inside
    assert adb.base["CZ"].shape == (1, 1, 3, 2)
    assert np.all(np.isfinite(adb.base["CZ"]))
    # CD0 was folded in: CX at α=0, β=0 is negative by roughly the parasite CD0
    assert adb.base["CX"][0, 0, 1, 0] < -0.005
    # analytic q̂/r̂ from the campaign's declared tail volumes (hand numbers in _campaign_json)
    assert np.ptp(adb.rate["q_hat"]["Cm"]) == 0.0
    assert adb.rate["q_hat"]["Cm"][0, 0, 0, 0] == pytest.approx(-6.264, rel=1e-3)
    assert adb.rate["q_hat"]["CZ"][0, 0, 0, 0] == pytest.approx(-2.409, rel=1e-3)
    assert adb.rate["r_hat"]["Cn"][0, 0, 0, 0] == pytest.approx(-0.04753, rel=1e-3)
    assert adb.rate["r_hat"]["CY"][0, 0, 0, 0] == pytest.approx(+0.14625, rel=1e-3)
    assert np.ptp(adb.rate["r_hat"]["Cl"]) > 0.0    # Cl_r = CL/4 follows the local CL
    # analytic roll: Cl_p is the strip-theory constant, Cn_p varies with local CL
    assert adb.rate["p_hat"]["Cl"][0, 0, 0, 0] == pytest.approx(-5.0 / 6.0, rel=0.1)
    assert np.ptp(adb.rate["p_hat"]["Cn"]) > 0.0
    assert doc["provenance"]["per_table_source"]["tables.rate.p_hat"] == "analytic-strip-theory"
    assert doc["provenance"]["per_table_source"]["tables.rate.q_hat"] == "analytic-tail-volume"
    assert doc["provenance"]["per_table_source"]["tables.rate.r_hat"] == "analytic-tail-volume"


@pytest.mark.vsp
@pytest.mark.slow
def test_control_tables_carry_the_contract_signs(pipeline):
    """The gains realised the contract convention IN the geometry, so the raw derivatives already
    obey it: left TE-down rolls right (+Cl), right rolls left, both lift; the symmetric stabilator
    lifts and pitches nose-down about the forward reference."""
    _, _, _, doc, _ = pipeline
    adb = contract_load.AeroDB.from_doc(doc)
    idx = (0, 0, 1, 0)
    cl_l = adb.control["aileron_left"]["Cl"][idx]
    cl_r = adb.control["aileron_right"]["Cl"][idx]
    assert cl_l > 0.01 and cl_r < -0.01
    assert cl_l == pytest.approx(-cl_r, rel=0.05)
    assert adb.control["aileron_left"]["CZ"][idx] < 0   # TE down lifts, on the left panel too
    assert adb.control["stabilator"]["CZ"][idx] < 0
    assert adb.control["stabilator"]["Cm"][idx] < 0
    assert adb.control["stabilator"]["Cl"][idx] == pytest.approx(0.0, abs=5e-3)


@pytest.mark.vsp
@pytest.mark.slow
def test_lint_is_embedded_and_the_symmetric_checks_pass(pipeline):
    _, _, _, doc, _ = pipeline
    results = {r["check"]: r["status"] for r in doc["lint"]["results"]}
    assert results["finite"] == "pass"
    assert results["symmetry_beta0"] == "pass"
    assert results["lr_mirror"] == "pass", [r for r in doc["lint"]["results"] if r["check"] == "lr_mirror"]
    assert results["cl_alpha_band"] == "pass"
    assert results["cm_q_band"] == "pass"
    assert results["pinned"] == "pass"
    assert results["sign:weathercock"] in ("pass", "waived")


@pytest.mark.vsp
@pytest.mark.slow
def test_assembly_is_deterministic_and_export_hashes_match(pipeline, tmp_path):
    tmp, campaign, rows, doc, flags = pipeline
    doc2 = asm.assemble(campaign, rows, streamline_commit="deadbeef" * 5, completeness_flags=flags)
    assert canonical_json.dumps(doc) == canonical_json.dumps(doc2), "assemble is not deterministic"

    manifest = export.write_release(tmp_path / "rel", aerodb=doc, massprops=None, engine_deck=None,
                                    raw_paths=[tmp / "raw" / "shard0.jsonl"],
                                    streamline_commit="deadbeef" * 5)
    for name, sha in manifest["files"].items():
        assert canonical_json.sha256_file(tmp_path / "rel" / name) == sha, name
    assert (tmp_path / "rel" / "BUILD.json").exists()
    reread = canonical_json.read(tmp_path / "rel" / "aerodb.json")
    contract_load.AeroDB.from_doc(reread)


@pytest.mark.vsp
@pytest.mark.slow
def test_the_runner_resumes_instead_of_rerunning(session, pipeline):
    tmp, campaign, _, _, _ = pipeline
    raw = tmp / "raw" / "shard0.jsonl"
    before = raw.read_text()
    runner.run(session, campaign, raw, log=lambda *a: None)   # everything already present
    assert raw.read_text() == before
    # And with a RELATIVE path, as the CLI passes one: the runner must resolve it before the
    # workdir chdir, or it re-runs everything into a scratch-dir copy (found on the first real
    # `--out build/golden` invocation).
    rel = os.path.relpath(raw)
    runner.run(session, campaign, Path(rel), log=lambda *a: None)
    assert raw.read_text() == before
