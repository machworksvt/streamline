"""Test plumbing.

There is no stub OpenVSP and there will not be one (Master Plan §8.9 #3): a suite that goes green
without the solver is a suite that measures nothing about the solver. Tests that need the bindings
take the `session` fixture; if the bindings are missing the fixture FAILS with the reason, it does
not skip. Set STREAMLINE_ALLOW_MISSING_VSP=1 to turn those failures into skips on a machine that is
deliberately not the flake — never in CI.
"""

from __future__ import annotations

import os

import pytest

from streamline.vsp import session as session_mod


@pytest.fixture(scope="session")
def session():
    try:
        return session_mod.require_openvsp()
    except session_mod.OpenVSPMissing as e:
        if os.environ.get("STREAMLINE_ALLOW_MISSING_VSP") == "1":
            pytest.skip(f"OpenVSP bindings missing and STREAMLINE_ALLOW_MISSING_VSP=1: {e}")
        pytest.fail(f"OpenVSP bindings are required (run inside `nix develop`): {e}")
