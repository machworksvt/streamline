"""OpenVSP session management and integration helpers."""

from __future__ import annotations

import importlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Any

from ..core.errors import VSPSessionError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _set_graphics_flags(enable: bool) -> None:
    """Set OpenVSP loader flags before importing the module."""
    try:
        import openvsp_config  # type: ignore

        openvsp_config.LOAD_FACADE = bool(enable)
        openvsp_config.LOAD_GRAPHICS = bool(enable)
        if hasattr(openvsp_config, "LOAD_MULTI_FACADE"):
            # Explicitly disable multi facade so single GUI loads reliably
            openvsp_config.LOAD_MULTI_FACADE = False
    except Exception:
        # If the config shim is unavailable we continue; import will fall back
        pass


def _prepend_env_path(var: str, value: str) -> None:
    current = os.environ.get(var)
    if not current:
        os.environ[var] = value
        return
    if value in current.split(os.pathsep):
        return
    os.environ[var] = f"{value}{os.pathsep}{current}"


def _ensure_vendor_paths() -> None:
    """Add bundled OpenVSP python/bin directories to sys.path and PATH.

    Allows invoking Streamline from terminals that haven't explicitly set
    PYTHONPATH/PATH for the vendor bundle.
    """
    repo_root = Path(__file__).resolve().parents[2]
    candidates: list[Path] = []
    env_root = os.environ.get("OPENVSP_ROOT")
    if env_root:
        root_path = Path(env_root).expanduser()
        if root_path.exists():
            candidates.append(root_path)
    # Heuristic: prefer newest-looking OpenVSP-* directory under repo root
    for child in sorted(repo_root.glob("OpenVSP-*"), reverse=True):
        if child.is_dir():
            candidates.append(child)
    seen_python = False
    modules_cleared = False
    for root in candidates:
        python_dir = root / "python"
        if not python_dir.exists():
            continue
        # Inject python directories
        extras = (
            python_dir,
            python_dir / "openvsp",
            python_dir / "openvsp_config",
            python_dir / "utilities",
            python_dir / "utilities" / "utilities",
        )
        for extra in reversed(extras):
            if extra.exists():
                path_str = str(extra)
                if path_str not in sys.path:
                    sys.path.insert(0, path_str)
        # Ensure DLLs are discoverable
        bin_dir = root / "bin"
        if bin_dir.exists():
            _prepend_env_path("PATH", str(bin_dir))
        seen_python = True
        # Purge any pre-imported stubs so the real bindings win on next import
        for name in list(sys.modules.keys()):
            if name == "openvsp" or name.startswith("openvsp."):
                sys.modules.pop(name, None)
                modules_cleared = True
            if name == "utilities" or name.startswith("utilities."):
                sys.modules.pop(name, None)
        break
    if not seen_python:
        logger.debug("OpenVSP vendor bundle python directory not found; relying on environment")
    else:
        if modules_cleared:
            logger.debug("Cleared cached openvsp/utilities modules to ensure vendor bindings load")
        # Guarantee the vendor utilities package is importable as `utilities`
        try:
            vendor_utilities = importlib.import_module("utilities.utilities")
        except ModuleNotFoundError:
            pass
        else:
            sys.modules.setdefault("utilities.utilities", vendor_utilities)
            sys.modules["utilities"] = vendor_utilities


_ensure_vendor_paths()


@dataclass
class VSPContext:
    vsp: object
    versions: Dict[str, str]


def _with_clean_argv(importer):
    """Temporarily hide CLI arguments that upset the OpenVSP Qt bootstrap."""

    saved = sys.argv[:]
    try:
        sys.argv = [saved[0]]
        return importer()
    finally:
        sys.argv = saved


def _import_with_flags(load_graphics: bool | None):
    def _do():
        if load_graphics is not None:
            _set_graphics_flags(bool(load_graphics))
        import openvsp as _vsp

        return _vsp

    return _with_clean_argv(_do)


def _import_openvsp_graphics(attempt_graphics: bool):
    """Attempt to load OpenVSP."""

    attempts: list[tuple[str, bool | None]] = []
    if attempt_graphics:
        attempts.append(("openvsp (graphics)", True))
    attempts.append(("openvsp (default)", None))
    attempts.append(("openvsp (headless)", False))

    tried: list[str] = []
    for label, load_flag in attempts:
        try:
            vsp = _import_with_flags(load_flag)
            tried.append(label)
            logger.debug("Loaded OpenVSP", context={"mode": label})
            return vsp, tried
        except Exception as exc:
            tried.append(f"{label} failed: {exc!r}")
            logger.debug("OpenVSP import attempt failed", context={"mode": label}, hint=str(exc))

    err = VSPSessionError(
        "Could not import OpenVSP Python module",
        context={"attempts": tried},
        hint="Verify that OpenVSP is installed and that its DLLs are discoverable via PATH.",
    )
    logger.error(err.message, context=err.context, code=err.code, hint=err.hint)
    raise err


