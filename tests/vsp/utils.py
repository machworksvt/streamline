from __future__ import annotations

def assert_has_minimal_api(vsp):
    required = ["AddGeom", "Update", "SetGeomName"]
    missing = [r for r in required if not hasattr(vsp, r)]
    if missing:
        raise AssertionError(f"OpenVSP module missing expected symbols: {missing}")