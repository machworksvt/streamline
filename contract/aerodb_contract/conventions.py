"""The conventions, machine-readable. `conventions.md` is the same content for people.

An AeroDB carries a copy of this dict in its `conventions` block and the validator requires it to
be EQUAL to the pinned one. So a producer and a consumer that disagree about a frame or a sign
cannot exchange an artifact by accident — the file itself says which convention it was written
under, and a consumer pinned to a different contract refuses at load rather than at the first
wrong-signed moment.
"""

from __future__ import annotations

CONVENTIONS_VERSION = 1

#: Physical control surfaces of the Icarus airframe, by name. This is the vocabulary a producer
#: must use for control-derivative tables and a consumer must map onto its own actuator indices.
#: The order here is the order of `surfaces` in the artifact; nothing else may depend on it.
SURFACES = (
    "aileron_left",
    "aileron_right",
    "flap_left",
    "flap_right",
    "stabilator",
    "ruddervator_left",
    "ruddervator_right",
)

#: Surfaces that enter the model as linear control derivatives (per rad). Flaps are excluded on
#: purpose: they enter through the base tables' `flap_rad` axis and MUST NOT also appear as a
#: derivative, or their effect would be counted twice.
CONTROL_SURFACES = ("aileron_left", "aileron_right", "stabilator", "ruddervator_left", "ruddervator_right")

#: Left/right pairs, for the mirror-symmetry lint.
MIRROR_PAIRS = (("aileron_left", "aileron_right"), ("ruddervator_left", "ruddervator_right"))

COEFFICIENTS = ("CX", "CY", "CZ", "Cl", "Cm", "Cn")
LONGITUDINAL = ("CX", "CZ", "Cm")
LATERAL = ("CY", "Cl", "Cn")
RATES = ("p_hat", "q_hat", "r_hat")

CONVENTIONS = {
    "version": CONVENTIONS_VERSION,
    "body_frame": "FRD",
    "datum": "openvsp-model-origin",
    "angles": "rad",
    "units": "SI",
    "alpha": "atan2(w, u)",
    "beta": "asin(v / V)",
    "airspeed": "true airspeed, m/s",
    "coefficients": {
        "CX": "X force / (qbar S), body FRD",
        "CY": "Y force / (qbar S), body FRD",
        "CZ": "Z force / (qbar S), body FRD (lift up is negative CZ)",
        "Cl": "rolling moment / (qbar S b), right wing down positive",
        "Cm": "pitching moment / (qbar S cbar), nose up positive",
        "Cn": "yawing moment / (qbar S b), nose right positive",
    },
    "moment_reference": "moment_reference_point_m, a fixed geometric point in FRD from the datum; NOT the CG",
    "rates_nondim": {"p_hat": "p b / (2 V)", "q_hat": "q cbar / (2 V)", "r_hat": "r b / (2 V)"},
    "surface_deflection": "positive = trailing edge down about the hinge line, per physical surface; "
                          "for a V-tail panel, toward the panel's lower surface",
    "surfaces": list(SURFACES),
    "control_surfaces": list(CONTROL_SURFACES),
    "flaps_enter_via": "the flap_rad axis of the base tables only",
    "composition": "C = base(alpha, beta, V, flap) + sum_r C_rhat * rhat + sum_s C_delta_s * delta_s",
    "vspaero_to_frd_rotation": "X_FRD = -X_vsp, Y_FRD = Y_vsp, Z_FRD = -Z_vsp",
    "density": "not in the artifact; the consumer supplies rho — per-breakpoint rho/Mach/Re are metadata",
}
