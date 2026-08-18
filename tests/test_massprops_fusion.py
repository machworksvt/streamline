"""Fusion export → ledger: parallel axis, frame, overrides, fuel, balance sizing — and the
committed Icarus ledger regenerates byte-for-byte from the committed export + overrides."""

import json
from pathlib import Path

import numpy as np
import pytest

from aerodb_contract import canonical_json
from streamline import massprops as mp_mod, massprops_fusion as mf

ROOT = Path(__file__).resolve().parents[1]
HDR = "HDR|path|body|mass_kg|vol_cm3|area_cm2|cx_cm|cy_cm|cz_cm|Ixx|Iyy|Izz|Ixy|Iyz|Ixz|material|density|visible|lightbulb|solid"


def _row(path, body, m, c_cm, I_c6, mat, rho, vis=1):
    """A body row from its OWN-CG tensor (kg cm², xx yy zz xy yz xz, tensor convention): the
    export carries the tensor about the ORIGIN, so apply the parallel axis the way Fusion does."""
    x, y, z = c_cm
    xx, yy, zz, xy, yz, xz = I_c6
    Io = (xx + m * (y * y + z * z), yy + m * (x * x + z * z), zz + m * (x * x + y * y),
          xy - m * x * y, yz - m * y * z, xz - m * x * z)
    vol = m / rho * 1e6 if rho else 1.0
    return "|".join(str(v) for v in [path, body, m, vol, 1.0, x, y, z, *Io, mat, rho, vis, vis, 1])


@pytest.fixture
def export(tmp_path):
    rows = [
        HDR,
        # a 2 kg cube-ish body in "Fuse:1", far aft-right-up, own tensor diag(0.01,0.02,0.03) kg m² = 100,200,300 kg cm²
        _row("/Fuse:1", "A", 2.0, (50.0, 10.0, 5.0), (100.0, 200.0, 300.0, 0.0, 0.0, 0.0), "Alu", 2700.0),
        # a 1 kg body in the same group, forward-left
        _row("/Fuse:1", "B", 1.0, (-30.0, -10.0, 0.0), (10.0, 10.0, 10.0, 0.0, 0.0, 0.0), "Steel", 7850.0),
        # a 'fuel' body: 1 L of water at the origin-ish
        _row("/Tank:1", "F", 1.0, (-5.0, 0.0, 4.0), (5.0, 5.0, 5.0, 0.0, 0.0, 0.0), "Fuel", 1000.0, vis=0),
        # a default-steel servo in a tail group
        _row("/Tail:1/Servo:1", "S", 0.785, (60.0, 20.0, 10.0), (1.0, 1.0, 1.0, 0.0, 0.0, 0.0), "Steel", 7850.0),
    ]
    p = tmp_path / "bodies.psv"
    p.write_text("\n".join(rows) + "\n")
    ov = {
        "fuel": {"bodies": [{"path_glob": "/Tank:1", "body": "F"}], "density_kg_m3": 800.0, "reason": "kerosene"},
        "density_overrides": [{"path_glob": "/Tail:1/Servo*", "body": "S", "density_kg_m3": 785.0, "reason": "1/10"}],
        "extra_components": [],
        "balance": {"name": "nose_ballast", "cg_frd_m": [0.7, 0.0, 0.0], "target_dry_cg_x_frd_m": 0.0, "reason": "t"},
    }
    q = tmp_path / "ov.json"
    q.write_text(json.dumps(ov))
    return p, q


def test_read_bodies_units_and_frame(export):
    bodies = mf.read_bodies(export[0])
    a = bodies[0]
    assert a.mass_kg == 2.0 and a.material == "Alu"
    assert np.allclose(a.com_root_m, [0.5, 0.1, 0.05])
    # origin tensor back to own CG reproduces diag(0.01, 0.02, 0.03)
    _, cg, Ic = mf.aggregate([a])
    assert np.allclose(Ic, np.diag([0.01, 0.02, 0.03]), atol=1e-12)


def test_group_aggregate_matches_hand_parallel_axis(export):
    bodies = mf.read_bodies(export[0])
    fuse = [b for b in bodies if b.top == "Fuse:1"]
    m, cg, Ic = mf.aggregate(fuse)
    assert m == 3.0
    assert np.allclose(cg, [(2 * 0.5 + 1 * -0.3) / 3, (2 * 0.1 - 1 * 0.1) / 3, (2 * 0.05) / 3])
    I = np.zeros((3, 3))
    for b, Ib in ((fuse[0], np.diag([0.01, 0.02, 0.03])), (fuse[1], np.diag([0.001] * 3))):
        d = b.com_root_m - cg
        I += Ib + b.mass_kg * (float(d @ d) * np.eye(3) - np.outer(d, d))
    assert np.allclose(Ic, I, atol=1e-12)


