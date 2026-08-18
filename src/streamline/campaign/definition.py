"""The campaign definition: the envelope is this file and nothing else.

Widening α, adding an airspeed or a flap detent is an edit to the JSON plus a re-release; the
artifact's axes and validity follow automatically. The definition's canonical-JSON sha256 is half
of the release id, so two releases from different grids can never collide.

Point enumeration order is FIXED — (flap, V, β, α), α fastest — and is the ABI of `raw.jsonl`:
the assembler indexes rows by their point key, and shards are contiguous slices of this order.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from aerodb_contract import canonical_json


class CampaignError(ValueError):
    pass


@dataclass(frozen=True)
class StabPointSpec:
    index: int
    flap_i: int
    v_i: int
    beta_i: int
    alpha_i: int
    flap_rad: float
    airspeed_m_s: float
    beta_rad: float
    alpha_rad: float

    @property
    def key(self) -> str:
        return f"stab/{self.flap_i}/{self.v_i}/{self.beta_i}/{self.alpha_i}"


@dataclass(frozen=True)
class Campaign:
    doc: dict
    path: Path
    sha256: str

    # --- identity -----------------------------------------------------------------------------
    @property
    def aircraft(self) -> str:
        return self.doc["aircraft"]

    @property
    def geometry_rev(self) -> str:
        return self.doc["geometry_rev"]

    @property
    def geometry_file(self) -> str:
        return self.doc["geometry_file"]

    @property
    def expected_geometry_sha256(self) -> str:
        return self.doc["geometry_sha256"]

    # --- grid ---------------------------------------------------------------------------------
    @property
    def alpha_rad(self) -> np.ndarray:
        return np.radians(np.asarray(self.doc["grid"]["alpha_deg"], dtype=float))

    @property
    def beta_rad(self) -> np.ndarray:
        return np.radians(np.asarray(self.doc["grid"]["beta_deg"], dtype=float))

    @property
    def airspeed(self) -> np.ndarray:
        return np.asarray(self.doc["grid"]["airspeed_m_s"], dtype=float)

    @property
    def flap_rad(self) -> np.ndarray:
        return np.radians(np.asarray(self.doc["grid"]["flap_deg"], dtype=float))

    @property
    def altitude_m(self) -> float:
        return float(self.doc["altitude_m"])

    @property
    def cref_m(self) -> float:
        """Reference chord, stated explicitly (§3.1: explicit beats derived) and checked against
        VSPAERO's FC_Cref_ echo by the runner after the first point."""
        return float(self.doc["cref_m"])

    @property
    def moment_ref_m(self) -> list:
        return [float(x) for x in self.doc["moment_reference_point_m"]]

    @property
    def reference_wing(self) -> str:
        """Name of the geom whose VSPAERO reference quantities define S, b, c̄."""
        return self.doc["reference_wing"]

    @property
    def vlm_set(self) -> str:
        """Name of the OpenVSP set solved as thin VLM surfaces (stab + rate runs). Explicit
        because real models carry non-aero geoms — fuel-mass conformals, servo CAD meshes, stowed
        gear — that "All" would silently lift (found on icarus rev A)."""
        return self.doc["vlm_set"]

    @property
    def parasite_set(self) -> str:
        """Name of the set whose wetted areas feed the parasite-drag buildup. Distinct from
        vlm_set: bodies (fuselage, nacelle, intakes) belong here and not in the VLM solve."""
        return self.doc["parasite_set"]

    @property
    def surface_groups(self) -> dict:
        """contract surface name → VSPAERO control-group name. Flap groups are named too (the
        geometry applies their detent) but never appear as control derivatives."""
        return dict(self.doc["surface_groups"])

    @property
    def flap_group(self) -> str | None:
        return self.doc.get("flap_group")

    @property
    def solver(self) -> dict:
        return dict(self.doc["solver"])

    @property
    def analytic_rates(self) -> dict:
        """Geometric inputs for the analytic q̂/r̂ tables (backends/analytic.py): tail areas,
        arms from the moment reference, lift-curve slopes, efficiencies, downwash gradient. ALL
        rate derivatives are analytic in v0 — VSPAERO's unsteady stability analyses render
        wrong-phased physics for surfaces at a lever arm on this pin (measured; see
        vsp/rates.py). Explicit numbers here, derivations in the campaign's `_` note."""
        return dict(self.doc["analytic_rates"])

    @property
    def cl_max_estimate(self) -> list:
        return [float(x) for x in self.doc["cl_max_estimate"]]

    @property
    def sign_waivers(self) -> tuple[str, ...]:
        return tuple(self.doc.get("sign_waivers", []))

    @property
    def taper_ratio(self) -> float:
        return float(self.doc["taper_ratio"])

    @property
    def validity(self) -> dict:
        return dict(self.doc["validity"])

    # --- enumeration --------------------------------------------------------------------------
    def stab_points(self) -> list[StabPointSpec]:
        out = []
        idx = 0
        for fi, f in enumerate(self.flap_rad):
            for vi, V in enumerate(self.airspeed):
                for bi, b in enumerate(self.beta_rad):
                    for ai, a in enumerate(self.alpha_rad):
                        out.append(StabPointSpec(idx, fi, vi, bi, ai, float(f), float(V), float(b), float(a)))
                        idx += 1
        return out

    def shard(self, k: int, n: int) -> list[StabPointSpec]:
        """Contiguous slice k of n of the stab points. Parasite rows always run in shard 0 —
        they are minutes, and one owner keeps the bookkeeping simple. (Rate tables are analytic,
        computed at assembly — no solver rows.)"""
        pts = self.stab_points()
        if not 0 <= k < n:
            raise CampaignError(f"shard {k}/{n} out of range")
        per = math.ceil(len(pts) / n)
        return pts[k * per:(k + 1) * per]


