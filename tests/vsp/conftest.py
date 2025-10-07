from __future__ import annotations

import os

import pytest

from streamline.vsp.test_factory import _FakeOpenVSP, import_openvsp

_ALLOWED_STUB_VALUES = {"1", "true", "yes", "on"}


def _stub_allowed() -> bool:
    value = os.getenv("STREAMLINE_ALLOW_VSP_STUB")
    if value is None:
        return True
    return value.strip().lower() in _ALLOWED_STUB_VALUES


@pytest.fixture(scope="session")
def real_openvsp():
    try:
        vsp_module = import_openvsp()
    except RuntimeError as exc:
        if _stub_allowed():
            pytest.skip(f"OpenVSP runtime unavailable: {exc}")
        raise

    if isinstance(vsp_module, _FakeOpenVSP) or getattr(vsp_module, "__streamline_is_stub__", False):
        reason = getattr(vsp_module, "__streamline_stub_reason__", "stub")
        if _stub_allowed():
            if reason:
                pytest.skip(f"OpenVSP runtime unavailable (stub: {reason})")
            pytest.skip("OpenVSP runtime unavailable (stub)")
        pytest.fail("OpenVSP runtime not installed. Set STREAMLINE_ALLOW_VSP_STUB=1 to allow stubbed tests.")

    return vsp_module
