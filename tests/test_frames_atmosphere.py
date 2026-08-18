"""Pure units: the VSP→FRD rotation and the ISA atmosphere. No solver."""

import math

import numpy as np
import pytest

from streamline import atmosphere as atm
from streamline.vsp import frames


def test_the_rotation_is_a_proper_rotation_not_a_reflection():
    R = frames.R_VSP_TO_FRD
    assert np.allclose(R @ R, np.eye(3)), "R must be its own inverse"
    assert np.linalg.det(R) == pytest.approx(1.0), "det +1 — a rotation, not a reflection"


def test_vsp_axes_map_to_frd():
    # VSP: X aft, Y right, Z up.  FRD: X fwd, Y right, Z down.
    assert np.allclose(frames.vsp_to_frd([1, 0, 0]), [-1, 0, 0])   # aft → -forward
    assert np.allclose(frames.vsp_to_frd([0, 1, 0]), [0, 1, 0])    # right → right
    assert np.allclose(frames.vsp_to_frd([0, 0, 1]), [0, 0, -1])   # up → -down


def test_forces_and_pitch_moment_map_as_expected():
    # VSP force +Z is up; FRD Z is down, so up → −Z_frd. VSP pitch (about Y) is preserved.
    coefs = frames.coefficients_to_frd({"CFx": 0, "CFy": 0, "CFz": 1.0,
                                        "CMx": 0, "CMy": 0.3, "CMz": 0})
    assert coefs["CZ"] == pytest.approx(-1.0)
    assert coefs["Cm"] == pytest.approx(0.3)
    # A drag force (VSP +X is aft) maps to FRD −X.
    coefs = frames.coefficients_to_frd({"CFx": 0.1, "CFy": 0, "CFz": 0, "CMx": 0, "CMy": 0, "CMz": 0})
    assert coefs["CX"] == pytest.approx(-0.1)


def test_isa_sea_level_is_standard():
    s = atm.isa(0.0)
    assert s.temperature_K == pytest.approx(288.15)
    assert s.pressure_Pa == pytest.approx(101325.0, rel=1e-6)
    assert s.density_kg_m3 == pytest.approx(1.225, rel=1e-3)
    assert s.speed_of_sound_m_s == pytest.approx(340.3, rel=1e-3)


def test_isa_at_kentland_1750ft_matches_the_wiki_numbers():
    # 1750 ft = 533.4 m; the aircraft wiki quotes rho 1.146, p 93.353 kPa, a 337.7 at cruise alt.
    s = atm.isa(533.4)
    assert s.density_kg_m3 == pytest.approx(1.16, abs=0.02)
    assert s.pressure_Pa == pytest.approx(95000, abs=1500)
    assert s.speed_of_sound_m_s == pytest.approx(338.5, abs=1.0)


def test_reynolds_and_mach_are_the_textbook_ratios():
    s = atm.isa(533.4)
    assert s.mach(30.0) == pytest.approx(30.0 / s.speed_of_sound_m_s)
    assert s.reynolds(30.0, 0.27) == pytest.approx(s.density_kg_m3 * 30.0 * 0.27 / s.dynamic_viscosity_Pa_s)
    assert s.reynolds_per_length(30.0) * 0.27 == pytest.approx(s.reynolds(30.0, 0.27))


def test_isa_refuses_the_stratosphere():
    with pytest.raises(ValueError):
        atm.isa(20000.0)
