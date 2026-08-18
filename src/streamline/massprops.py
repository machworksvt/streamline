"""Ledger-computed mass properties — pure numpy, no OpenVSP (decision at plan review: OpenVSP's
inertia tools are not trusted and the model is not set up for them).

The ledger is a committed JSON file of components: point masses with optional simple-shape local
inertias. The sum is exact for what the ledger says; what the ledger says is the user's estimate,
and the artifact carries `status: estimated` / `confidence` so nobody mistakes arithmetic for
measurement (§8.8's trust gradient: mass > CG > inertia).

Ledger schema (validated here, not in the contract package — the ledger is an input, not a
released artifact):

    {"components": [{"name": str, "mass_kg": float, "cg_m": [x,y,z]  (FRD from the datum),
                     "shape": {"kind": "point"} |
                              {"kind": "box",      "extents_m": [lx,ly,lz]} |
                              {"kind": "cylinder", "axis": "x|y|z", "radius_m": r, "length_m": l} |
                              {"kind": "inertia",  "inertia_kg_m2": [[...3x3...]]}   (about its own CG, FRD),
                     "source": str}, ...],
     "notes": str (optional),
     "fuel": {"cg_m": [x,y,z] (FRD), ...} (optional — where the fuel sits; the consumer's fuel state
              moves the CG toward it. Capacity is the engine deck's `fuel.capacity_kg`, not repeated here)}

`shape` defaults to point. Inertia of the assembly about the total CG via parallel axis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from aerodb_contract import canonical_json, schema as contract_schema


class LedgerError(ValueError):
    pass


def _local_inertia(comp: dict) -> np.ndarray:
    m = float(comp["mass_kg"])
    shape = comp.get("shape", {"kind": "point"})
    kind = shape.get("kind", "point")
    if kind == "point":
        return np.zeros((3, 3))
    if kind == "box":
        lx, ly, lz = (float(v) for v in shape["extents_m"])
        return m / 12.0 * np.diag([ly * ly + lz * lz, lx * lx + lz * lz, lx * lx + ly * ly])
    if kind == "cylinder":
        r, L = float(shape["radius_m"]), float(shape["length_m"])
        axial = 0.5 * m * r * r
        trans = m * (3 * r * r + L * L) / 12.0
        i = {"x": [axial, trans, trans], "y": [trans, axial, trans], "z": [trans, trans, axial]}
        try:
            return np.diag(i[shape["axis"]])
        except KeyError:
            raise LedgerError(f"{comp.get('name')}: cylinder axis must be x|y|z")
    if kind == "inertia":
        I = np.asarray(shape["inertia_kg_m2"], dtype=float)
        if I.shape != (3, 3) or not np.allclose(I, I.T):
            raise LedgerError(f"{comp.get('name')}: inertia must be a symmetric 3x3")
        return I
    raise LedgerError(f"{comp.get('name')}: unknown shape kind {kind!r}")


@dataclass(frozen=True)
class MassProps:
    mass_kg: float
    cg_m: np.ndarray
    inertia_kg_m2: np.ndarray     # about the CG, FRD
    components: list[dict]
    ledger_sha256: str
    fuel_cg_m: np.ndarray | None = None      # FRD; None when the ledger has no fuel block


def from_ledger(path: Path | str) -> MassProps:
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    comps = doc.get("components")
    if not comps:
        raise LedgerError(f"{p}: no components")
    total = 0.0
    moment = np.zeros(3)
    rows = []
    for c in comps:
        for key in ("name", "mass_kg", "cg_m", "source"):
            if key not in c:
                raise LedgerError(f"component {c.get('name', '?')!r}: missing {key!r}")
        m = float(c["mass_kg"])
        if m <= 0:
            raise LedgerError(f"{c['name']}: mass {m} must be positive")
        r = np.asarray(c["cg_m"], dtype=float)
        if r.shape != (3,):
            raise LedgerError(f"{c['name']}: cg_m must be [x,y,z]")
        total += m
        moment += m * r
        rows.append(c)
    cg = moment / total
    I = np.zeros((3, 3))
    for c in rows:
        m = float(c["mass_kg"])
        d = np.asarray(c["cg_m"], dtype=float) - cg
        I += _local_inertia(c) + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
    fuel_cg = None
    if isinstance(doc.get("fuel"), dict) and "cg_m" in doc["fuel"]:
        fuel_cg = np.asarray(doc["fuel"]["cg_m"], dtype=float)
        if fuel_cg.shape != (3,):
            raise LedgerError("fuel.cg_m must be [x,y,z]")
    return MassProps(mass_kg=total, cg_m=cg, inertia_kg_m2=I, components=rows,
                     ledger_sha256=canonical_json.sha256_file(p), fuel_cg_m=fuel_cg)


def to_artifact(mp: MassProps, *, aircraft_name: str, geometry_rev: str, geometry_sha256: str,
                confidence: dict | None = None) -> dict:
    """The contract-validated massprops.json document."""
    doc = {
        "schema": {"name": "massprops", "version": contract_schema.SCHEMA_VERSION},
        "aircraft": {"name": aircraft_name, "geometry_rev": geometry_rev,
                     "geometry_sha256": geometry_sha256},
        "mass_kg": mp.mass_kg,
        "cg_m": mp.cg_m.tolist(),
        "inertia_kg_m2": mp.inertia_kg_m2.tolist(),
        "components": [{"name": c["name"], "mass_kg": c["mass_kg"], "cg_m": list(c["cg_m"]),
                        "source": c["source"]} for c in mp.components],
        "status": {"mass": "estimated", "cg": "estimated", "inertia": "estimated"},
        "confidence": confidence or {"mass": "medium", "cg": "low", "inertia": "low"},
        "provenance": {"method": "ledger_point_masses", "ledger_sha256": mp.ledger_sha256,
                       "contract_version": contract_schema.SCHEMA_VERSION},
    }
    if mp.fuel_cg_m is not None:
        doc["fuel"] = {"cg_m": mp.fuel_cg_m.tolist()}
    contract_schema.check(canonical_json.to_jsonable(doc), "massprops")
    return canonical_json.to_jsonable(doc)