def import_vsp(*, allow_graphics: bool = False, launch_gui: bool = False) -> object:
    """Return the validated OpenVSP API module.

    allow_graphics=False (default) ensures headless-friendly import for tests.
    allow_graphics=True attempts to load a graphics-capable binding but does NOT
    auto-launch the GUI unless launch_gui=True.
    """
    vsp_root, _ = _import_openvsp_graphics(allow_graphics)
    if launch_gui:
        start_gui(vsp_root, strict=False)
    return vsp_root


def _call_if_exists(vsp, name: str, *args, **kwargs):
    if hasattr(vsp, name):
        return getattr(vsp, name)(*args, **kwargs)
    return None


def supports_gui(vsp) -> bool:
    # Require both start symbol and a positive IsGUIBuild() when available.
    if vsp is None:
        return False
    has_start = any(hasattr(vsp, attr) for attr in ("StartGUI", "StartGui"))
    if not has_start:
        return False
    return True


# Diagnostic helper to inspect environment and attempt GUI relaunch

def ensure_gui_started(vsp, *, strict: bool = False):  # pragma: no cover - side-effect
    if vsp is None:
        logger.warning("ensure_gui_started received None; attempting lazy init_context")
        try:
            ctx = init_context(open_gui=True, strict_gui=strict)
            vsp = ctx.vsp
        except Exception as exc:
            logger.error("Lazy init_context failed", hint=str(exc))
            return False
    if is_headless(vsp):
        logger.info("Skipping GUI start: headless binding detected")
        return False
    _set_graphics_flags(True)
    try:
        import openvsp_config  # type: ignore
        load_graphics = getattr(openvsp_config, 'LOAD_GRAPHICS', None)
        load_facade = getattr(openvsp_config, 'LOAD_FACADE', None)
    except Exception:
        load_graphics = load_facade = 'unavailable'
    has_startgui = hasattr(vsp, 'StartGUI')
    has_startgui_alt = hasattr(vsp, 'StartGui')
    path_head = os.environ.get('PATH', '').split(os.pathsep)[:8]
    logger.info(
        "GUI startup diagnostics",
        context={
            'has_StartGUI': has_startgui,
            'has_StartGui': has_startgui_alt,
            'supports_gui()': supports_gui(vsp),
            'openvsp_config.LOAD_GRAPHICS': load_graphics,
            'openvsp_config.LOAD_FACADE': load_facade,
            'PATH_head': path_head,
            'strict': strict,
        },
    )
    if not supports_gui(vsp):
        logger.warning("OpenVSP graphics symbols not present; cannot start GUI")
        return False
    return start_gui(vsp, strict=strict)


# --- GUI helpers (revised with InitGUI pre-call) ---

def _maybe_init_gui(vsp):
    """Call InitGUI/InitGui exactly once if provided by the binding."""
    try:
        if getattr(vsp, '_STREAMLINE_GUI_INIT_DONE', False):
            return
        for init_name in ("InitGUI", "InitGui"):
            if hasattr(vsp, init_name):
                try:
                    getattr(vsp, init_name)()
                    logger.debug("Invoked init routine before GUI start", context={'symbol': init_name})
                    break
                except Exception as exc:  # pragma: no cover
                    logger.warning("InitGUI call failed", context={'symbol': init_name}, hint=str(exc))
        try:
            setattr(vsp, '_STREAMLINE_GUI_INIT_DONE', True)
        except Exception:
            pass
    except Exception:
        pass


