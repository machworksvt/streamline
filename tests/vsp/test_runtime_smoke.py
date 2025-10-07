from __future__ import annotations


def test_openvsp_reports_version(real_openvsp):
    version = real_openvsp.VSPVersion()
    assert version
    assert isinstance(version, str)
    assert version.startswith("3.")