def test_frd_conversion_flips_xy_yz_only():
    I = np.array([[1.0, 0.2, 0.3], [0.2, 2.0, 0.4], [0.3, 0.4, 3.0]])
    F = mf.tensor_to_frd(I)
    assert np.allclose(np.diag(F), [1, 2, 3])
    assert F[0, 1] == -0.2 and F[1, 2] == -0.4 and F[0, 2] == 0.3
    assert np.allclose(mf.to_frd([1.0, 2.0, 3.0]), [-1.0, 2.0, -3.0])


def test_build_ledger_applies_overrides_fuel_and_balance(export, tmp_path):
    doc = mf.build_ledger(*export)
    names = [c["name"] for c in doc["components"]]
    assert "fusion:Fuse:1" in names and "fusion:Tail:1" in names and "fusion:Tank:1" not in names
    tail = next(c for c in doc["components"] if c["name"] == "fusion:Tail:1")
    assert tail["mass_kg"] == pytest.approx(0.0785)                       # re-densified 1/10
    assert doc["fuel"]["mass_full_kg"] == pytest.approx(0.8) and doc["fuel"]["volume_l"] == pytest.approx(1.0)
    assert np.allclose(doc["fuel"]["cg_m"], [0.05, 0.0, -0.04])          # root (-5,0,4) cm → FRD
    bal = next(c for c in doc["components"] if c["name"] == "nose_ballast")
    out = mf.write_ledger(doc, tmp_path / "ledger.json")
    mp = mp_mod.from_ledger(out)
    assert mp.cg_m[0] == pytest.approx(0.0, abs=1e-5)                     # sized to the target (balance rounded to 0.1 g)
    assert bal["mass_kg"] > 0
    assert np.allclose(mp.fuel_cg_m, doc["fuel"]["cg_m"])
    art = mp_mod.to_artifact(mp, aircraft_name="t", geometry_rev="A", geometry_sha256="0" * 64)
    assert art["fuel"]["cg_m"] == pytest.approx([0.05, 0.0, -0.04])


def test_unmatched_override_is_an_error(export, tmp_path):
    ov = json.loads(export[1].read_text())
    ov["density_overrides"][0]["body"] = "nope"
    q = tmp_path / "bad.json"
    q.write_text(json.dumps(ov))
    with pytest.raises(mf.FusionExportError, match="matched nothing"):
        mf.build_ledger(export[0], q)


def test_committed_icarus_ledger_regenerates_byte_for_byte():
    """The ledger of record is a function of the committed export + overrides — drift in any of
    the three (or in this module) shows up here."""
    d = ROOT / "projects" / "icarus" / "massprops"
    doc = mf.build_ledger(d / "fusion" / "bodies-2026-08-18.psv", d / "fusion-overrides.json")
    assert canonical_json.dumps(doc) == (d / "ledger.json").read_text(encoding="utf-8").rstrip("\n") or \
        canonical_json.dumps(doc) == (d / "ledger.json").read_text(encoding="utf-8")


def test_icarus_ledger_numbers_are_the_documented_ones():
    """Pins the physical content: dry Fusion mass, sized balance, fuel block, CG at the target."""
    d = ROOT / "projects" / "icarus" / "massprops"
    mp = mp_mod.from_ledger(d / "ledger.json")
    doc = json.loads((d / "ledger.json").read_text())
    fusion = [c for c in mp.components if c["name"].startswith("fusion:")]
    assert sum(c["mass_kg"] for c in fusion) == pytest.approx(19.300, abs=0.01)   # servo + tail-plate fixes applied
    # The dry CG lands 1.9 mm aft of the datum on its own — forward of the −5 mm balance target,
    # so the generator sizes the forward equipment/ballast mass to ZERO and omits the entry.
    assert mp.cg_m[0] == pytest.approx(-0.0019, abs=5e-4)
    assert not any(c["name"] == "forward_equipment_and_ballast" for c in mp.components)
    assert abs(mp.cg_m[1]) < 0.001                                                 # mirrored spar
    assert doc["fuel"]["volume_l"] == pytest.approx(3.91, abs=0.01)
    assert doc["fuel"]["mass_full_kg"] == pytest.approx(3.128, abs=0.005)
    assert doc["fuel"]["cg_m"][0] == pytest.approx(0.060, abs=0.002)               # 60 mm ahead of the datum
    tails = [c for c in fusion if c["name"].startswith("fusion:sigh")]
    assert len(tails) == 2 and all(0.35 < c["mass_kg"] < 0.45 for c in tails)      # 0.39 kg each, not 1.24
