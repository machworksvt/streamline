# data_structures.py

from dataclasses import dataclass, field, is_dataclass, asdict
from typing import List, Dict, Any
import numpy as np
import pandas as pd
import json

# -- Boilerplate for conversion to and from file -- #

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        # Handle numpy arrays
        if isinstance(obj, np.ndarray):
            return {"__ndarray__": True, "data": obj.tolist()}
        # Handle pandas DataFrames
        elif isinstance(obj, pd.DataFrame):
            return {"__pandas_dataframe__": True, "data": obj.to_dict(orient="split")}
        # If it’s a dataclass, convert it to a dict.
        elif is_dataclass(obj):
            return asdict(obj)
        return super().default(obj)

def _custom_decoder(d):
    if "__ndarray__" in d:
        return np.array(d["data"])
    if "__pandas_dataframe__" in d:
        return pd.DataFrame(**d["data"])
    return d

def to_file(obj, filename):
    """
    Serialize any of your dataclass objects (even if they contain numpy arrays or DataFrames)
    to a JSON file.
    """
    with open(filename, "w") as f:
        json.dump(obj, f, cls=CustomEncoder, indent=4)

def from_file(filename, cls):
    """
    Deserialize the JSON file back into an instance of 'cls'. This requires that
    the top-level object is a dict that can be used as keyword arguments for cls.
    """
    with open(filename, "r") as f:
        data = json.load(f, object_hook=_custom_decoder)
    return cls(**data)

# -- Geometry Data Structures -- #

@dataclass
class Parameter:
    """
        Parameter data structure
    """
    vsp_id : str # VSP ID
    name : str # Name of the parameter

@dataclass
class GeometryComponent:
    """
        GeometryComponent data structure    
    """
    vsp_id : str # VSP ID
    component_type : str # Component Type -> This is subclassed away but is useful for filtering
    parameters : Dict[Parameter, Any] = field(default_factory=dict)

@dataclass
class GeometryConfiguration:
    """
        GeometryConfiguration data structure
    """
    components : List[GeometryComponent] = field(default_factory=list) # List of GeometryComponents


# -- Operating Point Data Structures -- #

@dataclass
class OperatingPoint:
    """
        OperatingPoint data structure
    """
    name : str # Name of the operating point

# -- VSP Data Structures -- #

@dataclass
class VLMAnalysis:
    """
        VLMAnalysis data structure - all required inputs for a VLM analysis call to openvsp.
    """
    """
        List of all Analysis Inputs for a VSPAEROSweep
        NOTE: VLM analysis happens when 'AnalysisType' is set to vsp.VORTEX_LATTICE
        NOTE: Default static stability analysis is performed when 'AnalysisType' is set to vsp.STABILITY_DEFAULT

        ('2DFEMFlag', 
        'ActuatorDiskFlag', 
        'AlphaEnd', 
        'AlphaNpts', 
        'AlphaStart', 
        'AlternateInputFormatFlag', 
        'AnalysisMethod', 
        'AutoTimeNumRevs', 
        'AutoTimeStepFlag', 
        'BetaEnd', 
        'BetaNpts', 
        'BetaStart', 
        'CGDegenSet', 
        'CGGeomSet', 
        'CGModeID', 
        'Clmax', 
        'ClmaxToggle', 
        'FarDist', 
        'FarDistToggle', 
        'FixedWakeFlag', 
        'FromSteadyState', 
        'GeomSet', 
        'GroundEffect', 
        'GroundEffectToggle', 
        'HoverRamp', 
        'HoverRampFlag', 
        'KTCorrection', 
        'MACFlag', 
        'MachEnd', 
        'MachNpts', 
        'MachStart', 
        'Machref', 
        'ManualVrefFlag', 
        'MassSliceDir', 
        'MaxTurnAngle', 
        'MaxTurnToggle', 
        'ModeID', 
        'NCPU', 
        'NoiseCalcFlag', 
        'NoiseCalcType', 
        'NoiseUnits', 
        'NumMassSlice', 
        'NumTimeSteps', 
        'NumWakeNodes', 
        'Precondition', 
        'ReCref', 
        'ReCrefEnd', 
        'ReCrefNpts', 
        'RedirectFile', 
        'RefFlag', 
        'Rho', 
        'RotateBladesFlag', 
        'ScurveFlag', 
        'Sref', 
        'Symmetry', 
        'TimeStepSize', 
        'UnsteadyType', 
        'UseCGModeFlag', 
        'UseModeFlag', 
        'Vinf', 
        'Vref', 
        'WakeNumIter', 
        'WingID', 
        'Xcg', 
        'Ycg', 
        'Zcg', 
        'bref', 
        'cref')
    """
    mach : float
    alpha : float
    beta : float
    rho : float
    v_inf : float
    cg : np.ndarray
    # Assume static stability enabled by default for now
    geometry_config : GeometryConfiguration # it needs this because VSPAERO needs to know the set of geometries to use, execute function should handle this though
    


# -- Inertia Data Structures -- #

@dataclass
class InertiaConfiguration:
    """
        MassConfiguration data structure - all required inputs for a mass configuration call to openvsp.
    """
    name : str
    mass : float # Mass of the configuration
