from __future__ import annotations

from pathlib import Path

from streamline.vsp.test_factory import build_basic_transport


def test_import_openvsp_returns_module(real_openvsp):
    assert hasattr(real_openvsp, "ClearVSPModel")


def test_build_basic_transport(tmp_path: Path, real_openvsp):
    model_path = tmp_path / "ci_model.vsp3"
    results = build_basic_transport(output_path=model_path)

    assert model_path.exists()
    assert results["model_name"].startswith("streamline_test")
    assert results["sref"] > 0.0
    assert results["bref"] > 0.0
    assert results["cref"] > 0.0

    # Validate geometry lookup if API available; support builds requiring index argument.
    if hasattr(real_openvsp, "FindGeom"):
        try:
            geom_ids = real_openvsp.FindGeom(results["wing_name"])  # standard documented form
        except TypeError:
            # Some builds expect (name, index)
            geom_ids = real_openvsp.FindGeom(results["wing_name"], 0)
        assert geom_ids

    # No redundant WriteVSPFile after ClearVSPModel; build_basic_transport already wrote the file.
    # Simple cleanup without exporting an empty model.
    if hasattr(real_openvsp, "ClearVSPModel"):
        real_openvsp.ClearVSPModel()
