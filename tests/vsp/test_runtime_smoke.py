from __future__ import annotations


def test_openvsp_reports_version(real_openvsp):
    version = real_openvsp.GetVSPVersion()
    assert version
    assert isinstance(version, str)
    normalized = version.split(" ", 1)[1] if version.lower().startswith("openvsp ") else version
    assert normalized.startswith("3.")
