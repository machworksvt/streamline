"""The geometry substrate: load a .vsp3, hash it, enumerate what is in it, apply a configuration.

Shared by every analysis and by whatever lands later (structures, flowpath, visualisation export)
— plan §3.0. It knows OpenVSP; it does not know aero. Positions it reports are FRD from the datum
(the OpenVSP origin) — nothing above this layer sees VSP axes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import frames
from .session import Session


@dataclass(frozen=True)
class SubSurface:
    id: str
    name: str
    type: int          # api.SS_CONTROL etc.
    geom_id: str


@dataclass(frozen=True)
class Geom:
    id: str
    name: str
    type: str          # api.GetGeomTypeName: "Wing", "Fuselage", "Pod", ...
    subsurfaces: tuple[SubSurface, ...]


@dataclass(frozen=True)
class ControlGroup:
    index: int
    name: str
    surfaces: tuple[str, ...]      # VSPAERO's own surface names (e.g. "WingGeom_Surf0_SS_CONT_0")


@dataclass(frozen=True)
class Geometry:
    path: Path
    sha256: str
    geoms: tuple[Geom, ...]
    control_groups: tuple[ControlGroup, ...]
    sets: tuple[str, ...]           # set names by index (index 0 = "All", per OpenVSP)

    def wings(self) -> list[Geom]:
        return [g for g in self.geoms if g.type.lower().startswith("wing")]

    def by_name(self, name: str) -> Geom:
        for g in self.geoms:
            if g.name == name:
                return g
        raise KeyError(f"no geom named {name!r}; have {[g.name for g in self.geoms]}")

    def group(self, name: str) -> ControlGroup:
        for g in self.control_groups:
            if g.name == name:
                return g
        raise KeyError(f"no VSPAERO control group named {name!r}; have {[g.name for g in self.control_groups]}")

    def set_index(self, name: str) -> int:
        try:
            return self.sets.index(name)
        except ValueError:
            raise KeyError(f"no set named {name!r}; have {list(self.sets)}") from None


def sha256_of_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def enumerate_model(session: Session, path: Path | str) -> Geometry:
    """Describe whatever is currently loaded in OpenVSP; `path` is what it was loaded from."""
    api = session.api
    geoms = []
    for gid in api.FindGeoms():
        subs = []
        for k in range(api.GetNumSubSurf(gid)):
            sid = api.GetSubSurf(gid, k)
            subs.append(SubSurface(id=sid, name=api.GetSubSurfName(sid), type=int(api.GetSubSurfType(sid)), geom_id=gid))
        geoms.append(Geom(id=gid, name=api.GetGeomName(gid), type=api.GetGeomTypeName(gid), subsurfaces=tuple(subs)))
    groups = []
    for i in range(api.GetNumControlSurfaceGroups()):
        groups.append(ControlGroup(index=i, name=api.GetVSPAEROControlGroupName(i),
                                   surfaces=tuple(api.GetActiveCSNameVec(i))))
    sets = tuple(api.GetSetName(i) for i in range(api.GetNumSets()))
    p = Path(path)
    return Geometry(path=p, sha256=sha256_of_file(p) if p.exists() else "", geoms=tuple(geoms),
                    control_groups=tuple(groups), sets=sets)


def load(session: Session, path: Path | str) -> Geometry:
    """Replace the model with the file's contents and describe it. The sha256 is of the file
    bytes — the geometry's identity for every artifact produced from it (Master Plan §8.2)."""
    api = session.api
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    api.ClearVSPModel()
    api.ReadVSPFile(str(p))
    api.Update()
    return enumerate_model(session, p)


