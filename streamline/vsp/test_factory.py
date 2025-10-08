from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Iterable, List, Tuple

from ..core.logging import get_logger
from .session import import_vsp  # ensure promoted API


def import_openvsp():
    """Legacy helper for tests expecting `import_openvsp` symbol.

    Delegates to session.import_vsp(). Tests use this to obtain the OpenVSP
    module. Keeping it lightweight avoids duplicating session import logic.
    """
    from .session import import_vsp  # local import to avoid cycles
    return import_vsp()


def _discover_parms(vsp, geom_id: str):  # best-effort reflective map
    info = []
    try:
        ids = vsp.GetParmIDs(geom_id)  # type: ignore[attr-defined]
    except Exception:
        return info
    for pid in ids:
        try:
            name = vsp.GetParmName(pid)  # type: ignore[attr-defined]
            group = vsp.GetParmGroupName(pid)  # type: ignore[attr-defined]
            info.append((name, group, pid))
        except Exception:
            continue
    return info

def _enumerate_parms(vsp, geom_id: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    try:
        ids = vsp.GetParmIDs(geom_id)  # type: ignore[attr-defined]
    except Exception:
        return out
    for pid in ids:
        try:
            nm = vsp.GetParmName(pid)  # type: ignore[attr-defined]
            grp = vsp.GetParmGroupName(pid)  # type: ignore[attr-defined]
            out.append((nm, grp, pid))
        except Exception:
            continue
    return out

def _find_parm_id(parms: List[Tuple[str, str, str]], name_candidates: Iterable[str], group_candidates: Iterable[str] | None = None, *, substring: bool = False):
    names_lower = [n.lower() for n in name_candidates]
    groups_lower = {g.lower() for g in group_candidates} if group_candidates else None
    for nm, grp, pid in parms:
        nl = nm.lower(); gl = grp.lower()
        if groups_lower and gl not in groups_lower:
            continue
        if substring:
            if any(cand in nl for cand in names_lower):
                return pid, nm, grp
        else:
            if nl in names_lower:
                return pid, nm, grp
    return None

def _set_parm_by_id(vsp, pid: str, value: float) -> bool:
    try:
        vsp.SetParmVal(pid, float(value))  # preferred signature
        return True
    except TypeError:
        # Fallback: try name/group signature requires mapping pid back (skip to avoid errors)
        return False
    except Exception:
        return False

def _get_parm_val_by_id(vsp, pid: str):
    try:
        return float(vsp.GetParmVal(pid))
    except Exception:
        return None

def _set_numeric_parm(vsp, geom_id: str, value: float, name_candidates: Iterable[str], group_candidates: Iterable[str] | None = None) -> bool:
    name_set = {n.lower() for n in name_candidates}
    group_set = {g.lower() for g in group_candidates} if group_candidates else None
    # First attempt reflective search
    for name, group, pid in _discover_parms(vsp, geom_id):
        if name.lower() in name_set and (group_set is None or group.lower() in group_set):
            try:
                # Prefer setting by parm ID if available
                if hasattr(vsp, 'SetParmVal'):  # standard signature uses geom_id,name,group,val
                    try:
                        vsp.SetParmVal(geom_id, name, group, float(value))
                    except TypeError:
                        # Some builds allow SetParmVal(pid,val)
                        try:
                            vsp.SetParmVal(pid, float(value))  # type: ignore[arg-type]
                        except Exception:
                            raise
                return True
            except Exception:
                continue
    # Fallback brute-force attempts
    for nm in name_candidates:
        for grp in (group_candidates or ["WingGeom", "Design", "XSec_1", "XSec_0"]):
            try:
                vsp.SetParmVal(geom_id, nm, grp, float(value))
                return True
            except Exception:
                pass
    return False

def _get_first_parm_value(vsp, geom_id: str, name_candidates: Iterable[str], group_candidates: Iterable[str] | None = None) -> Optional[float]:
    name_set = {n.lower() for n in name_candidates}
    group_set = {g.lower() for g in group_candidates} if group_candidates else None
    for name, group, pid in _discover_parms(vsp, geom_id):
        if name.lower() in name_set and (group_set is None or group.lower() in group_set):
            try:
                return float(vsp.GetParmVal(geom_id, name, group))
            except Exception:
                try:
                    return float(vsp.GetParmVal(pid))  # type: ignore[arg-type]
                except Exception:
                    continue
    # Fallback brute force
    for nm in name_candidates:
        for grp in (group_candidates or ["WingGeom", "Design", "XSec_1", "XSec_0"]):
            try:
                return float(vsp.GetParmVal(geom_id, nm, grp))
            except Exception:
                pass
    return None


def build_basic_transport(
    *,
    model_name: str = "streamline_test",
    span: float = 5.0,
    chord: float = 1.0,
    thickness: float = 0.12,
    sweep_deg: float = 2.0,
    output_path: Optional[Path] = None,
    logger_name: str = __name__,
    vsp: Any | None = None,
) -> Dict[str, Any]:
    """Create a simple wing-only vehicle in OpenVSP for testing.

    Parameters:
        model_name: Base name for created geometry.
        span, chord, thickness, sweep_deg: Basic wing parameters.
        output_path: Optional path to write a .vsp3 file.
        logger_name: Logger namespace.
        vsp: Optional already-imported OpenVSP module (for dependency injection).
    """
    if vsp is None:
        # Use canonical importer to guarantee full promoted API
        vsp = import_vsp()

    if not hasattr(vsp, "AddGeom"):
        raise RuntimeError("Loaded 'openvsp' module is missing AddGeom – incorrect runtime installation")

    log = get_logger(logger_name)
    vsp.ClearVSPModel()

    wing_id = vsp.AddGeom("WING")
    wing_name = f"{model_name}_wing"
    vsp.SetGeomName(wing_id, wing_name)

    parms = _enumerate_parms(vsp, wing_id)

    # Locate span & chord parameters (accept common groups but only if discovered)
    span_pid_info = _find_parm_id(parms, ["TotalSpan", "Span", "FullSpan", "WingSpan"], ["WingGeom", "Design"])
    chord_pid_info = _find_parm_id(parms, ["TotalChord", "Chord", "AvgChord"], ["WingGeom", "Design"])
    thick_pid_info = _find_parm_id(parms, ["thick", "thickness"], None, substring=True)

    if span_pid_info:
        _set_parm_by_id(vsp, span_pid_info[0], span)
    if chord_pid_info:
        _set_parm_by_id(vsp, chord_pid_info[0], chord)
    if thick_pid_info:
        _set_parm_by_id(vsp, thick_pid_info[0], thickness)

    # Apply a couple of updates to propagate derived geometry
    for _ in range(2):
        try:
            vsp.Update()
        except Exception:
            break

    # Gather outputs
    span_val = _get_parm_val_by_id(vsp, span_pid_info[0]) if span_pid_info else span
    chord_val = _get_parm_val_by_id(vsp, chord_pid_info[0]) if chord_pid_info else chord

    # Area parameter discovery (no brute-force guessing that triggers warnings)
    area_pid_info = _find_parm_id(parms, ["Sref", "Area", "TotalArea", "WingArea", "PlanformArea"], ["WingGeom", "Design", "Ref"])
    if area_pid_info:
        sref = _get_parm_val_by_id(vsp, area_pid_info[0]) or (span_val * chord_val)
    else:
        sref = (span_val or span) * (chord_val or chord)

    results: Dict[str, Any] = {
        "wing_id": wing_id,
        "wing_name": wing_name,
        "model_name": model_name,
        "sref": float(sref),
        "bref": float(span_val or span),
        "cref": float(chord_val or chord),
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            vsp.WriteVSPFile(str(output_path))
            results["model_path"] = output_path
        except Exception as exc:
            log.debug("WriteVSPFile failed", hint=str(exc))

    log.debug(
        "Built OpenVSP test geometry (discovered parms)",
        context={
            "wing_id": wing_id,
            "span_pid": span_pid_info[:2] if span_pid_info else None,
            "chord_pid": chord_pid_info[:2] if chord_pid_info else None,
            "thick_pid": thick_pid_info[:2] if thick_pid_info else None,
            "area_present": bool(area_pid_info),
            "sref": sref,
        },
    )

    return results
