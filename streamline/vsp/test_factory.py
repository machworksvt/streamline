from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import get_logger


def import_openvsp() -> Optional[Any]:
    """Attempt to import the OpenVSP Python module."""

    try:
        import openvsp as vsp  # type: ignore
    except ModuleNotFoundError:
        return None
    return vsp


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
    """Create a simple wing-only vehicle in OpenVSP for testing.

    Returns a dictionary describing created geometry. Caller is responsible for
    providing an initialized OpenVSP session via :func:`import_openvsp`.
    """

    vsp = import_openvsp()
    if vsp is None:
        raise RuntimeError("OpenVSP Python module is not available")

    log = get_logger(logger_name)

    vsp.ClearVSPModel()

    wing_id = vsp.AddGeom("WING")
    wing_name = f"{model_name}_wing"
    vsp.SetGeomName(wing_id, wing_name)

    # Basic planform setup
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

    # Provide reference quantities back to callers
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
