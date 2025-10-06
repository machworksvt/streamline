# streamline/vsp/analysis.py
from __future__ import annotations
from typing import Any, List

class VSPAnalysisError(RuntimeError): ...

def list_analyses(vsp) -> List[str]:
    return list(vsp.ListAnalysis())

def get_inputs(vsp, analysis: str) -> List[str]:
    return list(vsp.GetAnalysisInputNames(analysis))

def doc(vsp, analysis: str) -> str:
    return vsp.GetAnalysisDoc(analysis)

# ---- Robust scalar setters (create-if-missing, then Set...) ----
def set_int_input(vsp, analysis: str, name: str, value: int) -> None:
    try:
        vec = vsp.GetIntAnalysisInput(analysis, name)
    except Exception:
        vec = []
    if not vec:
        vsp.SetIntAnalysisInput(analysis, name, [int(value)])
    else:
        v = list(vec); v[0] = int(value); vsp.SetIntAnalysisInput(analysis, name, v)

def set_double_input(vsp, analysis: str, name: str, value: float) -> None:
    try:
        vec = vsp.GetDoubleAnalysisInput(analysis, name)
    except Exception:
        vec = []
    if not vec:
        vsp.SetDoubleAnalysisInput(analysis, name, float(value))
    else:
        v = list(vec); v[0] = float(value); vsp.SetDoubleAnalysisInput(analysis, name, [v])

def set_string_input(vsp, analysis: str, name: str, value: str) -> None:
    try:
        vec = vsp.GetStringAnalysisInput(analysis, name)
    except Exception:
        vec = []
    if not vec:
        vsp.SetStringAnalysisInput(analysis, name, str(value))
    else:
        v = list(vec); v[0] = str(value); vsp.SetStringAnalysisInput(analysis, name, [v])

def set_vec3d_input(vsp, analysis: str, name: str, value: list[float] | tuple[float, float, float]) -> None:
    xyz = list(value)
    if len(xyz) != 3:
        raise VSPAnalysisError(f"{name} expects 3 elements, got {len(xyz)}")
    try:
        vec = vsp.GetVec3dAnalysisInput(analysis, name)
    except Exception:
        vec = []
    if not vec:
        vsp.SetVec3dAnalysisInput(analysis, name, xyz)
    else:
        v = list(vec); v[0] = xyz; vsp.SetVec3dAnalysisInput(analysis, name, [v])

def exec_analysis(vsp, analysis: str) -> str:
    res_id = vsp.ExecAnalysis(analysis)
    if not res_id:
        raise VSPAnalysisError(f"ExecAnalysis returned empty Results ID for {analysis}")
    return res_id
