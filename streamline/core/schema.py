from __future__ import annotations
from typing import Literal, Optional, Dict, List, Tuple
from pydantic import BaseModel, Field, field_validator

# -------------------------
# Enums / literals
# -------------------------
PropulsionType = Literal["electric_prop", "ic_prop", "micro_jet", "turbofan", "custom"]

# -------------------------
# Common structs
# -------------------------
class RunManifest(BaseModel):
    tool_versions: Dict[str, str] = Field(default_factory=dict)  # {"openvsp":"3.42.3", "streamline":"0.1.0"}
    vsp3_sha256: Optional[str] = None
    inputs_sha256: Optional[str] = None
    started_utc: Optional[str] = None
    ended_utc: Optional[str] = None
    source_paths: List[str] = Field(default_factory=list)

class ControlGroupSetting(BaseModel):
    name: str
    deflection_deg: float = 0.0
    limits_deg: Tuple[float, float] = (-25.0, 25.0)

class HingeSetting(BaseModel):
    device_name: str
    position: float  # deg or discrete index (interpretation is VSP-device specific)

class PayloadToggle(BaseModel):
    geom_name: str
    enabled: bool = True

# -------------------------
# Project-level schema
# -------------------------
class UAVDefinition(BaseModel):
    uav_id: str = "baseline"
    dod_group: Literal["Group 1", "Group 2", "Group 3", "Group 4", "Group 5"]
    propulsion_type: PropulsionType
    notes: str = ""

class MissionPhase(BaseModel):
    name: str
    type: Literal["takeoff","climb","cruise","loiter","descent","landing","sprint","reserve"]
    targets: Dict[str, float] = Field(default_factory=dict)  # {"speed_mps":..., "altitude_m":..., "mach":..., ...}
    constraints: Dict[str, float] = Field(default_factory=dict)
    weight: float = 1.0

class MissionDefinition(BaseModel):
    mission_id: str
    phases: List[MissionPhase] = Field(default_factory=list)
    environment: Dict[str, float] = Field(default_factory=dict)  # {"dISA_K":..., "wind_mps":...}
    reserves: Dict[str, float] = Field(default_factory=dict)     # {"energy_Wh":..., "time_s":...}
    objectives: Dict[str, float] = Field(default_factory=dict)

class PowerplantDefinition(BaseModel):
    powerplant_id: str
    type: PropulsionType
    maps: Dict[str, str | float | Dict] = Field(default_factory=dict)  # thrust/power/eta map descriptors
    dynamics: Dict[str, float] = Field(default_factory=dict)           # {"tau_s": 0.5}
    limits: Dict[str, float] = Field(default_factory=dict)             # {"max_thrust_N":..., ...}
    energy_model: Dict[str, float | Dict] = Field(default_factory=dict)

class OperatingPoint(BaseModel):
    op_name: str
    altitude_m: float
    mach: Optional[float] = None
    tas_mps: Optional[float] = None
    mass_override_kg: Optional[float] = None
    # TODO: inertia override?
    atmosphere_overrides: Dict[str, float] = Field(default_factory=dict)  # {"rho_kgm3":..., "a_mps":...}
    notes: str = ""

    @field_validator("mach", "tas_mps")
    @classmethod
    def _exclusive_speed(cls, v, info):
        # validation at instance level happens in model_post_init below
        return v

    def model_post_init(self, __context):
        if (self.mach is None) == (self.tas_mps is None):
            raise ValueError("OperatingPoint requires exactly one of {mach, tas_mps}.")


class ModeRef(BaseModel):
    mode_id: str
    mode_name: Optional[str] = None
    use_mode_flag: bool = True

class VarPresetRef(BaseModel):
    group_name: str
    setting_name: str

class Configuration(BaseModel):
    config_id: str
    mode: Optional[ModeRef] = None
    geom_set_index: Optional[int] = None
    geom_set_name: Optional[str] = None
    var_presets: List[VarPresetRef] = Field(default_factory=list)
    control_surface_groups: List[ControlGroupSetting] = Field(default_factory=list)
    hinges: List[HingeSetting] = Field(default_factory=list)
    payloads_toggle: List[PayloadToggle] = Field(default_factory=list)
    udp_overrides: Dict[str, float] = Field(default_factory=dict)
    runtime_overrides: Dict[str, float] = Field(default_factory=dict)
    notes: str = ""

class ProjectDefinition(BaseModel):
    project_id: str
    description: str = ""
    aircraft_file: str                # "<project_id>.vsp3"
    default_set: str
    versions: Dict[str, str] = Field(default_factory=dict)
    references: Dict[str, List[str]] = Field(default_factory=lambda: {
        "missions": [], "powerplants": [], "ops": [], "configs": []
    })
    uav: UAVDefinition
    control_policy: Literal["mirror_openvsp"] = "mirror_openvsp"
    mixing_profiles: Dict[str, Dict] = Field(default_factory=dict)  # optional future use
    notes: str = ""

# -------------------------
# Design-layer types
# -------------------------
class UDPCatalogEntry(BaseModel):
    udp_name: str
    geom_id: str
    description: str = ""
    value: float
    min: Optional[float] = None
    max: Optional[float] = None
    units: Optional[str] = None
    sensitivity_available: bool = False

class StagedEditBatch(BaseModel):
    config_id: str
    udp_changes: Dict[str, float] = Field(default_factory=dict)
    control_deflections_deg: Dict[str, float] = Field(default_factory=dict)  # group-name keyed
    hinges: Dict[str, float] = Field(default_factory=dict)
    payloads_toggle: Dict[str, bool] = Field(default_factory=dict)
    notes: str = ""

# -------------------------
# Analysis-layer metadata (no matrices here)
# -------------------------
class RefGeometry(BaseModel):
    S_ref_m2: float
    c_ref_m: float
    b_ref_m: float

class AnalysisOpSummaryMeta(BaseModel):
    set_name: str
    config_id: str
    op_name: str
    ref_geom: RefGeometry
    mass_kg: float
    cg_xyz_m: Tuple[float, float, float]
    propulsion: PropulsionType

class LinearModelMeta(BaseModel):
    set_name: str
    config_id: str
    op_name: str
    states: List[str]
    inputs: List[str]     # dynamic: delta_<group>, throttle?
    outputs: List[str]
    ref_geom: RefGeometry
    mass_kg: float
    cg_xyz_m: Tuple[float, float, float]
    frames: Dict[str, str] = Field(default_factory=dict)  # {"states":"body", "outputs":"body"}
    manifest: Optional[RunManifest] = None