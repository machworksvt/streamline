"""Fusion body export → mass ledger.

The Fusion 360 'Weight Estimates CAD' assembly is the team's component-level mass model: every
part a solid with a material whose density was calibrated to a weighed mass (custom materials
'Bottom fuselage', 'Wing skin', 'Intake assembly + engine', 'Avionics', ...). `pull_bodies.py`
(projects/icarus/massprops/fusion/) dumps every B-Rep body — mass, centre of mass and the moment
tensor about the root origin, in the root frame — as one row. This module turns that export into
`ledger.json` for `massprops.from_ledger`:

  * bodies are read in the Fusion ROOT frame (X aft, Y right, Z up = OpenVSP's, common origin)
    and converted to FRD with diag(−1, 1, −1); tensors with R·I·Rᵀ (xy, yz flip sign);
  * `getXYZMomentsOfInertia` returns TENSOR entries (I_xy = −∫xy dm) about the origin, in
    kg·cm²; each group's tensor is moved to its own CG by the parallel-axis theorem here, and
    `massprops.from_ledger` moves the groups to the assembly CG;
  * an overrides file declares what is NOT taken as modelled: the fuel solids (excluded from the
    dry ledger, reported as the `fuel` block at kerosene density), material fixes (a body carrying
    Fusion's default 'Steel'), declared extra components, and a balance mass sized to a target
    dry CG. Every override carries its reason into the ledger's `source` strings;
  * grouping is by top-level occurrence — one ledger component per assembly (fuselage shell,
    each wing, intake+engine, avionics, each V-tail, ...), each with its own inertia tensor. The
    body-level detail stays in the committed export; the ledger is what the release reads.

Why not trust Fusion's own 'Physical' panel: on this model the root-level default-accuracy
result (20.63 kg, CoM x = 90.9 mm) is not the sum of its parts (dry 20.99 kg at x = 53.9 mm,
all bodies 24.89 kg) and counts only visible bodies (the fuel and the top shell were hidden).
The per-body export is unambiguous; the panel number is not used.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

# Root (Fusion/OpenVSP: X aft, Y right, Z up) → FRD.
R_TO_FRD = np.diag([-1.0, 1.0, -1.0])


class FusionExportError(ValueError):
    pass


@dataclass(frozen=True)
class Body:
    path: str
    name: str
    mass_kg: float
    volume_cm3: float
    area_cm2: float
    com_root_m: np.ndarray        # (3,) root frame, metres
    inertia_origin: np.ndarray    # (3,3) TENSOR about the root origin, root frame, kg·m²
    material: str
    density_kg_m3: float | None
    visible: bool
    lightbulb: bool
    solid: bool

    @property
    def top(self) -> str:
        parts = self.path.split("/")
        return parts[1] if len(parts) > 1 and parts[1] else "ROOT"

    def rescaled(self, density_kg_m3: float) -> "Body":
        """Same geometry, different density: mass and moments scale together."""
        if not self.density_kg_m3:
            raise FusionExportError(f"{self.path}::{self.name}: cannot rescale a body without a density")
        k = density_kg_m3 / self.density_kg_m3
        return replace(self, mass_kg=self.mass_kg * k, inertia_origin=self.inertia_origin * k,
                       density_kg_m3=density_kg_m3)


_COLS = ("path", "body", "mass_kg", "vol_cm3", "area_cm2", "cx_cm", "cy_cm", "cz_cm",
         "Ixx", "Iyy", "Izz", "Ixy", "Iyz", "Ixz", "material", "density", "visible", "lightbulb", "solid")


def _tensor6(xx, yy, zz, xy, yz, xz) -> np.ndarray:
    return np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]], dtype=float)


def read_bodies(path: Path | str) -> list[Body]:
    """Parse a `pull_bodies.py` export. Fusion units (cm, kg·cm²) → SI here."""
    p = Path(path)
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("HDR|"):
        raise FusionExportError(f"{p}: first line must be the HDR| header row")
    hdr = tuple(lines[0].split("|")[1:])
    if hdr != _COLS:
        raise FusionExportError(f"{p}: unexpected columns {hdr}")
    out = []
    for i, ln in enumerate(lines[1:], start=2):
        c = ln.split("|")
        if len(c) != len(_COLS):
            raise FusionExportError(f"{p}:{i}: {len(c)} columns, expected {len(_COLS)}")
        f = [float(v) for v in c[2:14]]
        out.append(Body(
            path=c[0], name=c[1], mass_kg=f[0], volume_cm3=f[1], area_cm2=f[2],
            com_root_m=np.array(f[3:6]) * 1e-2,
            inertia_origin=_tensor6(*f[6:12]) * 1e-4,
            material=c[14], density_kg_m3=float(c[15]) if c[15] else None,
            visible=c[16] == "1", lightbulb=c[17] == "1", solid=c[18] == "1"))
    return out


def _matches(rule: dict, b: Body) -> bool:
    return fnmatch.fnmatchcase(b.path, rule["path_glob"]) and b.name == rule["body"]


def aggregate(bodies: list[Body]) -> tuple[float, np.ndarray, np.ndarray]:
    """Total mass, CG (root frame, m) and inertia tensor about that CG (root frame, kg·m²)."""
    m = sum(b.mass_kg for b in bodies)
    if m <= 0:
        raise FusionExportError("aggregate of zero mass")
    cg = sum(b.mass_kg * b.com_root_m for b in bodies) / m
    Io = sum(b.inertia_origin for b in bodies)
    # I_origin = I_cg + m (|c|² 1 − c cᵀ)  →  I_cg = I_origin − m (|c|² 1 − c cᵀ)
    Ic = Io - m * (float(cg @ cg) * np.eye(3) - np.outer(cg, cg))
    return m, cg, Ic


def to_frd(v: np.ndarray) -> np.ndarray:
    return R_TO_FRD @ np.asarray(v, float)


def tensor_to_frd(I: np.ndarray) -> np.ndarray:
    return R_TO_FRD @ np.asarray(I, float) @ R_TO_FRD.T


def _component(name: str, m: float, cg_root: np.ndarray, Ic_root: np.ndarray, source: str) -> dict:
    I = tensor_to_frd(Ic_root)
    I = 0.5 * (I + I.T)
    return {"name": name, "mass_kg": round(float(m), 6),
            "cg_m": [round(float(x), 6) for x in to_frd(cg_root)],
            "shape": {"kind": "inertia", "inertia_kg_m2": [[round(float(x), 7) for x in row] for row in I]},
            "source": source}


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_ledger(bodies_path: Path | str, overrides_path: Path | str) -> dict:
    bodies_path, overrides_path = Path(bodies_path), Path(overrides_path)
    bodies = read_bodies(bodies_path)
    ov = json.loads(overrides_path.read_text(encoding="utf-8"))
    log: list[str] = []

    # 1. fuel out of the dry set
    fuel_rules = ov.get("fuel", {}).get("bodies", [])
    fuel_bodies = [b for b in bodies if any(_matches(r, b) for r in fuel_rules)]
    if fuel_rules and len(fuel_bodies) != len(fuel_rules):
        raise FusionExportError(f"fuel rules matched {len(fuel_bodies)} bodies, expected {len(fuel_rules)}")
    dry = [b for b in bodies if b not in fuel_bodies]

    # 2. density overrides
    for rule in ov.get("density_overrides", []):
        hits = [b for b in dry if _matches(rule, b)]
        if not hits:
            raise FusionExportError(f"density override matched nothing: {rule['path_glob']} :: {rule['body']}")
        for h in hits:
            dry[dry.index(h)] = h.rescaled(float(rule["density_kg_m3"]))
        log.append(f"density {rule['density_kg_m3']} kg/m^3 on {len(hits)} bodies ({rule['path_glob']} :: "
                   f"{rule['body']}): {rule['reason']}")

    # 3. group by top-level occurrence
    groups: dict[str, list[Body]] = {}
    for b in dry:
        groups.setdefault(b.top, []).append(b)
    comps = []
    for top, bs in sorted(groups.items(), key=lambda kv: -sum(b.mass_kg for b in kv[1])):
        m, cg, Ic = aggregate(bs)
        n_hidden = sum(1 for b in bs if not b.visible)
        touched = [b for b in bs if any(_matches(r, b) for r in ov.get("density_overrides", []))]
        src = (f"Fusion 'Weight Estimates CAD' top-level occurrence '{top}': {len(bs)} bodies, "
               f"materials {sorted({b.material for b in bs})}; tensor about own CG from Fusion origin "
               f"moments (tensor convention), root→FRD diag(-1,1,-1)"
               + (f"; {n_hidden} hidden bodies included" if n_hidden else "")
               + (f"; {len(touched)} bodies re-densified per overrides" if touched else ""))
        comps.append(_component(f"fusion:{top}", m, cg, Ic, src))

    # 4. declared extra components (root-frame mm points)
    for e in ov.get("extra_components", []):
        cg_root = np.asarray(e["cg_root_mm"], float) * 1e-3
        comps.append({"name": e["name"], "mass_kg": float(e["mass_kg"]),
                      "cg_m": [round(float(x), 6) for x in to_frd(cg_root)],
                      "shape": {"kind": "point"}, "source": f"DECLARED: {e['reason']}"})

    # 5. balance mass sized to the target dry CG (x only)
    bal = ov.get("balance")
    balance_mass = 0.0
    if bal:
        m_tot = sum(c["mass_kg"] for c in comps)
        x_cg = sum(c["mass_kg"] * c["cg_m"][0] for c in comps) / m_tot
        x_t = float(bal["target_dry_cg_x_frd_m"])
        x_b = float(bal["cg_frd_m"][0])
        if x_b <= x_t:
            raise FusionExportError("balance station must be forward (larger x_FRD) of the target CG")
        # m_b such that (m_tot x_cg + m_b x_b)/(m_tot + m_b) = x_t
        balance_mass = max(0.0, m_tot * (x_t - x_cg) / (x_b - x_t))
        if balance_mass > 0:
            comps.append({"name": bal["name"], "mass_kg": round(balance_mass, 4),
                          "cg_m": [float(v) for v in bal["cg_frd_m"]], "shape": {"kind": "point"},
                          "source": f"DECLARED, sized here ({balance_mass:.3f} kg puts the dry CG at "
                                    f"x_FRD = {x_t:+.3f} m from {x_cg:+.4f} m): {bal['reason']}"})
        log.append(f"balance {balance_mass:.3f} kg at x_FRD {x_b:+.2f} m → dry CG x {x_t:+.3f} m")

    # 6. the fuel block
    fuel_doc = None
    if fuel_bodies:
        rho = float(ov["fuel"]["density_kg_m3"])
        vol_m3 = sum(b.volume_cm3 for b in fuel_bodies) * 1e-6
        mf, cgf, _ = aggregate([b.rescaled(rho) for b in fuel_bodies])
        fuel_doc = {"volume_l": round(vol_m3 * 1e3, 3), "density_kg_m3": rho,
                    "mass_full_kg": round(mf, 4), "cg_m": [round(float(x), 6) for x in to_frd(cgf)],
                    "bodies": [f"{b.path}::{b.name}" for b in fuel_bodies],
                    "source": ov["fuel"]["reason"]}

    all_m, all_cg, _ = aggregate(bodies)
    dry_m, dry_cg, _ = aggregate(dry)
    notes = (f"GENERATED by `streamline massprops from-fusion` from {bodies_path.name} "
             f"(sha256 {_sha(bodies_path)[:12]}, {len(bodies)} bodies) with {overrides_path.name} "
             f"(sha256 {_sha(overrides_path)[:12]}). Fusion root frame = OpenVSP frame, converted to FRD by "
             f"diag(-1,1,-1). As exported: all bodies {all_m:.3f} kg at x_root {all_cg[0]*1e3:+.1f} mm; "
             f"dry after overrides {dry_m:.3f} kg at x_root {dry_cg[0]*1e3:+.1f} mm. Overrides: "
             + " | ".join(log) + ". Open questions: " + " | ".join(ov.get("open_questions", [])))
    doc = {"notes": notes, "components": comps,
           "provenance": {"generator": "streamline.massprops_fusion", "bodies_file": bodies_path.name,
                          "bodies_sha256": _sha(bodies_path), "overrides_file": overrides_path.name,
                          "overrides_sha256": _sha(overrides_path), "frame": ov.get("frame")}}
    if fuel_doc:
        doc["fuel"] = fuel_doc
    return doc


def write_ledger(doc: dict, out: Path | str) -> Path:
    from aerodb_contract import canonical_json
    out = Path(out)
    canonical_json.write(out, doc)
    return out
