from __future__ import annotations

import os

import pytest

from streamline.vsp.test_factory import import_openvsp
from streamline.core.errors import VSPSessionError

_ALLOWED_TRUTHY = {"1", "true", "yes", "on"}


def _require_real() -> bool:
    return os.getenv("STREAMLINE_REQUIRE_REAL_VSP", "").strip().lower() in _ALLOWED_TRUTHY


def _skip_or_fail(reason: str):
    if _require_real():
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def real_openvsp():
    try:
        vsp_module = import_openvsp()
    except VSPSessionError as exc:
        _skip_or_fail(f"OpenVSP runtime unavailable: {exc.message}")
    except Exception as exc:  # unexpected import failure
        _skip_or_fail(f"OpenVSP import error: {exc}")

    # Validate minimal expected API from real runtime
    expected_symbols = ["AddGeom", "ClearVSPModel"]
    if not all(hasattr(vsp_module, s) for s in expected_symbols):
        missing = [s for s in expected_symbols if not hasattr(vsp_module, s)]
        _skip_or_fail(f"OpenVSP module present but incomplete (missing: {', '.join(missing)})")

    return vsp_module
