"""The ParasiteDrag wrapper: one (V, altitude) condition → CD0 build-up, SI in and out.

The unit traps this analysis carries (measured on this pin, plan §3.1): `VelocityUnit` defaults to
**ft/s** (`V_UNIT_M_S` is enum 1, not 0), `LengthUnit` to feet, and the built-in atmosphere works
in imperial regardless. The wrapper closes all of them the same way: `FreestreamPropChoice =
ATMOS_TYPE_MANUAL_RE_L`, with Reynolds-per-metre and Mach computed by OUR ISA (`atmosphere.py`) —
the only numbers Cf actually depends on — so no unit enum can silently change a Reynolds number.

Verified against theory at wiring time: with Re/L = 2.2e6 /m on the reference wing, VSPAERO's
Schlichting-compressible `Comp_Cf = 0.004906` vs `0.455/log10(Re)^2.58 = 0.00491`, and
`Total_CD = Σ Cf·Swet·FF / Sref` reconciles to the last digit. The test keeps both facts.

`PercLam` stays 0 (fully turbulent) — conservative for drag at this Reynolds and one less number
to defend; recorded in provenance via the resolved settings like everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from . import settings as settings_mod
from .geometry import Geometry
from .session import Session


@dataclass(frozen=True)
class ComponentDrag:
    label: str
    swet_m2: float
    lref_m: float
    reynolds: float
    cf: float
    form_factor: float
    perc_lam: float
    f_m2: float           # Cf·Swet·FF — the drag area
    cd: float             # f / Sref


@dataclass(frozen=True)
class ParasiteResult:
    airspeed_m_s: float
    mach: float
    sref_m2: float
    cd0_total: float
    components: tuple[ComponentDrag, ...]
    turb_cf_eqn: str
    resolved_settings: dict


def parasite_overrides(session: Session, geometry: Geometry, *, airspeed_m_s: float, mach: float,
                       reynolds_per_m: float, wing_id: str, parasite_set: str = "All",
                       extra: Mapping | None = None) -> dict:
    """`parasite_set` names the set whose wetted areas feed the CD0 buildup. "All" is only right
    for fixture models; a real model's "All" includes fuel-mass conformals, servo CAD meshes and
    stowed gear, which would each contribute fictitious wetted area (icarus rev A)."""
    api = session.api
    s = {
        "GeomSet": geometry.set_index(parasite_set),
        "RecomputeGeom": 1,
        "LengthUnit": int(api.LEN_M),
        "VelocityUnit": int(api.V_UNIT_M_S),
        "FreestreamPropChoice": int(api.ATMOS_TYPE_MANUAL_RE_L),
        "Vinf": airspeed_m_s,
        "Mach": mach,
        "Re_L": reynolds_per_m,
        "RefFlag": 1, "WingID": wing_id,
    }
    if extra:
        s.update(extra)
    return s


def run_parasite(session: Session, geometry: Geometry, *, overrides: dict) -> ParasiteResult:
    api = session.api
    full = settings_mod.complete(session, "ParasiteDrag", overrides)
    resolved = settings_mod.resolve(session, "ParasiteDrag", full, overrides=overrides)
    session.fresh_results()
    api.ExecAnalysis("ParasiteDrag")
    rid = session.latest("Parasite_Drag")

    def doubles(key):
        vals = api.GetDoubleResults(rid, key)
        if vals is None:
            raise KeyError(f"Parasite_Drag has no key {key!r}")
        return list(vals)

    def strings(key):
        return list(api.GetStringResults(rid, key))

    labels = strings("Comp_Label")
    swet, lref, re_, cf, ffout, perclam, f_, cd = (doubles(k) for k in (
        "Comp_Swet", "Comp_Lref", "Comp_Re", "Comp_Cf", "Comp_FFOut", "Comp_PercLam", "Comp_f", "Comp_CD"))
    n = len(labels)
    for name, col in (("Comp_Swet", swet), ("Comp_Cf", cf), ("Comp_CD", cd)):
        if len(col) != n:
            raise ValueError(f"{name} has {len(col)} rows for {n} components — refusing to zip ragged data")
    comps = tuple(ComponentDrag(labels[i], swet[i], lref[i], re_[i], cf[i], ffout[i], perclam[i], f_[i], cd[i])
                  for i in range(n))

    sref = doubles("FC_Sref")[0]
    total = doubles("Total_CD_Total")[0]
    vinf = doubles("FC_Vinf")[0]
    mach = doubles("FC_Mach")[0]
    # the echo check: what VSPAERO ran must be what was asked for
    if abs(vinf - float(overrides["Vinf"])) > 1e-6 * max(1.0, abs(vinf)):
        raise ValueError(f"ParasiteDrag ran Vinf={vinf}, asked {overrides['Vinf']} — a unit enum slipped")
    # and the bookkeeping must reconcile: total = sum of drag areas / Sref (+ excrescence, zero here)
    excres = doubles("Excres_f_Total")[0]
    recon = (sum(c.f_m2 for c in comps) + excres) / sref
    if abs(recon - total) > 1e-6 * max(1.0, abs(total)):
        raise ValueError(f"CD0 bookkeeping does not reconcile: Σf/Sref={recon} vs Total={total}")
    return ParasiteResult(airspeed_m_s=vinf, mach=mach, sref_m2=sref, cd0_total=total,
                          components=comps, turb_cf_eqn=strings("TurbCfEqnName")[0],
                          resolved_settings=resolved.as_json())