def bbox_frd(session: Session, geom_id: str) -> tuple[np.ndarray, np.ndarray]:
    """Bounding box of a geom in FRD (min, max) — after the rotation the roles of the VSP min/max
    swap along X and Z, which is exactly why this helper exists.

    Refuses Mesh geoms: GetGeomBBoxMin/Max SEGFAULTS the process on them (OpenVSP 3.51.2,
    found on icarus rev A's servo/gear CAD meshes) — a Python-level raise is the only guard."""
    api = session.api
    if api.GetGeomTypeName(geom_id) == "Mesh":
        raise TypeError(f"bbox_frd({api.GetGeomName(geom_id)!r}): Mesh geoms segfault "
                        "GetGeomBBox* on OpenVSP 3.51.2 — skip them")
    lo = api.GetGeomBBoxMin(geom_id)
    hi = api.GetGeomBBoxMax(geom_id)
    a = frames.vsp_to_frd([lo.x(), lo.y(), lo.z()])
    b = frames.vsp_to_frd([hi.x(), hi.y(), hi.z()])
    return np.minimum(a, b), np.maximum(a, b)


def _group_parm(session: Session, group: ControlGroup, name: str) -> str:
    api = session.api
    container = api.FindContainer("VSPAEROSettings", 0)
    pid = api.FindParm(container, name, f"ControlSurfaceGroup_{group.index}")
    if not pid:
        raise KeyError(f"no {name!r} parm for control group {group.name!r} (index {group.index})")
    return pid


def set_group_deflection(session: Session, group: ControlGroup, angle_rad: float) -> None:
    """Set a VSPAERO control-surface group's deflection (VSPAERO's parm is in degrees)."""
    session.api.SetParmVal(_group_parm(session, group, "DeflectionAngle"), float(np.degrees(angle_rad)))
    session.api.Update()


def get_group_deflection(session: Session, group: ControlGroup) -> float:
    return float(np.radians(session.api.GetParmVal(_group_parm(session, group, "DeflectionAngle"))))


def group_gains(session: Session, group: ControlGroup) -> dict[str, float]:
    """The per-copy gain parms (`Surf_<subsurf-id>_<copy>_Gain`) of a group, by parm name.

    THE HANDEDNESS MECHANISM, measured on this pin and load-bearing for the whole contract: a
    subsurface on a symmetric geom exists as two copies, and the MIRRORED copy's positive
    deflection is mirrored too (its local TE-down is global TE-up). So a group realises the
    contract's TE-down-positive-per-physical-surface convention through its gains:

        right-side surface   gains (1, 0)    — the primary copy alone
        left-side surface    gains (0, −1)   — the mirrored copy, un-mirrored
        symmetric surface    gains (1, −1)   — both panels globally TE-down (elevator/flap)

    Default (1, 1) is the classic antisymmetric aileron pair and is exactly what a per-side
    derivative must NOT be built from. Verified force-level: (1,0) → CZ −0.71 / Cl −0.13;
    (0,1) → CZ +0.72 (mirror-sign at the force level); (1,−1) → CZ −1.42, Cl 0.0."""
    api = session.api
    container = api.FindContainer("VSPAEROSettings", 0)
    out = {}
    for pid in api.FindContainerParmIDs(container):
        name = api.GetParmName(pid)
        if name.endswith("_Gain") and api.FindParm(container, name, f"ControlSurfaceGroup_{group.index}") == pid:
            out[name] = float(api.GetParmVal(pid))
    return out


def set_group_gains(session: Session, group: ControlGroup, gains: dict[str, float] | list[float]) -> None:
    """Set a group's per-copy gains, by parm name or as a list ordered by copy index (…_0_Gain,
    …_1_Gain, …). Refuses a count mismatch — a gain silently left at its default is precisely the
    antisymmetric-aileron trap."""
    api = session.api
    current = group_gains(session, group)
    if isinstance(gains, dict):
        wanted = gains
    else:
        ordered = sorted(current, key=lambda n: n.rsplit("_", 2)[-2])
        if len(gains) != len(ordered):
            raise ValueError(f"group {group.name!r} has {len(ordered)} gain parms, got {len(gains)} values")
        wanted = dict(zip(ordered, gains))
    unknown = set(wanted) - set(current)
    if unknown:
        raise KeyError(f"group {group.name!r} has no gain parms {sorted(unknown)}; has {sorted(current)}")
    container = api.FindContainer("VSPAEROSettings", 0)
    for name, val in wanted.items():
        api.SetParmVal(api.FindParm(container, name, f"ControlSurfaceGroup_{group.index}"), float(val))
    api.Update()
