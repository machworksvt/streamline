# streamline/vsp/analyses/_set_utils.py
from __future__ import annotations

from typing import Optional

from ..configure import AppliedConfiguration
from ..sets import choose_populated_set


def resolve_set_index(vsp, ticket, applied_cfg: Optional[AppliedConfiguration]):
    """Resolve the set index to analyze for a ticket."""
    if getattr(ticket, "set_index", None) is not None:
        try:
            return int(getattr(ticket, "set_index"))
        except Exception:
            pass
    if applied_cfg and applied_cfg.geom_set_index is not None:
        try:
            return int(applied_cfg.geom_set_index)
        except Exception:
            pass

    candidates = []
    ticket_name = getattr(ticket, "set_name", None)
    if ticket_name:
        candidates.append(ticket_name)
    if applied_cfg and applied_cfg.geom_set_name:
        candidates.append(applied_cfg.geom_set_name)

    try:
        mapping = {i: vsp.GetSetName(i) for i in range(vsp.GetNumSets())}
    except Exception:
        mapping = {}

    for candidate in candidates:
        if not candidate:
            continue
        for idx, name in mapping.items():
            if name and name.lower() == str(candidate).lower():
                return idx

    try:
        return choose_populated_set(vsp)
    except Exception:
        return None


def resolve_set_name(vsp, set_idx: Optional[int], applied_cfg: Optional[AppliedConfiguration]):
    """Resolve the friendly set name associated with ``set_idx``."""
    if set_idx is None:
        return applied_cfg.geom_set_name if applied_cfg else None
    if applied_cfg and applied_cfg.geom_set_index == set_idx and applied_cfg.geom_set_name:
        return applied_cfg.geom_set_name
    try:
        return vsp.GetSetName(int(set_idx))
    except Exception:
        return applied_cfg.geom_set_name if applied_cfg else None
