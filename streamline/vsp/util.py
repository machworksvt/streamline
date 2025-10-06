# streamline/vsp/util.py
from __future__ import annotations
from typing import Dict, List, Any

def as_list(v):  # OpenVSP Set*AnalysisInput expects lists
    return [v]

def get_control_group_names(vsp) -> List[str]:
    n = vsp.GetNumControlSurfaceGroups()
    return [vsp.GetVSPAEROControlGroupName(i) for i in range(n)]

def apply_control_deflections(vsp, defl_deg: Dict[int, float]) -> None:
    if not defl_deg:
        return
    c = vsp.FindContainer("VSPAEROSettings", 0)
    for gi, val in defl_deg.items():
        pid = vsp.FindParm(c, "DeflectionAngle", f"ControlSurfaceGroup_{gi}")
        if pid:
            vsp.SetParmVal(pid, float(val))

def apply_udp_overrides(vsp, overrides: Dict[str, float]) -> None:
    # Accept ParmID -> value (SI) for now; we can add name->ParmID lookup later.
    for parm_id, value in (overrides or {}).items():
        try: vsp.SetParmVal(parm_id, float(value))
        except Exception:
            # intentionally quiet in smoke paths; add logging later if desired
            pass
