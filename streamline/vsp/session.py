"""OpenVSP session management and integration helpers."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

from ..core.errors import VSPSessionError
from ..core.logging import get_logger

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


def import_vsp() -> object:
    vsp, _ = _import_openvsp_graphics()
    return vsp


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
