"""Assemble engine_deck.json from bench runs + a committed spec (projects/<ac>/engine/spec.json).

The spec declares everything the bench cannot measure — the datasheet block, the thrust model
(no load cell ⇒ power law with a declared exponent), fuel density/capacity, installation — and
names the bench bags. `build()` runs the fits, evaluates the maps on the deck's setting axis, and
writes per-field provenance so a reader can tell datasheet from measured from prior at a glance.
Pure given (spec, runs): no clock, no host; determinism-diffable like the aero side.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from aerodb_contract import canonical_json, schema as contract_schema

from . import fit as fit_mod, ingest


class EngineSpecError(ValueError):
    pass


_REQUIRED = ("engine", "bench_bags", "datasheet", "thrust_model", "fuel", "thrust_line",
             "setting_axis_rpm", "test_date", "notes")


def load_spec(path: Path | str) -> dict:
    p = Path(path)
    spec = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in spec]
    if missing:
        raise EngineSpecError(f"{p}: engine spec is missing {missing}")
    ds = spec["datasheet"]
    for k in ("rpm_idle", "rpm_max_continuous", "rpm_max_transient", "thrust_N_at_max_transient",
              "fuel_g_min_at_max_thrust", "source"):
        if k not in ds:
            raise EngineSpecError(f"{p}: datasheet.{k} missing")
    tm = spec["thrust_model"]
    if tm.get("kind") != "power_law":
        raise EngineSpecError(f"{p}: only thrust_model.kind='power_law' is supported until a load cell exists")
    if not (1.0 <= float(tm["exponent"]) <= 4.0):
        raise EngineSpecError(f"{p}: thrust_model.exponent {tm['exponent']} is not a turbojet exponent (1–4)")
    if float(spec["fuel"]["density_kg_m3"]) <= 0:
        raise EngineSpecError(f"{p}: fuel.density_kg_m3 must be > 0")
    spec["_path"] = str(p)
    return spec


def build(spec: dict, runs: list[ingest.BenchRun]) -> dict:
    ds = spec["datasheet"]
    tm = spec["thrust_model"]
    rho_f = float(spec["fuel"]["density_kg_m3"])
    n_idle = float(ds["rpm_idle"])
    n_cont = float(ds["rpm_max_continuous"])
    n_trans = float(ds["rpm_max_transient"])

    # --- fits -----------------------------------------------------------------------------------
    windows = []
    for r in runs:
        windows += fit_mod.steady_windows(r)
    spec_pt = (n_trans, float(ds["fuel_g_min_at_max_thrust"]) / (rho_f / 1000.0))   # g/min → mL/min
    ff_fit = fit_mod.fit_fuel_flow(windows, degree=int(spec.get("fuel_fit_degree", 2)), spec_point=spec_pt)
    spool = fit_mod.fit_spool(runs)

    # --- setting axis + maps --------------------------------------------------------------------
    axis = np.asarray(spec["setting_axis_rpm"], dtype=float)
    if axis[0] < n_idle - 1 or axis[-1] > n_trans + 1:
        raise EngineSpecError(f"setting_axis_rpm must lie within [idle {n_idle}, max transient {n_trans}]")
    ff_ml_min = fit_mod.eval_fuel_flow_ml_min(ff_fit, axis)
    ff_kg_s = ff_ml_min * (rho_f / 1e6) / 60.0
    egt_C = np.interp(axis, [w.rpm for w in sorted(windows, key=lambda w: w.rpm)],
                      [w.egt_C for w in sorted(windows, key=lambda w: w.rpm)])
    t_anchor = float(ds["thrust_N_at_max_transient"])
    thrust = t_anchor * (axis / n_trans) ** float(tm["exponent"])

    files = []
    for r in runs:
        for name, sha in sorted(r.file_sha256.items()):
            files.append({"path": f"bench/{r.name}/{name}", "sha256": sha,
                          "role": "steady+spool" if r.has_throttle() else "steady"})
    primary_sha = files[0]["sha256"]

    doc = {
        "schema": {"name": "engine_deck", "version": contract_schema.SCHEMA_VERSION},
        "engine": spec["engine"],
        "static": {
            "setting_kind": "rpm",
            "setting": axis.tolist(),
            "thrust_N": thrust.tolist(),
            "fuel_flow_kg_s": ff_kg_s.tolist(),
            "egt_K": (egt_C + 273.15).tolist(),
            "source": {
                "thrust_N": "estimated",
                "fuel_flow_kg_s": "fitted",
                "egt_K": "measured",
                "notes": (f"thrust: {tm['kind']} k={tm['exponent']} anchored at datasheet "
                          f"{t_anchor} N @ {n_trans:.0f} rpm — NO bench thrust exists; fuel: degree-"
                          f"{ff_fit.degree} polynomial through {ff_fit.n_points} points "
                          f"({len(windows)} steady bench windows + datasheet spec point), RMS "
                          f"{ff_fit.rms_ml_min:.1f} mL/min, ECU volumetric flow UNCALIBRATED (manual "
                          f"§8.6); egt: linear interp of steady windows"),
            },
        },
        "limits": {"setting_idle": n_idle, "setting_max_continuous": n_cont,
                   "setting_max_transient": n_trans, "source": "datasheet"},
        "fuel": {"capacity_kg": float(spec["fuel"]["capacity_kg"]), "density_kg_m3": rho_f,
                 "type": spec["fuel"]["type"]},
        "thrust_model": {"kind": "power_law", "exponent": float(tm["exponent"]),
                         "anchor_thrust_N": t_anchor, "anchor_setting": n_trans, "source": "estimated"},
        "dynamics": {
            "spool_up_time_constant_s": spool.tau_up_s,
            "spool_down_time_constant_s": spool.tau_down_s,
            "slew_up_per_s": spool.slew_up_rpm_s,
            "slew_down_per_s": spool.slew_down_rpm_s,
            "spool_fit": {"method": spool.method, "n_steps_up": spool.n_up, "n_steps_down": spool.n_down,
                          "n_runs_slew_up": spool.n_slew_up, "n_runs_slew_down": spool.n_slew_down,
                          "steps": [vars(s) for s in spool.steps]},
            "source": "fitted",
        },
        "ambient": {"pressure_Pa": float(spec.get("ambient_pressure_Pa", 94500.0)),
                    "temperature_K": float(spec.get("ambient_temperature_K", 291.0))},
        "thrust_line": {"point_m": [float(x) for x in spec["thrust_line"]["point_m"]],
                        "direction_b": [float(x) for x in spec["thrust_line"]["direction_b"]]},
        "status": "estimated",
        "provenance": {"bench_file_sha256": primary_sha, "bench_files": files,
                       "test_date": spec["test_date"], "notes": spec["notes"],
                       "contract_version": contract_schema.SCHEMA_VERSION},
    }
    doc = canonical_json.to_jsonable(doc)
    contract_schema.check(doc, "engine_deck")
    return doc


def build_from_spec(spec_path: Path | str) -> dict:
    spec = load_spec(spec_path)
    base = Path(spec_path).parent
    runs = ingest.load_bags([base / "bench" / b for b in spec["bench_bags"]])
    return build(spec, runs)
