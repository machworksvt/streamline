from __future__ import annotations
import numpy as np
from typing import Tuple, Dict, List

# Angles helpers
def deg2rad(x): return np.deg2rad(x)
def rad2deg(x): return np.rad2deg(x)

# --- Stability <-> Body axes coefficient conversion (small angles assumption okay for tooling) ---

def _wind_to_body_D(alpha_rad: float, beta_rad: float) -> np.ndarray:
    """
    Rotation from wind (stability) to body axes for forces/moments mapping.
    Returns 6x6 block-diagonal matrix for [X,Y,Z,L,M,N] assuming standard convention.
    """
    ca, sa = np.cos(alpha_rad), np.sin(alpha_rad)
    cb, sb = np.cos(beta_rad), np.sin(beta_rad)

    # Force transform (3x3) wind->body
    # Xb =  ca*Cb * Xw + ...   (we use canonical mapping via yaw(beta) then pitch(alpha))
    Rz_beta = np.array([[ cb,  sb, 0],
                        [-sb,  cb, 0],
                        [  0,   0, 1]])
    Ry_alpha = np.array([[ ca, 0, -sa],
                         [  0, 1,   0],
                         [ sa, 0,  ca]])
    F = Ry_alpha @ Rz_beta  # wind->body

    # Moments use same rotation about axes for coefficient components
    M = F.copy()
    D = np.zeros((6,6))
    D[:3,:3] = F
    D[3:,3:] = M
    return D

def coeffs_stab_to_body(alpha_rad: float, beta_rad: float, CX: float, CY: float, CZ: float,
                        Cl: float, Cm: float, Cn: float) -> Tuple[float,float,float,float,float,float]:
    v = np.array([CX, CY, CZ, Cl, Cm, Cn], dtype=float)
    body = _wind_to_body_D(alpha_rad, beta_rad) @ v
    return tuple(body.tolist())

# Control bus schema from groups
def make_control_bus_schema(group_names: List[str], include_throttle: bool = True) -> Dict:
    signals = [{"name": f"delta_{g}", "unit": "rad"} for g in group_names]
    if include_throttle:
        signals.append({"name":"throttle","unit":"1"})
    return {"bus_name": "StreamlineControls", "signals": signals}
