"""OpenVSP session management and integration helpers."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

from ..core.errors import VSPSessionError
from ..core.logging import get_logger
from .promote import promote_full_api

logger = get_logger(__name__)


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
    """Attempt to load OpenVSP with increasingly permissive fallbacks."""

    tried = []

    try:
        vsp = _try_import_openvsp_graphics_once(load_graphics=True, load_facade=True)
        tried.append("openvsp_config(graphics+facade)+openvsp")
        logger.debug("Loaded OpenVSP with graphics+facade build")
        return vsp, tried
    except Exception as exc:  # pragma: no cover - import side effects
        tried.append(f"openvsp_config+openvsp failed: {exc!r}")
        logger.debug("Failed to load OpenVSP graphics+facade build", hint=str(exc))

    try:
        vsp = _try_import_openvsp_graphics_once(load_graphics=True, load_facade=None)
        tried.append("openvsp_config(graphics)+openvsp")
        logger.debug("Loaded OpenVSP with graphics-only build")
        return vsp, tried
    except Exception as exc:  # pragma: no cover - import side effects
        tried.append(f"openvsp_config(graphics)+openvsp failed: {exc!r}")
        logger.debug("Failed to load OpenVSP graphics-only build", hint=str(exc))

    try:
        def _plain():
            import openvsp as _vsp

            return _vsp

        vsp = _with_clean_argv(_plain)
        tried.append("openvsp (plain)")
        logger.debug("Loaded OpenVSP plain Python module")
        return vsp, tried
    except Exception as exc:  # pragma: no cover - import side effects
        tried.append(f"openvsp failed: {exc!r}")
        logger.debug("Failed to load OpenVSP plain Python module", hint=str(exc))

    try:
        def _legacy():
            import vsp as _vsp

            return _vsp

        vsp = _with_clean_argv(_legacy)
        tried.append("vsp (legacy)")
        logger.debug("Loaded legacy vsp module")
        return vsp, tried
    except Exception as exc:  # pragma: no cover - import side effects
        tried.append(f"vsp failed: {exc!r}")
        logger.debug("Failed to load legacy vsp module", hint=str(exc))

    err = VSPSessionError(
        "Could not import OpenVSP Python module",
        context={"attempts": tried},
        hint="Verify that OpenVSP is installed and on PYTHONPATH.",
    )
    logger.error(err.message, context=err.context, code=err.code, hint=err.hint)
    raise err


REQUIRED_VSP_SYMBOLS = [
    "AddGeom",
    "ClearVSPModel",
    "SetGeomName",
    "SetParmVal",
    "GetParmVal",
    "Update",
    # Extend minimal required set to include core file export used by tests
    "WriteVSPFile",
]

# Generic compiled layer promotion using promoter utility
_DEF_VERSION_ALIASES = [("VSPVersion", "GetVSPVersion"), ("VSPVersion", "OPENVSP_VERSION")]

def _promote_compiled_layer(vsp_module):
    # Promote full API from compiled submodule openvsp._vsp
    promoted = promote_full_api(
        "openvsp",
        candidates=["openvsp._vsp"],
        version_aliases=_DEF_VERSION_ALIASES,
    )
    return promoted or vsp_module

# Promote auxiliary OpenVSP ecosystem modules (best-effort / optional)
_AUX_PROMOTE = {
    "degen_geom": ["degen_geom._core", "degen_geom._degen"],
    "avlpy": ["avlpy._core", "avlpy._avl"],
}

def _promote_related():  # pragma: no cover - side-effect helper
    for mod, cands in _AUX_PROMOTE.items():
        try:
            promote_full_api(mod, candidates=cands)
        except Exception:
            pass


def _locate_api_object(vsp_module):
    """Return an object exposing the required OpenVSP API symbols.

    Some distributions place the SWIG layer or API inside a nested attribute
    (e.g. openvsp.vsp or openvsp.core). This walks shallow attributes to locate
    one that provides the full symbol set.
    """
    if all(hasattr(vsp_module, n) for n in REQUIRED_VSP_SYMBOLS):
        return vsp_module, None

    for name in dir(vsp_module):
        if name.startswith("__"):
            continue
        try:
            cand = getattr(vsp_module, name)
        except Exception:  # pragma: no cover - defensive
            continue
        if all(hasattr(cand, n) for n in REQUIRED_VSP_SYMBOLS):
            return cand, name
    return vsp_module, None  # fallback (will fail validation later)


def _validate_openvsp_module(vsp) -> object:
    """Validate the imported OpenVSP module exposes minimal expected API.

    Raises:
        VSPSessionError: if any required symbol is missing (most likely a wrong
            module on sys.path or an incomplete installation).
    """
    api_obj, attr = _locate_api_object(vsp)
    # Always attempt promotion to ensure full namespace exposure
    vsp = _promote_compiled_layer(vsp)
    api_obj, attr = _locate_api_object(vsp)
    missing = [name for name in REQUIRED_VSP_SYMBOLS if not hasattr(api_obj, name)]
    if missing:
        path = getattr(vsp, "__file__", "<unknown>")
        raise VSPSessionError(
            "Imported openvsp module is incomplete",
            context={
                "module_file": path,
                "missing": missing,
                "present_sample": [n for n in dir(vsp)[:40]],
                "resolved_subattr": attr,
                "sys_path_head": sys.path[:6],
            },
            hint=(
                "Bindings found but required symbols missing. Confirm openvsp._vsp exists and DLL paths (bin, vspaero_ex) are on PATH."
            ),
        )
    # Provide GetVSPVersion alias if only VSPVersion present
    if hasattr(api_obj, 'VSPVersion') and not hasattr(api_obj, 'GetVSPVersion'):
        try: setattr(api_obj, 'GetVSPVersion', getattr(api_obj, 'VSPVersion'))
        except Exception: pass
    # Normalize version string to raw numeric (e.g. '3.46.0')
    try:
        if hasattr(api_obj, 'GetVSPVersion'):
            _raw_ver = api_obj.GetVSPVersion()
            if isinstance(_raw_ver, str) and _raw_ver.startswith('OpenVSP '):
                _simple = _raw_ver.split()[-1]
                # wrap to always return simple
                def _gv():
                    return _simple
                try:
                    setattr(api_obj, 'GetVSPVersion', _gv)
                except Exception:
                    pass
                # Provide OPENVSP_VERSION convenience attribute if missing
                if not hasattr(api_obj, 'OPENVSP_VERSION'):
                    try: setattr(api_obj, 'OPENVSP_VERSION', _simple)
                    except Exception: pass
    except Exception:  # pragma: no cover
        pass
    # (Removed automatic FindGeom signature adapter to preserve original API)
    if api_obj is not vsp:
        # Wrap to provide direct attribute access for callers expecting top-level functions.
        class _VSPFacade:
            __wrapped__ = api_obj
            __streamline_api_subattr__ = attr
            def __getattr__(self, item):  # pragma: no cover - simple delegation
                return getattr(api_obj, item)
        logger.debug("Resolved OpenVSP API via nested attribute", context={"attr": attr, "module_file": getattr(vsp, "__file__", "<unknown>")})
        return _VSPFacade()
    logger.debug(
        "Validated OpenVSP runtime",
        context={
            "module_file": getattr(vsp, "__file__", "<unknown>"),
            "version": getattr(vsp, "OPENVSP_VERSION", getattr(vsp, "VSPVersion", lambda: "?")()),
        },
    )
    return vsp


def import_vsp() -> object:
    vsp, _ = _import_openvsp_graphics()
    # Promote auxiliary modules (non-fatal)
    _promote_related()
    return _validate_openvsp_module(vsp)


def _call_if_exists(vsp, name: str, *args, **kwargs):
    if hasattr(vsp, name):
        return getattr(vsp, name)(*args, **kwargs)
    return None


def start_gui(vsp) -> None:
    logger.info("Starting OpenVSP GUI")
    _call_if_exists(vsp, "EnableStopGUIMenuItem")
    launched = False
    for name in ("StartGUI", "StartGui"):
        if hasattr(vsp, name):
            try:
                getattr(vsp, name)()
                launched = True
                break
            except Exception as exc:  # pragma: no cover - GUI specific failure
                logger.warning(
                    "OpenVSP GUI launch method raised an exception",
                    context={"method": name},
                    hint=str(exc),
                )
    if launched:
        time.sleep(0.2)
    else:
        err = VSPSessionError(
            "StartGUI/StartGui not found or failed to launch",
            hint="Ensure the graphics build of OpenVSP is available.",
        )
        logger.error(err.message, code=err.code, hint=err.hint)
        raise err


def lock_gui(vsp) -> None:
    logger.debug("Locking OpenVSP GUI")
    _call_if_exists(vsp, "Lock")


def unlock_gui(vsp) -> None:
    logger.debug("Unlocking OpenVSP GUI")
    _call_if_exists(vsp, "Unlock")
    _call_if_exists(vsp, "UpdateGUI")


def init_context(open_gui: bool = False) -> VSPContext:
    vsp, tried = _import_openvsp_graphics()
    versions = {"openvsp_api": getattr(vsp, "OPENVSP_VERSION", "unknown")}
    logger.info(
        "Initialized OpenVSP context",
        context={"open_gui": open_gui, "version": versions["openvsp_api"], "attempts": tried},
    )
    if open_gui:
        start_gui(vsp)
    return VSPContext(vsp=vsp, versions=versions)
