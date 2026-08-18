"""ISA (ICAO 1993 / US Standard 1976 troposphere) — pure functions, SI, no dependency.

One atmosphere for the whole repo: the campaign states an altitude and gets ρ, T, p, a, μ from
here; those go into the raw rows and the artifact's `conditions` as metadata. VSPAERO is then fed
explicit numbers (density / Reynolds per length), never its own imperial-defaulted atmosphere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

G0 = 9.80665
R_AIR = 287.05287
GAMMA = 1.4
T0 = 288.15
P0 = 101325.0
L = -0.0065           # K/m, troposphere lapse rate
MU_REF, T_REF, S_SUTH = 1.716e-5, 273.15, 110.4


@dataclass(frozen=True)
class State:
    altitude_m: float
    temperature_K: float
    pressure_Pa: float
    density_kg_m3: float
    speed_of_sound_m_s: float
    dynamic_viscosity_Pa_s: float

    @property
    def kinematic_viscosity_m2_s(self) -> float:
        return self.dynamic_viscosity_Pa_s / self.density_kg_m3

    def mach(self, airspeed_m_s: float) -> float:
        return airspeed_m_s / self.speed_of_sound_m_s

    def reynolds(self, airspeed_m_s: float, length_m: float) -> float:
        return self.density_kg_m3 * airspeed_m_s * length_m / self.dynamic_viscosity_Pa_s

    def reynolds_per_length(self, airspeed_m_s: float) -> float:
        return self.density_kg_m3 * airspeed_m_s / self.dynamic_viscosity_Pa_s

    def dynamic_pressure(self, airspeed_m_s: float) -> float:
        return 0.5 * self.density_kg_m3 * airspeed_m_s ** 2


def isa(altitude_m: float, delta_T_K: float = 0.0) -> State:
    """Troposphere only (valid to 11 km); `delta_T_K` shifts temperature at constant pressure."""
    if not -1000.0 <= altitude_m <= 11000.0:
        raise ValueError(f"altitude {altitude_m} m outside the troposphere model")
    T_std = T0 + L * altitude_m
    p = P0 * (T_std / T0) ** (-G0 / (L * R_AIR))
    T = T_std + delta_T_K
    rho = p / (R_AIR * T)
    a = math.sqrt(GAMMA * R_AIR * T)
    mu = MU_REF * (T / T_REF) ** 1.5 * (T_REF + S_SUTH) / (T + S_SUTH)
    return State(altitude_m=float(altitude_m), temperature_K=T, pressure_Pa=p, density_kg_m3=rho,
                 speed_of_sound_m_s=a, dynamic_viscosity_Pa_s=mu)
