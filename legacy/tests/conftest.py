from __future__ import annotations

import os, sys
import pytest
from pathlib import Path
from streamline.vsp import import_vsp
from streamline.core.errors import VSPSessionError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.environ.get("STREAMLINE_DEBUG_VSP"):
    print("DEBUG VSP sys.executable:", sys.executable)
    print("DEBUG VSP sys.path head:", sys.path[:8])


@pytest.fixture(scope="session")
def openvsp_runtime():
    """Return a validated OpenVSP module via canonical importer.

    Falls back to skip (or fail if STREAMLINE_REQUIRE_REAL_VSP is truthy)
    when the runtime is unavailable or incomplete.
    """
    truthy = {"1", "true", "yes", "on"}
    require_real = os.getenv("STREAMLINE_REQUIRE_REAL_VSP", "").strip().lower() in truthy
    try:
        mod = import_vsp()  # session logic handles symbol promotion/validation
        return mod
    except VSPSessionError as e:
        if require_real:
            raise RuntimeError(f"Failed to import OpenVSP runtime: {e.message}") from e
        pytest.skip(f"OpenVSP runtime unavailable: {e.message}")
    except Exception as e:  # unexpected import failure
        if require_real:
            raise RuntimeError(f"Unexpected OpenVSP import error: {e}") from e
        pytest.skip(f"OpenVSP import error: {e}")
