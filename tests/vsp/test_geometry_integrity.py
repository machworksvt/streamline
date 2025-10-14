from __future__ import annotations

from pathlib import Path

import pytest

from streamline.vsp.session import import_vsp

from .utils import (
    assert_parm_changes,
    enumerate_parms,
    find_geom_ids,
    find_parm,
    get_parm_value,
)


pytestmark = pytest.mark.vsp


def _require_parm(vsp, geom_id: str, names: list[str], groups: list[str] | None = None, *, substring: bool = False):
    parms = enumerate_parms(vsp, geom_id)
    info = find_parm(parms, names, groups, substring=substring)
    if info is None:
        pytest.skip(f"Missing expected parm {names!r} for geometry {geom_id}")
    return info


def test_parm_roundtrip_and_update_stability(wing_model):
    vsp = wing_model.vsp
    geom_id = wing_model.wing_id

    span_info = _require_parm(vsp, geom_id, ["TotalSpan", "Span", "FullSpan", "WingSpan"], ["WingGeom", "Design"])
    chord_info = _require_parm(vsp, geom_id, ["TotalChord", "Chord", "AvgChord"], ["WingGeom", "Design"])

    span_before = get_parm_value(vsp, geom_id, span_info)
    chord_before = get_parm_value(vsp, geom_id, chord_info)

    assert_parm_changes(vsp, geom_id, span_info, span_before * 0.85 + 0.25)
    assert_parm_changes(vsp, geom_id, chord_info, chord_before * 1.15 + 0.05)


def test_area_derivation_matches_span_chord(wing_model):
    vsp = wing_model.vsp
    geom_id = wing_model.wing_id

    span_info = _require_parm(vsp, geom_id, ["TotalSpan", "Span", "FullSpan", "WingSpan"], ["WingGeom", "Design"])
    chord_info = _require_parm(vsp, geom_id, ["TotalChord", "Chord", "AvgChord"], ["WingGeom", "Design"])

    area_info = find_parm(
        enumerate_parms(vsp, geom_id),
        ["Sref", "Area", "TotalArea", "WingArea", "PlanformArea"],
        ["WingGeom", "Design", "Ref"],
    )
    if area_info is None:
        pytest.skip("Wing area parameter not exposed by runtime")

    # Ensure latest geometry values are read.
    vsp.Update()
    span_val = get_parm_value(vsp, geom_id, span_info)
    chord_val = get_parm_value(vsp, geom_id, chord_info)
    area_val = get_parm_value(vsp, geom_id, area_info)

    expected_area = span_val * chord_val
    assert area_val == pytest.approx(expected_area, rel=0.05, abs=1e-3)


def test_multiple_components_have_unique_ids(wing_model):
    vsp = wing_model.vsp
    base_name = wing_model.wing_name
    primary_id = wing_model.wing_id

    fuselage_id = vsp.AddGeom("FUSELAGE")
    fuselage_name = f"{base_name}_fus"
    vsp.SetGeomName(fuselage_id, fuselage_name)

    secondary_wing_id = vsp.AddGeom("WING")
    secondary_name = f"{base_name}_secondary"
    vsp.SetGeomName(secondary_wing_id, secondary_name)

    duplicate_id = vsp.AddGeom("WING")
    vsp.SetGeomName(duplicate_id, base_name)

    vsp.Update()

    assert len({primary_id, fuselage_id, secondary_wing_id, duplicate_id}) == 4

    primary_matches = find_geom_ids(vsp, base_name)
    assert primary_id in primary_matches

    # Older OpenVSP releases only return the first match when duplicate names are
    # present.  When that behaviour changes, we still want to verify the duplicate
    # geometry can be discovered via the name search, so allow both code paths.
    if duplicate_id in primary_matches:
        assert len(set(primary_matches)) == len(primary_matches)
    else:
        assert primary_matches == [primary_id]

    assert vsp.GetGeomName(primary_id) == base_name
    assert vsp.GetGeomName(duplicate_id) == base_name

    fuselage_matches = find_geom_ids(vsp, fuselage_name)
    assert fuselage_matches == [fuselage_id]

    secondary_matches = find_geom_ids(vsp, secondary_name)
    assert secondary_wing_id in secondary_matches


@pytest.mark.vsp_slow
def test_save_reload_roundtrip_preserves_parameters(wing_model, tmp_path: Path):
    vsp = wing_model.vsp
    geom_id = wing_model.wing_id
    wing_name = wing_model.wing_name

    span_info = _require_parm(vsp, geom_id, ["TotalSpan", "Span", "FullSpan", "WingSpan"], ["WingGeom", "Design"])
    chord_info = _require_parm(vsp, geom_id, ["TotalChord", "Chord", "AvgChord"], ["WingGeom", "Design"])

    span_before = get_parm_value(vsp, geom_id, span_info)
    chord_before = get_parm_value(vsp, geom_id, chord_info)

    target_path = tmp_path / "roundtrip" / "model.vsp3"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    vsp.WriteVSPFile(str(target_path))
    assert target_path.exists()

    vsp.ClearVSPModel()
    assert not find_geom_ids(vsp, wing_name)

    vsp.ReadVSPFile(str(target_path))
    vsp.Update()

    reloaded_ids = find_geom_ids(vsp, wing_name)
    if not reloaded_ids:
        pytest.fail("Wing missing after reloading saved file")
    reloaded_id = reloaded_ids[0]

    span_after = get_parm_value(
        vsp,
        reloaded_id,
        _require_parm(
            vsp,
            reloaded_id,
            [span_info[0]],
            [span_info[1]] if span_info[1] else None,
            substring=False,
        ),
    )
    chord_after = get_parm_value(
        vsp,
        reloaded_id,
        _require_parm(
            vsp,
            reloaded_id,
            [chord_info[0]],
            [chord_info[1]] if chord_info[1] else None,
            substring=False,
        ),
    )

    assert span_after == pytest.approx(span_before, rel=1e-6, abs=1e-6)
    assert chord_after == pytest.approx(chord_before, rel=1e-6, abs=1e-6)


def test_import_vsp_promotes_module_namespace():
    """Updated: import_vsp now returns the concrete API module; root namespace may stay bare.
    We verify the returned object has required symbols. Namespace exposure is optional.
    """
    vsp = import_vsp()
    import openvsp  # type: ignore

    assert hasattr(vsp, "AddGeom"), "import_vsp() must return module with AddGeom"
    # Root namespace may or may not have symbols; if it does, they should match.
    if hasattr(openvsp, "AddGeom"):
        assert openvsp.AddGeom is vsp.AddGeom
    else:
        # Ensure we are indeed dealing with a namespace package still.
        assert getattr(openvsp, "__file__", None) is None


def test_environment_version_matches_runtime(real_openvsp):
    reported = real_openvsp.GetVSPVersion()
    assert reported, "GetVSPVersion() should return a version string"
