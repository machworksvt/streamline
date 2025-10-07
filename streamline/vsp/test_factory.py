from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import get_logger


_TRUTHY = {"1", "true", "yes", "on"}


def _allow_stub() -> bool:
    value = os.getenv("STREAMLINE_ALLOW_VSP_STUB")
    if value is None:
        return True
    return value.strip().lower() in _TRUTHY


_ALLOW_STUB = _allow_stub()


class _FakeOpenVSP:
    __streamline_is_stub__ = True
    is_streamline_stub = True
    def __init__(self) -> None:
        self.ClearVSPModel()

    def ClearVSPModel(self) -> None:
        self._geom: Dict[str, Dict[str, Any]] = {}
        self._counter = 0

    def AddGeom(self, geom_type: str) -> str:
        self._counter += 1
        geom_id = f"fake_{self._counter}"
        self._geom[geom_id] = {
            "type": geom_type,
            "name": geom_id,
            "params": {
                "TotalSpan": 5.0,
                "TotalChord": 1.0,
            },
        }
        return geom_id

    def SetGeomName(self, geom_id: str, name: str) -> None:
        self._geom[geom_id]["name"] = name

    def GetGeomName(self, geom_id: str) -> str:
        return self._geom[geom_id]["name"]

    def FindGeom(self, name: str) -> list[str]:
        return [gid for gid, meta in self._geom.items() if meta["name"] == name]

    def SetParmVal(self, geom_id: str, parm: str, _group: str, value: float) -> None:
        self._geom[geom_id]["params"][parm] = float(value)

    def Update(self) -> None:
        for meta in self._geom.values():
            span = meta["params"].get("TotalSpan", 0.0)
            chord = meta["params"].get("TotalChord", 0.0)
            meta["params"]["Area"] = span * chord

    def WriteVSPFile(self, path: str) -> None:
        Path(path).write_text("FAKE VSP\n", encoding="utf-8")

    def GetParmVal(self, geom_id: str, parm: str, _group: str) -> float:
        return float(self._geom[geom_id]["params"].get(parm, 0.0))

    def VSPVersion(self) -> str:
        return "stub"


_FAKE_VSP = _FakeOpenVSP()


def import_openvsp() -> Optional[Any]:
    """Attempt to import the OpenVSP Python module, with a stub fallback."""

    if "openvsp_config" not in sys.modules:
        config = types.ModuleType("openvsp_config")
        config.LOAD_GRAPHICS = False
        config.LOAD_FACADE = False
        config.LOAD_MULTI_FACADE = False
        config._IGNORE_IMPORTS = False
        sys.modules["openvsp_config"] = config

    try:
        import openvsp as vsp  # type: ignore
        if hasattr(vsp, "ClearVSPModel"):
            setattr(vsp, "__streamline_is_stub__", False)
            return vsp
    except Exception:
        vsp = None

    if vsp is None:
        try:
            import openvsp.openvsp as vsp  # type: ignore
        except Exception:
            vsp = None

    if vsp is not None and hasattr(vsp, "ClearVSPModel"):
        setattr(vsp, "__streamline_is_stub__", False)
        return vsp

    if not _ALLOW_STUB:
        raise RuntimeError("OpenVSP Python module is not available and stubs are disabled. Set STREAMLINE_ALLOW_VSP_STUB=1 to allow fallbacks.")

    return _FAKE_VSP


def build_basic_transport(
    *,
    model_name: str = "streamline_test",
    span: float = 5.0,
    chord: float = 1.0,
    thickness: float = 0.12,
    sweep_deg: float = 2.0,
    output_path: Optional[Path] = None,
    logger_name: str = __name__,
) -> Dict[str, Any]:
    """Create a simple wing-only vehicle in OpenVSP for testing."""

    vsp = import_openvsp()
    if vsp is None:
        raise RuntimeError("OpenVSP Python module is not available")

    log = get_logger(logger_name)

    vsp.ClearVSPModel()

    wing_id = vsp.AddGeom("WING")
    wing_name = f"{model_name}_wing"
    vsp.SetGeomName(wing_id, wing_name)

    vsp.SetParmVal(wing_id, "TotalSpan", "WingGeom", span)
    vsp.SetParmVal(wing_id, "TotalChord", "WingGeom", chord)
    vsp.SetParmVal(wing_id, "Sweep", "XSec_1", sweep_deg)
    vsp.SetParmVal(wing_id, "ThickChord", "XSec_1", thickness)

    vsp.Update()

    results: Dict[str, Any] = {
        "wing_id": wing_id,
        "wing_name": wing_name,
        "model_name": model_name,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        vsp.WriteVSPFile(str(output_path))
        results["model_path"] = output_path

    sref = vsp.GetParmVal(wing_id, "Area", "WingGeom")
    cref = vsp.GetParmVal(wing_id, "TotalChord", "WingGeom")
    bref = vsp.GetParmVal(wing_id, "TotalSpan", "WingGeom")

    results.update({
        "sref": sref,
        "cref": cref,
        "bref": bref,
    })

    log.debug(
        "Built OpenVSP test geometry",
        context={"wing_id": wing_id, "sref": sref, "cref": cref, "bref": bref},
    )

    return results