def start_gui(vsp, *, strict: bool = False, block: bool = False, hold_seconds: float | None = None) -> bool:
    """Attempt to start the OpenVSP GUI.

    strict: raise on failure instead of warning.
    block: if True and StartGUI returns immediately, optionally hold the process
           (useful for manual diagnostics when GUI is expected but not shown).
    hold_seconds: optional override for how long to sleep when block=True and
                  StartGUI returned without raising (default 8s).
    """
    gui_build = None
    if hasattr(vsp, 'IsGUIBuild'):
        try:
            gui_build = bool(vsp.IsGUIBuild())
        except Exception:
            gui_build = None
    logger.info(
        "Starting OpenVSP GUI",
        context={
            'strict': strict,
            'has_StartGUI': hasattr(vsp, 'StartGUI'),
            'has_StartGui': hasattr(vsp, 'StartGui'),
            'has_InitGUI': hasattr(vsp, 'InitGUI') or hasattr(vsp, 'InitGui'),
            'IsGUIBuild': gui_build,
        },
    )
    if gui_build is False:
        msg = "Binding reports IsGUIBuild()==False; attempting GUI start anyway"
        logger.warning(msg)

    _call_if_exists(vsp, "EnableStopGUIMenuItem")
    _maybe_init_gui(vsp)

    launched = False
    launch_exc: Optional[Exception] = None
    for name in ("StartGUI", "StartGui"):
        if hasattr(vsp, name):
            try:
                getattr(vsp, name)()
                launched = True
                logger.debug("Invoked GUI start", context={'symbol': name})
                if hasattr(vsp, "EnableStopGUIMenuItem"):
                    _call_if_exists(vsp, "EnableStopGUIMenuItem")
                break
            except Exception as exc:  # pragma: no cover
                launch_exc = exc
                logger.warning(
                    "GUI launch attempt failed", context={'symbol': name}, hint=str(exc)
                )
    if launched:
        # Provide a small delay so the window has time to surface when called from short-lived scripts.
        if block:
            import time as _t
            sleep_for = hold_seconds if hold_seconds is not None else 8.0
            logger.debug("Blocking after StartGUI to keep process alive", context={'seconds': sleep_for})
            try:
                _t.sleep(max(0.1, float(sleep_for)))
            except Exception:
                pass
        logger.info("OpenVSP GUI launch reported success")
        return True

    msg = "OpenVSP GUI not available (graphics build or StartGUI symbol missing)"
    if launch_exc:
        msg = f"GUI launch failed: {launch_exc}"
    if strict:
        err = VSPSessionError("StartGUI/StartGui not found or failed to launch", hint=msg)
        logger.error(err.message, code=err.code, hint=err.hint)
        raise err
    logger.warning(msg)
    return False


def force_graphics_reimport() -> object | None:
    """Attempt to discard existing headless binding and re-import with graphics enabled.
    Returns the new vsp module (graphics) or None if unsuccessful.
    """
    try:
        import sys as _sys
        # Remove known modules to force a fresh import path resolution
        for name in list(_sys.modules):
            if name == 'openvsp' or name.startswith('openvsp.'):
                _sys.modules.pop(name, None)
        # Re-import with graphics allowed
        v = import_vsp(allow_graphics=True, launch_gui=False)  # type: ignore
        if supports_gui(v):
            logger.info("force_graphics_reimport succeeded", context={'IsGUIBuild': getattr(v, 'IsGUIBuild', lambda: None)() if hasattr(v, 'IsGUIBuild') else None})
        else:
            logger.warning("force_graphics_reimport did not obtain GUI-capable binding")
        return v
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("force_graphics_reimport failed", hint=str(exc))
        return None


def lock_gui(vsp) -> None:
    logger.debug("Locking OpenVSP GUI")
    _call_if_exists(vsp, "Lock")


def unlock_gui(vsp) -> None:
    logger.debug("Unlocking OpenVSP GUI")
    _call_if_exists(vsp, "Unlock")
    _call_if_exists(vsp, "UpdateGUI")


def init_context(load_graphics: bool = False, *, launch_gui: bool = False, strict_gui: bool = False) -> VSPContext:
    """Initialize and cache an OpenVSP context.

    load_graphics controls whether we attempt graphics-capable binding import.
    launch_gui controls whether the GUI is immediately started (not desired for most
    automated flows; the TUI or smoke CLI can opt-in separately).
    """
    vsp_root, tried = _import_openvsp_graphics(load_graphics)
    api = vsp_root
    versions = {"openvsp_api": getattr(api, "OPENVSP_VERSION", "unknown")}
    logger.info(
        "Initialized OpenVSP context",
        context={"graphics": load_graphics, "launch_gui": launch_gui, "version": versions["openvsp_api"], "attempts": tried},
    )
    if launch_gui:
        start_gui(api, strict=strict_gui)
    globals()['_ACTIVE_VSP'] = api
    globals()['vsp'] = api
    return VSPContext(vsp=api, versions=versions)


# --- Accessor added for configuration capture integration ---
if 'get_vsp' not in globals():
    def get_vsp():  # pragma: no cover
        gv = globals().get('_ACTIVE_VSP')
        if gv is not None:
            return gv
        # Lazy fallback: attempt import & validation; let errors propagate (A)
        v = import_vsp()
        globals()['_ACTIVE_VSP'] = v
        globals()['vsp'] = v
        return v

# New strict accessor for callers needing explicit assurance
def require_vsp():  # pragma: no cover
    v = get_vsp()
    if v is None:
        raise VSPSessionError("OpenVSP context unavailable after import attempt")
    return v

# Headless detection utility (D)
def is_headless(vsp) -> bool:
    if vsp is None:
        return True
    return not any(hasattr(vsp, attr) for attr in ("WriteVSPFile", "AddGeom", "Update"))

