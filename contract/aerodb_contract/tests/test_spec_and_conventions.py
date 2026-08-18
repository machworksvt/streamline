"""spec.md is generated and current; conventions.md mentions every machine-readable convention."""

from pathlib import Path

from aerodb_contract import conventions as cv, spec

HERE = Path(__file__).resolve().parents[1]


def test_spec_md_is_current():
    committed = (HERE / "spec.md").read_text(encoding="utf-8")
    assert committed == spec.render(), "spec.md is stale — run `make spec` and commit the result"


def test_conventions_md_covers_the_dict():
    md = (HERE / "conventions.md").read_text(encoding="utf-8")
    for s in cv.SURFACES:
        assert s in md, s
    for needle in ("FRD", "trailing-edge down", "atan2(w, u)", "asin(v / V)", "p b / 2V", "moment_reference_point_m",
                   "flap_rad", "X_FRD = −X_vsp"):
        assert needle in md, needle


def test_flaps_are_not_control_surfaces():
    assert not any(s.startswith("flap") for s in cv.CONTROL_SURFACES)
    assert set(cv.CONTROL_SURFACES) < set(cv.SURFACES)
