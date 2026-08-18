"""Geometry apply: a committed JSON spec → a new .vsp3 revision, scripted end to end (§8.4 —
no hand edits between hashed revisions, the spec IS the record of what changed and why).

The spec pins the source file's sha256, so an apply against a silently-changed source refuses
instead of laundering it into the next revision. Operations, in the order they run:

    rename_geoms        [{name, new, parent?}]   parent disambiguates duplicate names
    rename_subsurfaces  [{geom, old, new}]
    zero_deflections    true                     every VSPAERO group to 0° before the save
    groups              [{name, geom, subsurface, gains}]   the FULL group table: existing group
                        slots are repurposed in-place (the API cannot delete groups), extras are
                        created; membership is always both copies, orientation lives in the
                        per-copy gains (right (1,0), left (0,−1), symmetric (1,−1) — the
                        handedness mechanism, geometry.group_gains)
    sets                [{name, geoms}]          named set with EXPLICIT membership; claims an
                        empty default-named slot when the name does not exist yet
"""

from __future__ import annotations

import json
from pathlib import Path

from . import geometry as geom_mod
from .session import Session


class ApplyError(RuntimeError):
    pass


def _geom_by_spec(geo: geom_mod.Geometry, api, name: str, parent: str | None):
    hits = [g for g in geo.geoms if g.name == name]
    if parent is not None:
        hits = [g for g in hits if (api.GetGeomName(api.GetGeomParent(g.id)) if api.GetGeomParent(g.id) else "") == parent]
    if len(hits) != 1:
        raise ApplyError(f"geom {name!r}" + (f" under {parent!r}" if parent else "") +
                         f" matches {len(hits)} geoms — need exactly 1")
    return hits[0]


def apply_spec(session: Session, spec_path: Path | str) -> dict:
    """Run the spec; returns {'out': path, 'sha256': hex} of the written revision."""
    api = session.api
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    src = spec_path.parent / spec["source"]
    out = spec_path.parent / spec["out"]

    geo = geom_mod.load(session, src)
    if geo.sha256 != spec["source_sha256"]:
        raise ApplyError(f"{src.name} is sha256 {geo.sha256[:12]}… but the spec pins "
                         f"{spec['source_sha256'][:12]}… — the source changed; re-audit first")

    for r in spec.get("rename_geoms", ()):
        g = _geom_by_spec(geo, api, r["name"], r.get("parent"))
        api.SetGeomName(g.id, r["new"])
    for r in spec.get("rename_subsurfaces", ()):
        g = _geom_by_spec(geo, api, r["geom"], None)
        hits = [ss for ss in g.subsurfaces if ss.name == r["old"]]
        if len(hits) != 1:
            raise ApplyError(f"subsurface {r['old']!r} on {r['geom']!r} matches {len(hits)}")
        api.SetSubSurfName(hits[0].id, r["new"])
    api.Update()
    geo = geom_mod.enumerate_model(session, src)   # names changed; re-read

    groups = spec.get("groups", ())
    for i, gs in enumerate(groups):
        if i >= api.GetNumControlSurfaceGroups():
            gi = api.CreateVSPAEROControlSurfaceGroup()
            if gi != i:
                raise ApplyError(f"created group landed at index {gi}, expected {i}")
        api.SetVSPAEROControlGroupName(gs["name"], i)
        api.RemoveAllFromVSPAEROControlSurfaceGroup(i)
        avail = list(api.GetAvailableCSNameVec(i))
        picks = [k + 1 for k, n in enumerate(avail)
                 if n.startswith(f"{gs['geom']}_") and n.endswith(f"_{gs['subsurface']}")]
        if len(picks) != len(gs["gains"]):
            raise ApplyError(f"group {gs['name']!r}: {len(picks)} copies of "
                             f"{gs['geom']}/{gs['subsurface']} available ({avail}), "
                             f"spec has {len(gs['gains'])} gains")
        api.AddSelectedToCSGroup(picks, i)
        api.Update()
    if groups:
        geo = geom_mod.enumerate_model(session, src)
        for i, gs in enumerate(groups):
            geom_mod.set_group_gains(session, geo.group(gs["name"]), [float(x) for x in gs["gains"]])

    if spec.get("zero_deflections", False):
        for cg in geom_mod.enumerate_model(session, src).control_groups:
            geom_mod.set_group_deflection(session, cg, 0.0)

    for ss in spec.get("sets", ()):
        sets = tuple(api.GetSetName(k) for k in range(api.GetNumSets()))
        if ss["name"] in sets:
            idx = sets.index(ss["name"])
        else:
            empties = [k for k, nm in enumerate(sets)
                       if nm.startswith("Set_") and not any(api.GetSetFlag(g.id, k) for g in geo.geoms)]
            if not empties:
                raise ApplyError(f"no empty default-named set slot left for {ss['name']!r}")
            idx = empties[0]
            api.SetSetName(idx, ss["name"])
        want = set(ss["geoms"])
        have = {g.name for g in geo.geoms}
        if not want <= have:
            raise ApplyError(f"set {ss['name']!r} names unknown geoms {sorted(want - have)}")
        for g in geo.geoms:
            api.SetSetFlag(g.id, idx, g.name in want)
    api.Update()

    api.WriteVSPFile(str(out), api.SET_ALL)
    sha = geom_mod.sha256_of_file(out)
    return {"out": str(out), "sha256": sha}
