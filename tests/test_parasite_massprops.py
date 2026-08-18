"""Parasite drag against Schlichting, and the massprops ledger against hand arithmetic."""

import json
import math

import numpy as np
import pytest

from streamline import atmosphere as atm, massprops
from streamline.vsp import geometry as geom_mod, parasite, reference


# --- parasite drag ----------------------------------------------------------------------------

@pytest.mark.vsp
@pytest.mark.slow
def test_skin_friction_matches_schlichting_and_the_buildup_reconciles(session, tmp_path):
    """The check the user asked for by name: OpenVSP's skin-friction settings pinned together —
    Cf(Re) against the Schlichting correlation, the FF·Cf·Swet/Sref bookkeeping, and the SI units
    (a ft/s VelocityUnit slip moves Re by 3.28x and fails the Cf band)."""
    api = session.api
    wing = reference.flat_rectangular_wing(session, span_m=2.0, chord_m=0.25)
    path = tmp_path / "w.vsp3"
    api.WriteVSPFile(str(path), api.SET_ALL)
    geometry = geom_mod.enumerate_model(session, path)

    s = atm.isa(533.4)
    V = 30.0
    with session.workdir(tmp_path):
        ov = parasite.parasite_overrides(session, geometry, airspeed_m_s=V, mach=s.mach(V),
                                         reynolds_per_m=s.reynolds_per_length(V), wing_id=wing.geom_id)
        res = parasite.run_parasite(session, geometry, overrides=ov)

    assert res.sref_m2 == pytest.approx(wing.area_m2, rel=1e-6)
    assert len(res.components) == 1
    c = res.components[0]
    # Re on the component's own reference length, from OUR atmosphere
    assert c.reynolds == pytest.approx(s.reynolds_per_length(V) * c.lref_m, rel=1e-3)
    # Schlichting compressible ≈ 0.455/log10(Re)^2.58 at negligible Mach
    cf_theory = 0.455 / math.log10(c.reynolds) ** 2.58
    assert c.cf == pytest.approx(cf_theory, rel=0.03), (c.cf, cf_theory)
    # and the total is exactly the buildup
    assert res.cd0_total == pytest.approx(sum(x.f_m2 for x in res.components) / res.sref_m2, rel=1e-9)
    assert 0.005 < res.cd0_total < 0.03, "a bare-wing CD0 in a sane band"


# --- massprops ledger -------------------------------------------------------------------------

def _write_ledger(tmp_path, comps):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"components": comps}), encoding="utf-8")
    return p


def test_two_point_masses_give_the_textbook_cg_and_inertia(tmp_path):
    p = _write_ledger(tmp_path, [
        {"name": "a", "mass_kg": 1.0, "cg_m": [1.0, 0.0, 0.0], "source": "test"},
        {"name": "b", "mass_kg": 1.0, "cg_m": [-1.0, 0.0, 0.0], "source": "test"},
    ])
    mp = massprops.from_ledger(p)
    assert mp.mass_kg == 2.0
    assert mp.cg_m == pytest.approx([0.0, 0.0, 0.0])
    # two unit masses at ±1 m on X: Ixx = 0, Iyy = Izz = 2
    assert np.diag(mp.inertia_kg_m2) == pytest.approx([0.0, 2.0, 2.0])


def test_shapes_add_their_local_inertia_with_parallel_axis(tmp_path):
    p = _write_ledger(tmp_path, [
        {"name": "box", "mass_kg": 12.0, "cg_m": [0.0, 0.0, 0.0],
         "shape": {"kind": "box", "extents_m": [1.0, 1.0, 1.0]}, "source": "test"},
    ])
    mp = massprops.from_ledger(p)
    # cube: I = m/12·(2 a^2) each axis = 12/12·2 = 2
    assert np.diag(mp.inertia_kg_m2) == pytest.approx([2.0, 2.0, 2.0])
    p2 = _write_ledger(tmp_path, [
        {"name": "cyl", "mass_kg": 2.0, "cg_m": [0.0, 0.0, 0.0],
         "shape": {"kind": "cylinder", "axis": "x", "radius_m": 0.1, "length_m": 0.5}, "source": "test"},
    ])
    mp2 = massprops.from_ledger(p2)
    assert mp2.inertia_kg_m2[0, 0] == pytest.approx(0.5 * 2.0 * 0.01)


def test_the_artifact_round_trips_through_the_contract(tmp_path):
    p = _write_ledger(tmp_path, [
        {"name": "structure", "mass_kg": 8.0, "cg_m": [-0.6, 0.0, 0.0], "source": "estimate"},
        {"name": "engine", "mass_kg": 1.7, "cg_m": [-1.1, 0.0, 0.05], "source": "datasheet"},
        {"name": "fuel", "mass_kg": 3.6, "cg_m": [-0.55, 0.0, 0.02],
         "shape": {"kind": "box", "extents_m": [0.4, 0.2, 0.15]}, "source": "estimate"},
    ])
    mp = massprops.from_ledger(p)
    doc = massprops.to_artifact(mp, aircraft_name="icarus", geometry_rev="A",
                                geometry_sha256="0" * 64)
    from aerodb_contract import MassProps as ContractMP
    loaded = ContractMP.from_doc(doc)
    assert loaded.mass_kg == pytest.approx(13.3)
    assert loaded.doc["provenance"]["ledger_sha256"] == mp.ledger_sha256


def test_bad_ledgers_are_refused_with_names(tmp_path):
    with pytest.raises(massprops.LedgerError, match="missing 'source'"):
        massprops.from_ledger(_write_ledger(tmp_path, [{"name": "x", "mass_kg": 1.0, "cg_m": [0, 0, 0]}]))
    with pytest.raises(massprops.LedgerError, match="must be positive"):
        massprops.from_ledger(_write_ledger(tmp_path, [
            {"name": "x", "mass_kg": -1.0, "cg_m": [0, 0, 0], "source": "t"}]))
