from __future__ import annotations

from pathlib import Path

from streamline.vsp.test_factory import build_basic_transport, import_openvsp


def test_import_openvsp_returns_module():
    vsp_module = import_openvsp()
    assert vsp_module is not None
    assert hasattr(vsp_module, "ClearVSPModel")


def test_build_basic_transport(tmp_path: Path):
    vsp_module = import_openvsp()
    model_path = tmp_path / "ci_model.vsp3"
    results = build_basic_transport(output_path=model_path)

    assert model_path.exists()
    assert results["model_name"].startswith("streamline_test")
    assert results["sref"] > 0.0
    assert results["bref"] > 0.0
    assert results["cref"] > 0.0

    if hasattr(vsp_module, "FindGeom"):
        geom_ids = vsp_module.FindGeom(results["wing_name"])
        assert geom_ids

    vsp_module.ClearVSPModel()
    vsp_module.WriteVSPFile(str(model_path))
