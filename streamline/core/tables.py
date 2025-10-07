from __future__ import annotations
import pandas as pd
from typing import Iterable, Dict, List

# ----- unit metadata helpers -----
SI_UNITS = {
    "coeffs": "-", "deg": "deg", "rad": "rad",
    "force_N": "N", "moment_Nm": "N·m",
    "speed_mps": "m/s", "altitude_m": "m", "mass_kg": "kg", "pressure_Pa":"Pa"
}

def _attach_units(df: pd.DataFrame, units: Dict[str,str]):  # convenience
    df.attrs["units"] = units
    return df

# ----- RAW stability derivatives (stability axes) -----
# index: (set, config, op, wrt, variable)   columns: CX CY CZ Cl Cm Cn
DERIV_COLS = ["CX","CY","CZ","Cl","Cm","Cn"]

def new_stability_derivs_table() -> pd.DataFrame:
    df = pd.DataFrame(columns=["set","config","op","wrt","variable"] + DERIV_COLS)
    df = df.astype({c:"float64" for c in DERIV_COLS})
    df = df.set_index(["set","config","op","wrt","variable"])
    return _attach_units(df, {"coeffs":"-", "angles":"rad"})

# ----- Parasite drag (raw) -----
def new_parasite_component_table() -> pd.DataFrame:
    cols = ["CD0_comp","wetted_area_m2","Re","form_factor","notes"]
    df = pd.DataFrame(columns=["set","config","op","component_name"]+cols)
    df = df.set_index(["set","config","op","component_name"])
    return _attach_units(df, {"CD0_comp":"-", "wetted_area_m2":"m^2"})

def new_parasite_total_table() -> pd.DataFrame:
    df = pd.DataFrame(columns=["set","config","op","CD0_total"]).set_index(["set","config","op"])
    return _attach_units(df, {"CD0_total":"-"})

# ----- Trim (raw) -----
def new_trim_table(control_groups: List[str]) -> pd.DataFrame:
    cols = ["alpha_rad","beta_rad","qbar_Pa","thrust_N","CL","CD","Cm"] + [f"delta_{g}_rad" for g in control_groups]
    df = pd.DataFrame(columns=["set","config","op"] + cols).set_index(["set","config","op"])
    return _attach_units(df, {"alpha_rad":"rad","beta_rad":"rad","qbar_Pa":"Pa","thrust_N":"N"})

# ----- Processed: op summary -----
def new_op_summary_table(control_groups: List[str]) -> pd.DataFrame:
    cols = [
        "rho_kgm3","a_mps","qbar_Pa","mach","tas_mps",
        "S_ref_m2","c_ref_m","b_ref_m","mass_kg","cg_x_m","cg_y_m","cg_z_m",
        "alpha_rad","beta_rad","thrust_N","CL","CD","Cm","feasible"
    ] + [f"delta_{g}_rad" for g in control_groups]
    df = pd.DataFrame(columns=["set","config","op"] + cols).set_index(["set","config","op"])
    return _attach_units(df, {"qbar_Pa":"Pa","thrust_N":"N","S_ref_m2":"m^2","c_ref_m":"m","b_ref_m":"m"})

# ----- Processed: control power margins -----
def new_control_power_table() -> pd.DataFrame:
    # index (set, config, op, axis) ; axis in {pitch, roll, yaw}
    cols = ["required_moment_Nm","available_moment_Nm","margin_Nm","required_deflection_deg","limit_deg"]
    df = pd.DataFrame(columns=["set","config","op","axis"] + cols).set_index(["set","config","op","axis"])
    return _attach_units(df, {"required_moment_Nm":"N·m","available_moment_Nm":"N·m","required_deflection_deg":"deg"})

# ----- Linear model: long-form ABCD -----
def new_abcd_table() -> pd.DataFrame:
    # Minimal empty schema; values appended later
    return pd.DataFrame(columns=["set","config","op","block","i","j","value"]).set_index(["set","config","op","block","i","j"])

def new_modes_table() -> pd.DataFrame:
    # index (set, config, op, mode)
    cols = ["zeta","omega_n_rad_s","freq_hz","tau_s","eig_real","eig_imag","class","level"]
    return pd.DataFrame(columns=["set","config","op","mode"] + cols).set_index(["set","config","op","mode"])
