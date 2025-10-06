from __future__ import annotations
import json, pathlib
from typing import Dict, Any

DATA_ROOT = pathlib.Path(__file__).resolve().parents[2] / "data" / "taxonomy"

def load_dod_groups() -> Dict[str, Any]:
    p = DATA_ROOT / "dod_uav_groups.json"
    return json.loads(p.read_text(encoding="utf-8"))

def group_thresholds_SI(label: str) -> Dict[str, Any]:
    """Return thresholds converted to SI (kg, m, m/s)."""
    d = load_dod_groups()
    rec = next((g for g in d["groups"] if g["label"] == label), None)
    if not rec:
        raise KeyError(f"Unknown DoD group: {label}")

    # conversions
    LB_TO_KG = 0.45359237
    FT_TO_M = 0.3048
    KN_TO_MPS = 0.514444

    out = {"label": rec["label"]}

    if "mgtow_lb" in rec:
        rng = rec["mgtow_lb"]
        out["mgtow_kg"] = {k: v*LB_TO_KG for k,v in rng.items()}

    if "altitude" in rec:
        alt = rec["altitude"].copy()
        if "max_ft" in alt: alt["max_m"] = alt.pop("max_ft") * FT_TO_M
        if "typical_max_ft" in alt: alt["typical_max_m"] = alt.pop("typical_max_ft") * FT_TO_M
        if "typical_min_ft" in alt: alt["typical_min_m"] = alt.pop("typical_min_ft") * FT_TO_M
        out["altitude"] = alt

    if "speed_kn" in rec:
        sp = rec["speed_kn"].copy()
        if "max" in sp: sp["max_mps"] = sp.pop("max") * KN_TO_MPS
        out["speed"] = sp

    return out

