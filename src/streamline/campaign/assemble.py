"""Assembly: (campaign, raw rows) → the AeroDB document. Pure — no OpenVSP, no clock, no host.

This is the function the determinism double-run diffs (`make determinism`): the same campaign and
the same rows must produce the same bytes, twice, in two processes.

Composition decisions made here, all recorded in the artifact:

* base tables = VSPAERO inviscid + parasite `CD0(V)` rotated into body axes
  (`ΔC = −CD0·v̂`, `v̂ = (cosα cosβ, sinβ, sinα cosβ)`), flap-agnostic (`ParasiteDrag` knows
  nothing of deflection — the flap's own drag rise is in the inviscid solution only; stated in
  `validity.notes`).
* ALL rate tables = the analytic backend (`backends/analytic.py`): strip theory for p̂, tail
  volumes (campaign `analytic_rates`) for q̂/r̂ — VSPAERO's rate channels are quarantined on
  this pin (measured; vsp/rates.py). `Cn_p` and `Cl_r` vary with the local CL; `CL_α` is fitted
  from the assembled base tables at flap 0, middle V, β≈0, inside the declared validity range.
* control tables = the steady per-group derivatives, mapped from VSPAERO group names to contract
  surface names by the campaign's `surface_groups`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from aerodb_contract import canonical_json, completeness as comp, conventions as cv, lint as lint_mod
from aerodb_contract import load as contract_load, schema as contract_schema, signs as signs_mod
from aerodb_contract.completeness import CHECKLIST

from .. import atmosphere as atm
from ..backends import analytic
from .definition import Campaign, CampaignError


def read_rows(path: Path | str) -> dict[str, dict]:
    rows = {}
    with Path(path).open() as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row["key"]] = row
    return rows


def merge_shards(paths: list[Path]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for p in paths:
        for key, row in read_rows(p).items():
            if key in rows and rows[key] != row:
                raise CampaignError(f"{key} appears in two shards with different content")
            rows[key] = row
    return rows


def _wind_unit(alpha: float, beta: float) -> np.ndarray:
    return np.array([np.cos(alpha) * np.cos(beta), np.sin(beta), np.sin(alpha) * np.cos(beta)])


def _cl_grid(base: dict, alpha: np.ndarray) -> np.ndarray:
    """Wind-axis CL per grid point from body CX/CZ (β small-angle exact at β=0, adequate off it)."""
    a = alpha[np.newaxis, np.newaxis, np.newaxis, :]
    return -base["CZ"] * np.cos(a) + base["CX"] * np.sin(a)


def assemble(campaign: Campaign, rows: dict[str, dict], *, streamline_commit: str,
             completeness_flags: list[dict]) -> dict:
    alpha, beta = campaign.alpha_rad, campaign.beta_rad
    V, flap = campaign.airspeed, campaign.flap_rad
    shape = (flap.size, V.size, beta.size, alpha.size)

    meta = rows.get("meta")
    if meta is None:
        raise CampaignError("raw rows carry no meta row — shard 0 did not finish")

    # --- base + control from the stab rows -----------------------------------------------------
    base = {c: np.full(shape, np.nan) for c in cv.COEFFICIENTS}
    control = {s: {c: np.full(shape, np.nan) for c in cv.COEFFICIENTS} for s in cv.CONTROL_SURFACES}
    groups = campaign.surface_groups
    missing = []
    reference = None
    for spec in campaign.stab_points():
        row = rows.get(spec.key)
        if row is None:
            missing.append(spec.key)
            continue
        idx = (spec.flap_i, spec.v_i, spec.beta_i, spec.alpha_i)
        for c in cv.COEFFICIENTS:
            base[c][idx] = row["base"][c]
        for surface in cv.CONTROL_SURFACES:
            gname = groups.get(surface)
            if gname is None:
                raise CampaignError(f"campaign.surface_groups has no entry for {surface!r}")
            try:
                dc = row["d_control"][gname]
            except KeyError:
                raise CampaignError(f"{spec.key}: no control derivative for group {gname!r} "
                                    f"({surface}) — was the group exercised by the run?")
            for c in cv.COEFFICIENTS:
                control[surface][c][idx] = dc[c]
        if reference is None:
            fc = row["flight_condition"]
            reference = {"S_m2": fc["FC_Sref_"], "b_m": fc["FC_Bref_"], "cbar_m": fc["FC_Cref_"],
                         "moment_reference_point_m": campaign.moment_ref_m}
            settings_repr = row["settings"]
    if missing:
        raise CampaignError(f"{len(missing)} stab points absent from the rows, first: {missing[:5]}")

    # --- parasite CD0 rotated into the base ----------------------------------------------------
    cd0 = np.full(V.size, np.nan)
    for vi in range(V.size):
        prow = rows.get(f"parasite/{vi}")
        if prow is None:
            raise CampaignError(f"no parasite row for airspeed index {vi}")
        cd0[vi] = prow["cd0_total"]
    for fi in range(flap.size):
        for vi in range(V.size):
            for bi, b in enumerate(beta):
                for ai, a in enumerate(alpha):
                    d = -cd0[vi] * _wind_unit(a, b)
                    base["CX"][fi, vi, bi, ai] += d[0]
                    base["CY"][fi, vi, bi, ai] += d[1]
                    base["CZ"][fi, vi, bi, ai] += d[2]

    # --- rate tables: ALL analytic (backends/analytic.py — VSPAERO's rate channels are
    # quarantined on this pin; the module docstring holds the measured evidence) ----------------
    cl = _cl_grid(base, alpha)
    lo, hi = campaign.validity["alpha_deg"]
    m = (alpha >= np.radians(lo)) & (alpha <= np.radians(hi))
    bi0 = int(np.argmin(np.abs(beta)))
    if m.sum() < 2:
        raise CampaignError("fewer than two α points inside the validity range; cannot fit CL_α")
    cl_alpha = float(np.polyfit(alpha[m], cl[0, V.size // 2, bi0, m], 1)[0])
    rate = {"p_hat": analytic.p_hat_column(cl_alpha, campaign.taper_ratio, cl),
            "q_hat": analytic.q_hat_column(campaign.analytic_rates,
                                           reference["S_m2"], reference["cbar_m"], shape),
            "r_hat": analytic.r_hat_column(campaign.analytic_rates,
                                           reference["S_m2"], reference["b_m"], cl)}

    # --- stall bookkeeping ---------------------------------------------------------------------
    cl_max = campaign.cl_max_estimate
    beyond = []
    for fi in range(flap.size):
        for vi in range(V.size):
            for bi in range(beta.size):
                for ai in range(alpha.size):
                    if cl[fi, vi, bi, ai] > cl_max[fi]:
                        beyond.append({"flap_i": fi, "V_i": vi, "beta_i": bi, "alpha_i": ai,
                                       "CL": round(float(cl[fi, vi, bi, ai]), 4)})

    isa = atm.isa(campaign.altitude_m)
    doc = {
        "schema": {"name": "aerodb", "version": contract_schema.SCHEMA_VERSION},
        "id": f"{campaign.aircraft}-{campaign.geometry_rev}.{campaign.sha256[:8]}.{streamline_commit[:8]}",
        "aircraft": {"name": campaign.aircraft, "geometry_rev": campaign.geometry_rev,
                     "geometry_file": campaign.geometry_file,
                     "geometry_sha256": meta["geometry_sha256"]},
        "conventions": cv.CONVENTIONS,
        "reference": reference,
        "surfaces": list(cv.SURFACES),
        "axes": {"alpha_rad": alpha.tolist(), "beta_rad": beta.tolist(),
                 "airspeed_m_s": V.tolist(), "flap_rad": flap.tolist()},
        "conditions": {"altitude_m": campaign.altitude_m, "atmosphere": "ISA",
                       "density_kg_m3": [isa.density_kg_m3] * V.size,
                       "mach": [isa.mach(float(v)) for v in V],
                       "reynolds_cbar": [isa.reynolds(float(v), reference["cbar_m"]) for v in V]},
        "tables": {"base": base, "rate": rate, "control": control},
        "model": {"composition": cv.CONVENTIONS["composition"],
                  "base_includes": ["vspaero_vlm_inviscid", "parasite_cd0_rotated_to_body"],
                  "flaps_enter_via": "axis"},
        "validity": {"alpha_rad": [np.radians(lo), np.radians(hi)],
                     "beta_rad": [float(beta[0]), float(beta[-1])] if beta.size > 1 else [-0.01, 0.01],
                     "delta_rad_max": np.radians(float(campaign.validity["delta_deg_max"])),
                     "notes": ("VLM + empirical CD0 (flap-agnostic). ALL rate derivatives are "
                               "analytic: p from strip theory; q/r from tail volumes with "
                               "explicit campaign inputs (wing Cm_q term, sidewash and fin "
                               "z-arm omitted, not invented). VSPAERO unsteady stability "
                               "channels quarantined on this pin: measured wrong-phased "
                               "response for surfaces at a lever arm. "
                               + campaign.validity.get("notes", "")),
                     "stall": {"cl_max_estimate": cl_max, "source": campaign.validity.get(
                         "cl_max_source", "campaign estimate"), "points_beyond": beyond}},
        "provenance": {"backend": {"name": "vspaero", "openvsp_version": meta["openvsp_version"],
                                   "method": "VLM", "unpinned": not meta["pinned"],
                                   "settings": settings_repr},
                       "campaign_sha256": campaign.sha256,
                       "streamline_commit": streamline_commit,
                       "contract_version": contract_schema.SCHEMA_VERSION,
                       "per_table_source": {"tables.base": "vspaero-steady+parasite",
                                            "tables.control": "vspaero-steady",
                                            "tables.rate.q_hat": analytic.SOURCE_ID_TAIL,
                                            "tables.rate.r_hat": analytic.SOURCE_ID_TAIL,
                                            "tables.rate.p_hat": analytic.SOURCE_ID},
                       "confidence": {"default": "unquantified",
                                      "tables.rate.p_hat": "low",
                                      "tables.rate.q_hat": "low",
                                      "tables.rate.r_hat": "low"}},
        "knockdowns": {"control_effectiveness": {s: {"factor": 1.0, "uncertainty": None,
                                                     "source": "unquantified"}
                                                 for s in cv.CONTROL_SURFACES}},
        "lint": {"version": lint_mod.LINT_VERSION, "results": []},
        "completeness": {"version": comp.CHECKLIST_VERSION, "flags": completeness_flags},
    }
    doc = canonical_json.to_jsonable(doc)

    # --- embed lint + signs (on the document as a consumer will see it) ------------------------
    adb = contract_load.AeroDB.from_doc(doc)
    doc["lint"]["results"] = lint_mod.run_lint(adb, sign_waivers=campaign.sign_waivers)
    contract_schema.check(doc, "aerodb")
    return doc


def audit_completeness(geometry, campaign: Campaign, *, has_ledger: bool,
                       has_engine_geometry: bool = False, has_gear: bool = False,
                       has_airfoils: bool = False) -> list[dict]:
    """The §8.7 checklist, filled from what the campaign and geometry can actually show. Items the
    audit cannot verify yet stay `open` — flags, not gates."""
    group_names = {g.name for g in geometry.control_groups}
    wanted = set(campaign.surface_groups.values())
    surfaces_ok = wanted <= group_names

    def flag(item_id, ok, note=""):
        return {"item": item_id, "status": "clear" if ok else "open", "note": note}

    flags = [
        flag("reference_quantities", True, f"RefFlag from wing {campaign.reference_wing!r}, cref echo-checked"),
        flag("moment_reference_point", any(abs(x) > 1e-12 for x in campaign.moment_ref_m)
             or campaign.doc.get("moment_reference_is_datum", False),
             "set by the campaign"),
        flag("surfaces_present", surfaces_ok, f"groups {sorted(wanted - group_names)} missing" if not surfaces_ok else ""),
        flag("surfaces_hinged", surfaces_ok, "hinges implied by VSPAERO subsurface controls"),
        flag("surface_vocabulary", surfaces_ok, ""),
        flag("flap_detents_defined", campaign.flap_group is not None or campaign.flap_rad.size == 1,
             "single detent, no flap group" if campaign.flap_group is None else ""),
        flag("engine_geometry", has_engine_geometry, ""),
        flag("gear_geometry", has_gear, ""),
        flag("mass_ledger", has_ledger, ""),
        flag("airfoils_defined", has_airfoils, ""),
    ]
    errs = comp.validate_flags(flags)
    if errs:  # pragma: no cover — the list above tracks the checklist by construction
        raise CampaignError("; ".join(errs))
    return flags
