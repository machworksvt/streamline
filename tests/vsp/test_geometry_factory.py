from __future__ import annotations

from pathlib import Path

import pytest

openvsp = pytest.importorskip(
    "openvsp",
    reason="OpenVSP Python bindings are required for geometry factory tests",
)

from streamline.vsp.test_factory import build_basic_transport, import_openvsp  # noqa: E402


def test_import_openvsp_returns_module():
    assert import_openvsp() is openvsp


def test_build_basic_transport(tmp_path: Path):
    model_path = tmp_path / "ci_model.vsp3"
    results = build_basic_transport(output_path=model_path)

    assert model_path.exists()
    assert results["model_name"].startswith("streamline_test")
    assert results["sref"] > 0.0
    assert results["bref"] > 0.0
    assert results["cref"] > 0.0

    # Ensure the file loads back into OpenVSP without errors
    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(model_path))
    geom_ids = openvsp.FindGeom(results["wing_name"])
    assert geom_ids
    assert openvsp.GetGeomName(geom_ids[0]) == results["wing_name"]
