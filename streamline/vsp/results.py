from __future__ import annotations
import pandas as pd
from typing import Any, Dict, List

class VSPResultsError(RuntimeError): ...

def dump_available(vsp, results_id: str) -> Dict[str, str]:
    """
    Return {data_name: type} for everything in this Results. Type is 'double', 'int', 'string', 'matrix', etc.
    """
    out: Dict[str, str] = {}
    names = list(vsp.GetAllDataNames(results_id))  # :contentReference[oaicite:15]{index=15}
    for nm in names:
        t = vsp.GetResultsType(results_id, nm)  # e.g., RES_DATA_DOUBLE, ... (string)
        out[nm] = t
    return out

def get(vsp, results_id: str, name: str) -> Any:
    """
    Fetch a named payload with the correct getter based on reported type.
    """
    t = vsp.GetResultsType(results_id, name)
    if t == "RES_DATA_DOUBLE":
        return list(vsp.GetDoubleResults(results_id, name))
    if t == "RES_DATA_DOUBLE_MATRIX":
        return [list(row) for row in vsp.GetDoubleMatResults(results_id, name)]
    if t == "RES_DATA_INT":
        return list(vsp.GetIntResults(results_id, name))
    if t == "RES_DATA_STRING":
        return list(vsp.GetStringResults(results_id, name))
    # add others as needed
    return vsp.GetResults(results_id, name)  # fallback

# ---------- Helpers to our standardized tables ----------

def stability_derivs_to_df(vsp, results_id: str) -> pd.DataFrame:
    """
    Convert VSPAERO Stability results to our (set,config,op,wrt,variable)->[CX..Cn] table.
    Assumes the Results payloads use conventional VSPAERO names (alpha, beta, p_hat, etc.).
    """
    # Names differ slightly per version; list what's there:
    avail = dump_available(vsp, results_id)

    # Try common payloads (user can expand these as we confirm names via GetAllDataNames)
    wrt = []
    coeffs = []

    # Example names often present: "Alpha", "Beta", "p_hat", "q_hat", "r_hat", "dCmdalpha" etc.
    for candidate in ("Alpha", "Beta", "p_hat", "q_hat", "r_hat"):
        if candidate in avail:
            vals = get(vsp, results_id, candidate)
            # Treat as perturbation variables; pair up with derivatives if present
            for i, v in enumerate(vals):
                wrt.append((candidate, float(v)))

    # Coeff derivative matrices (names vary); this will be refined once we lock exact keys via List… inspection.
    # For now, load what is present into a long form.
    rows = []
    # Suppose the results include per-variable partials named: "dCX_dAlpha", etc.
    for name, typ in avail.items():
        if name.startswith("d") and "_d" in name:
            # crude parser: dCX_dAlpha -> (CX, Alpha)
            try:
                left, right = name.split("_d", 1)
                X = left[1:]   # CX,CY,…
                wrtvar = right
                vals = get(vsp, results_id, name)
                # Flatten to rows
                for i, val in enumerate(vals):
                    rows.append({"wrt": wrtvar, "variable": wrtvar, X: float(val)})
            except Exception:
                continue

    if not rows:
        # fallback empty frame with our columns
        return pd.DataFrame(columns=["set","config","op","wrt","variable","CX","CY","CZ","Cl","Cm","Cn"]).set_index(["set","config","op","wrt","variable"])

    df = pd.DataFrame(rows)
    # ensure all coefficient columns exist
    for c in ["CX","CY","CZ","Cl","Cm","Cn"]:
        if c not in df.columns: df[c] = None
    # caller will add (set,config,op) indexing before saving
    return df
