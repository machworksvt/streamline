# streamline/vsp/sets.py
from __future__ import annotations
from typing import Dict, Optional, Tuple, List

class VSPSetError(RuntimeError): ...

def list_sets(vsp) -> Dict[int, str]:
    out: Dict[int, str] = {}
    n = vsp.GetNumSets()
    for i in range(n):
        out[i] = vsp.GetSetName(i)
    return out

def ensure_set(vsp, name: str) -> int:
    mapping = list_sets(vsp)
    for idx, nm in mapping.items():
        if nm == name:
            return idx
    idx = max(mapping.keys()) + 1 if mapping else 0
    vsp.SetSetName(idx, name)
    return idx

def set_membership_counts(vsp) -> Dict[int, int]:
    """Count how many geoms are in each set index."""
    counts = {i: 0 for i in range(vsp.GetNumSets())}
    for gid in vsp.FindGeoms():
        for i in counts.keys():
            try:
                if vsp.GetSetFlag(gid, i):
                    counts[i] += 1
            except Exception:
                pass
    return counts

def choose_populated_set(vsp, preferred_idx: Optional[int] = None) -> int:
    """
    Return a set index that actually contains geometry.
    Priority: preferred_idx (if populated) → first non-empty set → 0.
    """
    counts = set_membership_counts(vsp)
    if preferred_idx is not None and counts.get(preferred_idx, 0) > 0:
        return preferred_idx
    for i, n in counts.items():
        if n > 0:
            return i
    return 0  # last resort

def set_inputs_for_analysis(vsp, analysis_name: str, thick_set_idx: int, thin_set_idx: Optional[int] = None) -> None:
    vsp.SetIntAnalysisInput(analysis_name, "GeomSet",      [int(thick_set_idx)])
    if thin_set_idx is not None:
        vsp.SetIntAnalysisInput(analysis_name, "ThinGeomSet", [int(thin_set_idx)])
