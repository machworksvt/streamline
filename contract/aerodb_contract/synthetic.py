"""A synthetic, physically plausible AeroDB (and siblings) for tests and for the ingest proof.

Linear derivatives with static stability, laid onto the v0 grid and written in the contract's own
shape. It is what the lint and sign fixtures are developed against, what the CasADi ingest test
interpolates, and what a consumer can use before a real release exists. It is NOT an aircraft;
`aircraft.name` says `synthetic` and `provenance.backend.name` says `synthetic` so nothing can
mistake it for one.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from . import canonical_json, completeness as comp, conventions as cv, schema

# Icarus-like numbers, per radian, chosen to satisfy every sign fixture and lint band.
DERIVS = {
    "CL0": 0.20, "CL_a": 5.0, "CD0": 0.030, "K": 0.045, "Cm0": 0.05, "Cm_a": -0.80,
    "CY_b": -0.40, "Cl_b": -0.08, "Cn_b": 0.10,
    "CL_q": 6.0, "Cm_q": -12.0, "CY_p": -0.05, "Cl_p": -0.45, "Cn_p": -0.03,
    "CY_r": 0.20, "Cl_r": 0.10, "Cn_r": -0.15,
    # flaps: increments per rad of detent
    "dCL_f": 0.8, "dCm_f": -0.20, "dCD_f": 0.04,
}
# TE-down positive per surface: (CX, CY, CZ, Cl, Cm, Cn) per rad
CONTROL = {
    "aileron_left":      (0.0,  0.00, -0.15,  0.10, 0.00, -0.010),
    "aileron_right":     (0.0,  0.00, -0.15, -0.10, 0.00,  0.010),
    "stabilator":        (0.0,  0.00, -0.50,  0.00, -1.50, 0.000),
    "ruddervator_left":  (0.0,  0.15, -0.15,  0.02, -0.40, -0.060),
    "ruddervator_right": (0.0, -0.15, -0.15, -0.02, -0.40,  0.060),
}
GEOM = {"S_m2": 0.56, "b_m": 2.08, "cbar_m": 0.27, "ref_point": [-0.55, 0.0, 0.0]}
FAKE_SHA = hashlib.sha256(b"synthetic").hexdigest()


def _wind_to_body(cl, cd, cy, alpha, beta):
    ca, sa, cb, sb = math.cos(alpha), math.sin(alpha), math.cos(beta), math.sin(beta)
    cx = -cd * ca * cb + cl * sa
    cz = -cd * sa * cb - cl * ca
    cyb = cy - cd * sb
    return cx, cyb, cz


def synthetic_aerodb(*, alpha_deg=(-8, 16, 2), beta_deg=(-15, 15, 5), airspeed=(20.0, 30.0, 45.0),
                     flap_deg=(0.0, 15.0, 30.0), altitude_m=533.4) -> dict:
    d = DERIVS
    alpha = np.radians(np.arange(alpha_deg[0], alpha_deg[1] + 1e-9, alpha_deg[2]))
    beta = np.radians(np.arange(beta_deg[0], beta_deg[1] + 1e-9, beta_deg[2]))
    V = np.asarray(airspeed, float)
    flap = np.radians(np.asarray(flap_deg, float))
    shape = (flap.size, V.size, beta.size, alpha.size)

    base = {c: np.zeros(shape) for c in cv.COEFFICIENTS}
    for i, f in enumerate(flap):
        for j in range(V.size):
            for k, b in enumerate(beta):
                for m, a in enumerate(alpha):
                    cl = d["CL0"] + d["CL_a"] * a + d["dCL_f"] * f
                    cd = d["CD0"] + d["K"] * cl * cl + d["dCD_f"] * f
                    cy = d["CY_b"] * b
                    cx, cyb, cz = _wind_to_body(cl, cd, cy, a, b)
                    base["CX"][i, j, k, m] = cx
                    base["CY"][i, j, k, m] = cyb
                    base["CZ"][i, j, k, m] = cz
                    base["Cl"][i, j, k, m] = d["Cl_b"] * b
                    base["Cm"][i, j, k, m] = d["Cm0"] + d["Cm_a"] * a + d["dCm_f"] * f
                    base["Cn"][i, j, k, m] = d["Cn_b"] * b

    def const(v):
        return np.full(shape, float(v))

    rate = {
        "p_hat": {"CX": const(0), "CY": const(d["CY_p"]), "CZ": const(0), "Cl": const(d["Cl_p"]), "Cm": const(0), "Cn": const(d["Cn_p"])},
        "q_hat": {"CX": const(0), "CY": const(0), "CZ": const(-d["CL_q"]), "Cl": const(0), "Cm": const(d["Cm_q"]), "Cn": const(0)},
        "r_hat": {"CX": const(0), "CY": const(d["CY_r"]), "CZ": const(0), "Cl": const(d["Cl_r"]), "Cm": const(0), "Cn": const(d["Cn_r"])},
    }
    control = {s: {c: const(v) for c, v in zip(cv.COEFFICIENTS, vals)} for s, vals in CONTROL.items()}

    # stall bookkeeping from a CL_max guess per detent
    cl_max = [1.2, 1.5, 1.7][: flap.size]
    beyond = []
    for i in range(flap.size):
        for j in range(V.size):
            for k in range(beta.size):
                for m, a in enumerate(alpha):
                    cl = -base["CZ"][i, j, k, m] * math.cos(a) + base["CX"][i, j, k, m] * math.sin(a)
                    if cl > cl_max[i]:
                        beyond.append({"flap_i": i, "V_i": j, "beta_i": k, "alpha_i": m, "CL": round(cl, 4)})

    rho0, T0, p0 = 1.225, 288.15, 101325.0
    T = T0 - 0.0065 * altitude_m
    rho = rho0 * (T / T0) ** 4.2559
    a_snd = math.sqrt(1.4 * 287.05 * T)
    mu = 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)

    doc = {
        "schema": {"name": "aerodb", "version": schema.SCHEMA_VERSION},
        "id": "synthetic-A.00000000.00000000",
        "aircraft": {"name": "synthetic", "geometry_rev": "A", "geometry_file": "synthetic.vsp3",
                     "geometry_sha256": FAKE_SHA},
        "conventions": cv.CONVENTIONS,
        "reference": {"S_m2": GEOM["S_m2"], "b_m": GEOM["b_m"], "cbar_m": GEOM["cbar_m"],
                      "moment_reference_point_m": GEOM["ref_point"]},
        "surfaces": list(cv.SURFACES),
        "axes": {"alpha_rad": alpha.tolist(), "beta_rad": beta.tolist(),
                 "airspeed_m_s": V.tolist(), "flap_rad": flap.tolist()},
        "conditions": {"altitude_m": altitude_m, "atmosphere": "ISA",
                       "density_kg_m3": [rho] * V.size,
                       "mach": [float(v / a_snd) for v in V],
                       "reynolds_cbar": [float(rho * v * GEOM["cbar_m"] / mu) for v in V]},
        "tables": {"base": base, "rate": rate, "control": control},
        "model": {"composition": cv.CONVENTIONS["composition"],
                  "base_includes": ["synthetic_linear_model"], "flaps_enter_via": "axis"},
        "validity": {"alpha_rad": [float(alpha[0]), math.radians(12.0)],
                     "beta_rad": [float(beta[0]), float(beta[-1])],
                     "delta_rad_max": math.radians(25.0),
                     "notes": "synthetic linear model; no stall, no hinge moments",
                     "stall": {"cl_max_estimate": cl_max, "source": "synthetic", "points_beyond": beyond}},
        "provenance": {"backend": {"name": "synthetic", "openvsp_version": "n/a", "method": "linear-model",
                                   "unpinned": False, "settings": {}},
                       "campaign_sha256": FAKE_SHA, "streamline_commit": "synthetic",
                       "contract_version": schema.SCHEMA_VERSION,
                       "per_table_source": {"tables": "synthetic"},
                       "confidence": {"default": "unquantified"}},
        "knockdowns": {"control_effectiveness": {s: {"factor": 1.0, "uncertainty": None, "source": "unquantified"}
                                                 for s in cv.CONTROL_SURFACES}},
        "lint": {"version": 1, "results": []},
        "completeness": {"version": comp.CHECKLIST_VERSION,
                         "flags": [{"item": it.id, "status": "clear", "note": "synthetic"} for it in comp.CHECKLIST]},
    }
    # Plain JSON types throughout — a document, not a bag of arrays.
    return canonical_json.to_jsonable(doc)


def synthetic_massprops() -> dict:
    comps = [
        {"name": "structure", "mass_kg": 4.0, "cg_m": [-0.60, 0.0, 0.0], "source": "synthetic"},
        {"name": "engine", "mass_kg": 1.7, "cg_m": [-1.10, 0.0, 0.05], "source": "synthetic"},
        {"name": "fuel", "mass_kg": 3.6, "cg_m": [-0.55, 0.0, 0.02], "source": "synthetic"},
        {"name": "avionics+batteries", "mass_kg": 2.0, "cg_m": [-0.30, 0.0, 0.0], "source": "synthetic"},
        {"name": "chute", "mass_kg": 0.55, "cg_m": [-0.45, 0.0, -0.05], "source": "synthetic"},
    ]
    m = sum(c["mass_kg"] for c in comps)
    cg = sum(c["mass_kg"] * np.asarray(c["cg_m"]) for c in comps) / m
    I = np.zeros((3, 3))
    for c in comps:
        r = np.asarray(c["cg_m"]) - cg
        I += c["mass_kg"] * (float(r @ r) * np.eye(3) - np.outer(r, r))
    I += np.diag([0.5, 0.9, 1.3])  # local inertias, made up
    return {
        "schema": {"name": "massprops", "version": schema.SCHEMA_VERSION},
        "aircraft": {"name": "synthetic", "geometry_rev": "A", "geometry_sha256": FAKE_SHA},
        "mass_kg": m, "cg_m": cg.tolist(), "inertia_kg_m2": I.tolist(),
        "components": comps,
        "status": {"mass": "estimated", "cg": "estimated", "inertia": "estimated"},
        "confidence": {"mass": "medium", "cg": "low", "inertia": "low"},
        "provenance": {"method": "ledger_point_masses", "ledger_sha256": FAKE_SHA,
                       "contract_version": schema.SCHEMA_VERSION},
    }


def synthetic_engine_deck() -> dict:
    thr = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    return {
        "schema": {"name": "engine_deck", "version": schema.SCHEMA_VERSION},
        "engine": "synthetic turbojet",
        "static": {"setting_kind": "throttle_frac", "setting": thr,
                   "thrust_N": [float(200.0 * t ** 1.3) for t in thr],
                   "fuel_flow_kg_s": [float(0.009 * (0.15 + 0.85 * t)) for t in thr],
                   "source": {"thrust_N": "estimated", "fuel_flow_kg_s": "estimated"}},
        "limits": {"setting_idle": 0.0, "setting_max_continuous": 1.0, "source": "estimated"},
        "fuel": {"capacity_kg": 4.0, "density_kg_m3": 800.0, "type": "synthetic kerosene"},
        "thrust_model": {"kind": "power_law", "exponent": 1.3, "anchor_thrust_N": 200.0,
                         "anchor_setting": 1.0, "source": "estimated"},
        "dynamics": {"spool_up_time_constant_s": 0.8, "spool_down_time_constant_s": 0.5,
                     "slew_up_per_s": 0.15, "slew_down_per_s": 0.2, "source": "estimated"},
        "ambient": {"pressure_Pa": 93353.0, "temperature_K": 288.0},
        "thrust_line": {"point_m": [-1.10, 0.0, 0.05], "direction_b": [1.0, 0.0, 0.0]},
        "status": "estimated",
        "provenance": {"bench_file_sha256": FAKE_SHA, "test_date": "1970-01-01", "notes": "synthetic",
                       "contract_version": schema.SCHEMA_VERSION},
    }
