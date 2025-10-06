# streamline/vsp/session.py
from __future__ import annotations
import os, sys, time
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class VSPContext:
    vsp: object
    versions: Dict[str, str]

class VSPSessionError(RuntimeError): ...

def _with_clean_argv(importer):
    """
    Some OpenVSP/Qt glue inspects sys.argv on import and chokes on our CLI tokens (e.g., 'smoke').
    Temporarily replace sys.argv with just the script name.
    """
    saved = sys.argv[:]
    try:
        sys.argv = [saved[0]]
        return importer()
    finally:
        sys.argv = saved

def _try_import_openvsp_graphics_once(load_graphics: bool | None, load_facade: bool | None):
    def _do():
        if load_graphics is not None or load_facade is not None:
            import openvsp_config
            if load_graphics is not None:
                openvsp_config.LOAD_GRAPHICS = bool(load_graphics)
            if load_facade is not None:
                openvsp_config.LOAD_FACADE = bool(load_facade)
        import openvsp as _vsp
        return _vsp
    return _with_clean_argv(_do)

def _import_openvsp_graphics():
    """
    Try to load the graphics+facade build per OpenVSP guidance.
    Fallbacks to plain 'openvsp' or legacy 'vsp' if not available.
    """
    tried = []

    # Preferred: graphics + facade
    try:
        vsp = _try_import_openvsp_graphics_once(load_graphics=True, load_facade=True)
        tried.append("openvsp_config(graphics+facade)+openvsp")
        return vsp, tried
    except Exception as e:
        tried.append(f"openvsp_config+openvsp failed: {e!r}")

    # Next: graphics only
    try:
        vsp = _try_import_openvsp_graphics_once(load_graphics=True, load_facade=None)
        tried.append("openvsp_config(graphics)+openvsp")
        return vsp, tried
    except Exception as e:
        tried.append(f"openvsp_config(graphics)+openvsp failed: {e!r}")

    # Plain package name
    try:
        def _plain():
            import openvsp as _vsp
            return _vsp
        vsp = _with_clean_argv(_plain)
        tried.append("openvsp (plain)")
        return vsp, tried
    except Exception as e:
        tried.append(f"openvsp failed: {e!r}")

    # Legacy module name
    try:
        def _legacy():
            import vsp as _vsp
            return _vsp
        vsp = _with_clean_argv(_legacy)
        tried.append("vsp (legacy)")
        return vsp, tried
    except Exception as e:
        tried.append(f"vsp failed: {e!r}")

    raise VSPSessionError("Could not import OpenVSP Python module. Attempts: " + " | ".join(tried))

def import_vsp() -> object:
    vsp, _ = _import_openvsp_graphics()
    return vsp

def _call_if_exists(vsp, name: str, *args, **kwargs):
    if hasattr(vsp, name):
        return getattr(vsp, name)(*args, **kwargs)
    return None

def start_gui(vsp) -> None:
    _call_if_exists(vsp, "EnableStopGUIMenuItem")
    launched = False
    for name in ("StartGUI", "StartGui"):
        if hasattr(vsp, name):
            try:
                getattr(vsp, name)()
                launched = True
                break
            except Exception:
                pass
    if launched:
        time.sleep(0.2)
    else:
        raise VSPSessionError("StartGUI/StartGui not found or failed to launch. Is the graphics build loaded?")

def lock_gui(vsp) -> None:
    _call_if_exists(vsp, "Lock")

def unlock_gui(vsp) -> None:
    _call_if_exists(vsp, "Unlock")
    _call_if_exists(vsp, "UpdateGUI")

def init_context(open_gui: bool = False) -> VSPContext:
    vsp, tried = _import_openvsp_graphics()
    versions = {"openvsp_api": getattr(vsp, "OPENVSP_VERSION", "unknown")}
    if open_gui:
        start_gui(vsp)
    return VSPContext(vsp=vsp, versions=versions)
