from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

import pytest


ParmInfo = Tuple[str, str, str]


def assert_has_minimal_api(vsp):
    required = ["AddGeom", "Update", "SetGeomName"]
    missing = [r for r in required if not hasattr(vsp, r)]
    if missing:
        raise AssertionError(f"OpenVSP module missing expected symbols: {missing}")


def enumerate_parms(vsp, geom_id: str) -> List[ParmInfo]:
    ids: Sequence[str]
    try:
        ids = list(vsp.GetParmIDs(geom_id))  # type: ignore[attr-defined]
    except Exception:
        return []

    discovered: List[ParmInfo] = []
    for pid in ids:
        try:
            name = vsp.GetParmName(pid)  # type: ignore[attr-defined]
            group = vsp.GetParmGroupName(pid)  # type: ignore[attr-defined]
        except Exception:
            continue
        discovered.append((str(name), str(group), str(pid)))
    return discovered


def find_parm(
    parms: Sequence[ParmInfo],
    name_candidates: Iterable[str],
    group_candidates: Iterable[str] | None = None,
    *,
    substring: bool = False,
) -> Optional[ParmInfo]:
    name_cands = [n.lower() for n in name_candidates]
    group_set = {g.lower() for g in group_candidates} if group_candidates else None
    for name, group, pid in parms:
        n_lower = name.lower()
        g_lower = group.lower()
        if group_set and g_lower not in group_set:
            continue
        if substring:
            if any(candidate in n_lower for candidate in name_cands):
                return name, group, pid
        elif n_lower in name_cands:
            return name, group, pid
    return None


def set_parm_value(vsp, geom_id: str, parm: ParmInfo, value: float) -> None:
    name, group, pid = parm
    # Prefer parm-id signature when available.
    try:
        vsp.SetParmVal(pid, float(value))
        return
    except TypeError:
        pass
    except Exception:  # pragma: no cover - fall back to full signature
        pass
    else:
        return

    try:
        vsp.SetParmVal(geom_id, name, group, float(value))
    except Exception as exc:  # pragma: no cover
        raise AssertionError(
            f"Failed to set parm {name} ({group}) on {geom_id}: {exc}"
        ) from exc


def get_parm_value(vsp, geom_id: str, parm: ParmInfo) -> float:
    name, group, pid = parm
    try:
        return float(vsp.GetParmVal(pid))
    except TypeError:
        pass
    except Exception:
        pass
    try:
        return float(vsp.GetParmVal(geom_id, name, group))
    except Exception as exc:  # pragma: no cover
        raise AssertionError(
            f"Failed to read parm {name} ({group}) on {geom_id}: {exc}"
        ) from exc


def assert_parm_changes(vsp, geom_id: str, parm: ParmInfo, new_value: float, *, tol: float = 1e-6) -> Tuple[float, float]:
    before = get_parm_value(vsp, geom_id, parm)
    set_parm_value(vsp, geom_id, parm, new_value)
    vsp.Update()
    after = get_parm_value(vsp, geom_id, parm)
    assert after == pytest.approx(new_value, rel=1e-6, abs=tol)
    assert abs(after - before) > tol
    vsp.Update()
    second = get_parm_value(vsp, geom_id, parm)
    assert second == pytest.approx(after, rel=1e-6, abs=tol)
    return before, after


def find_geom_ids(vsp, name: str) -> List[str]:
    if not hasattr(vsp, "FindGeom"):
        return []
    try:
        result = vsp.FindGeom(name)
    except TypeError:
        result = vsp.FindGeom(name, 0)
    except Exception:
        return []
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return [str(x) for x in result]
    return [str(result)]
