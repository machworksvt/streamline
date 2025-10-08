from __future__ import annotations

import os, sys, pathlib, platform, importlib
import pytest
from pathlib import Path
from streamline.vsp import import_vsp
from streamline.core.errors import VSPSessionError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_OPENVSP_ROOT = os.environ.get("OPENVSP_HOME") or os.environ.get("STREAMLINE_OPENVSP_HOME")
_PY_DIR = os.environ.get("OPENVSP_PYTHON_DIR") or os.environ.get("STREAMLINE_OPENVSP_PYTHON_DIR")


def _inject_paths():
    # Prepend python bindings directory
    if _PY_DIR and pathlib.Path(_PY_DIR).is_dir() and _PY_DIR not in sys.path:
        sys.path.insert(0, _PY_DIR)

    # Windows: add DLL search paths so the native module resolves dependencies
    if platform.system().lower().startswith("win") and _OPENVSP_ROOT:
        for sub in ["", "bin", "vspaero_ex"]:
            d = pathlib.Path(_OPENVSP_ROOT) / sub
            if d.is_dir():
                try:
                    os.add_dll_directory(str(d))
                except Exception:
                    pass

    if os.environ.get("STREAMLINE_DEBUG_VSP"):
        print("DEBUG VSP sys.executable:", sys.executable)
        print("DEBUG VSP sys.path head:", sys.path[:8])
        print("DEBUG VSP OPENVSP_HOME:", _OPENVSP_ROOT)
        print("DEBUG VSP OPENVSP_PYTHON_DIR:", _PY_DIR)


_inject_paths()


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