_REQUIRED = ("aircraft", "geometry_rev", "geometry_file", "geometry_sha256", "grid", "altitude_m", "cref_m",
             "moment_reference_point_m", "reference_wing", "vlm_set", "parasite_set",
             "surface_groups", "solver", "analytic_rates",
             "cl_max_estimate", "taper_ratio", "validity")


def load(path: Path | str) -> Campaign:
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise CampaignError(f"{p}: campaign is missing {missing}")
    grid = doc["grid"]
    for k in ("alpha_deg", "beta_deg", "airspeed_m_s", "flap_deg"):
        v = grid.get(k)
        if not isinstance(v, list) or not v:
            raise CampaignError(f"{p}: grid.{k} must be a non-empty list")
        if len(v) > 1 and not all(b > a for a, b in zip(v, v[1:])):
            raise CampaignError(f"{p}: grid.{k} must be strictly increasing")
    if len(doc["cl_max_estimate"]) != len(grid["flap_deg"]):
        raise CampaignError(f"{p}: cl_max_estimate must have one entry per flap detent")
    for k in ("ncpu", "wake_iters", "num_wake_nodes"):
        if k not in doc["solver"]:
            raise CampaignError(f"{p}: solver.{k} missing")
    ar = doc["analytic_rates"]
    for key in ("horizontal_tails", "vertical_tails", "depsilon_dalpha"):
        if key not in ar:
            raise CampaignError(f"{p}: analytic_rates.{key} missing")
    if not 0.0 <= float(ar["depsilon_dalpha"]) <= 0.8:
        raise CampaignError(f"{p}: analytic_rates.depsilon_dalpha {ar['depsilon_dalpha']} is not a downwash gradient")
    for kind in ("horizontal_tails", "vertical_tails"):
        if not isinstance(ar[kind], list) or not ar[kind]:
            raise CampaignError(f"{p}: analytic_rates.{kind} must be a non-empty list "
                                "(a config with genuinely no tail must say so with an explicit "
                                "zero-area entry, not an absence)")
        for t in ar[kind]:
            for f in ("name", "S_m2", "arm_m", "a_per_rad", "eta"):
                if f not in t:
                    raise CampaignError(f"{p}: analytic_rates.{kind} entry missing {f!r}")
            if float(t["S_m2"]) < 0 or float(t["arm_m"]) <= 0:
                raise CampaignError(f"{p}: analytic_rates {t['name']!r}: S_m2 must be ≥0 and "
                                    "arm_m >0 (metres AFT of the moment reference)")
            if not (1.0 <= float(t["a_per_rad"]) <= 8.0 and 0.0 < float(t["eta"]) <= 1.2):
                raise CampaignError(f"{p}: analytic_rates {t['name']!r}: implausible a_per_rad or eta")
    return Campaign(doc=doc, path=p, sha256=canonical_json.sha256_of(doc))
