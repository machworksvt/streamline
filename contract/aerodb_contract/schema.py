"""Schema-as-code for the four artifacts: aerodb, massprops, engine_deck, manifest.

The Python IS the schema. Each artifact is a flat list of `Field`s (dotted path, kind, unit, doc);
`validate()` walks the list against a document and returns every problem it finds, and
`spec.py` renders the same list into `spec.md`, so the document people read cannot drift from the
one machines check. No JSON-Schema library: `icarus-dynamics` pins this package into a
stdlib+numpy shell and must not gain a dependency to read an aero table.

Strictness: unknown TOP-LEVEL keys and unknown table names are errors (a typo must not pass);
unknown keys nested inside `provenance`, `conditions`, `lint`, `completeness` are allowed, which
is where forward-compatible additions go. Anything else is a schema version bump.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from . import conventions as cv

SCHEMA_VERSION = "0.1.0"

ID_RE = re.compile(r"^[a-z0-9]+-[A-Z]\.[0-9a-f]{8}\.[0-9a-f]{8}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """The document violates the contract; the message lists every violation found."""


@dataclass(frozen=True)
class Field:
    path: str
    kind: str                       # see _check_kind
    unit: str = "-"
    doc: str = ""
    required: bool = True
    shape: tuple[str, ...] | None = None    # table / vector shape in axis symbols or ints
    allowed: tuple[str, ...] | None = None  # for kind "enum" / "enum_list"
    equals: Any = None                      # value must equal this exactly (conventions block)
    pattern: re.Pattern | None = None       # for kind "str"


TABLE_SHAPE = ("n_flap", "n_V", "n_beta", "n_alpha")


def _table_fields() -> list[Field]:
    out = []
    for c in cv.COEFFICIENTS:
        out.append(Field(f"tables.base.{c}", "table", "-", f"total {c} on the grid", shape=TABLE_SHAPE))
    for r in cv.RATES:
        for c in cv.COEFFICIENTS:
            out.append(Field(f"tables.rate.{r}.{c}", "table", "1/rad",
                             f"∂{c}/∂{r} (per unit non-dimensional rate)", shape=TABLE_SHAPE))
    for s in cv.CONTROL_SURFACES:
        for c in cv.COEFFICIENTS:
            out.append(Field(f"tables.control.{s}.{c}", "table", "1/rad",
                             f"∂{c}/∂δ_{s} (per rad, trailing-edge down positive)", shape=TABLE_SHAPE))
    return out


AERODB_FIELDS: tuple[Field, ...] = (
    Field("schema.name", "str", doc="'aerodb'", equals="aerodb"),
    Field("schema.version", "str", doc="this schema's version", equals=SCHEMA_VERSION),
    Field("id", "str", doc="<aircraft>-<rev>.<campaign8>.<streamline8> — identity of the INPUTS; the content hash lives in MANIFEST.json", pattern=ID_RE),
    Field("aircraft.name", "str", doc="e.g. 'icarus'"),
    Field("aircraft.geometry_rev", "str", doc="revision letter of the .vsp3 (§8.2)"),
    Field("aircraft.geometry_file", "str", doc="basename of the .vsp3"),
    Field("aircraft.geometry_sha256", "str", doc="sha256 of the .vsp3 bytes", pattern=SHA_RE),
    Field("conventions", "object", doc="copy of conventions.CONVENTIONS; must equal the pinned one", equals=cv.CONVENTIONS),
    Field("reference.S_m2", "number", "m^2", "reference area"),
    Field("reference.b_m", "number", "m", "reference span"),
    Field("reference.cbar_m", "number", "m", "reference chord"),
    Field("reference.moment_reference_point_m", "vec3", "m", "moment reference point, FRD from the datum (NOT the CG)"),
    Field("surfaces", "enum_list", doc="the seven physical surfaces, in contract order", allowed=cv.SURFACES, equals=list(cv.SURFACES)),
    Field("axes.alpha_rad", "axis", "rad", "angle of attack breakpoints, strictly increasing"),
    Field("axes.beta_rad", "axis", "rad", "sideslip breakpoints, strictly increasing"),
    Field("axes.airspeed_m_s", "axis", "m/s", "true-airspeed breakpoints, strictly increasing"),
    Field("axes.flap_rad", "axis", "rad", "flap detent breakpoints (both flaps together), strictly increasing"),
    Field("conditions.altitude_m", "number", "m", "geometric altitude the campaign ran at"),
    Field("conditions.atmosphere", "str", doc="'ISA' or a named override"),
    Field("conditions.density_kg_m3", "vector", "kg/m^3", "density per airspeed breakpoint (metadata; not a model input)", shape=("n_V",)),
    Field("conditions.mach", "vector", "-", "Mach per airspeed breakpoint", shape=("n_V",)),
    Field("conditions.reynolds_cbar", "vector", "-", "Reynolds number on cbar per airspeed breakpoint", shape=("n_V",)),
    *_table_fields(),
    Field("model.composition", "str", doc="the composition formula, verbatim from conventions", equals=cv.CONVENTIONS["composition"]),
    Field("model.base_includes", "list[str]", doc="what is summed into base, e.g. ['vspaero_vlm_inviscid', 'parasite_cd0_rotated_to_body']"),
    Field("model.flaps_enter_via", "str", doc="'axis'", equals="axis"),
    Field("validity.alpha_rad", "range", "rad", "[lo, hi] the producer stands behind"),
    Field("validity.beta_rad", "range", "rad", "[lo, hi]"),
    Field("validity.delta_rad_max", "number", "rad", "largest surface deflection the linear derivatives are meant for"),
    Field("validity.notes", "str", doc="free text: what the method cannot see (stall, hinge moments, ...)"),
    Field("validity.stall.cl_max_estimate", "vector", "-", "CL_max estimate per flap detent (from the campaign; low confidence)", shape=("n_flap",)),
    Field("validity.stall.source", "str", doc="where the estimate came from"),
    Field("validity.stall.points_beyond", "list[object]", doc="grid points whose CL exceeds the estimate: {flap_i, V_i, beta_i, alpha_i, CL}", required=True),
    Field("provenance.backend.name", "str", doc="'vspaero'"),
    Field("provenance.backend.openvsp_version", "str", doc="e.g. '3.51.2'"),
    Field("provenance.backend.method", "str", doc="'VLM'"),
    Field("provenance.backend.unpinned", "bool", doc="true if produced on an OpenVSP other than the pinned one; the release lint refuses"),
    Field("provenance.backend.settings", "object", doc="every solver input, as resolved (the no-implicit-defaults register)"),
    Field("provenance.campaign_sha256", "str", doc="sha256 of the canonical campaign definition", pattern=SHA_RE),
    Field("provenance.streamline_commit", "str", doc="git commit of streamline that produced this ('dirty' suffix allowed for non-release runs)"),
    Field("provenance.contract_version", "str", doc="aerodb_contract version", equals=SCHEMA_VERSION),
    Field("provenance.per_table_source", "object", doc="table path → source id (multi-backend later)"),
    Field("provenance.confidence.default", "str", doc="'unquantified' in v0"),
    Field("knockdowns.control_effectiveness", "object", doc="surface → {factor, uncertainty, source}; 1.0/null/'unquantified' in v0"),
    Field("lint.version", "int", doc="lint list version"),
    Field("lint.results", "list[object]", doc="[{check, status: pass|warn|fail|waived, detail}]"),
    Field("completeness.version", "int", doc="checklist version"),
    Field("completeness.flags", "list[object]", doc="[{item, status: clear|open|waived, note}]"),
)

MASSPROPS_FIELDS: tuple[Field, ...] = (
    Field("schema.name", "str", equals="massprops"),
    Field("schema.version", "str", equals=SCHEMA_VERSION),
    Field("aircraft.name", "str"),
    Field("aircraft.geometry_rev", "str"),
    Field("aircraft.geometry_sha256", "str", pattern=SHA_RE),
    Field("mass_kg", "number", "kg", "total mass"),
    Field("cg_m", "vec3", "m", "CG, FRD from the datum"),
    Field("inertia_kg_m2", "matrix3", "kg m^2", "inertia tensor about the CG, FRD; symmetric, positive definite"),
    Field("components", "list[object]", doc="[{name, mass_kg, cg_m[3], inertia_local_kg_m2[3][3] | shape, source}]"),
    Field("fuel.cg_m", "vec3", "m", "where the fuel mass sits, FRD from the datum; the consumer's fuel state "
          "moves the CG and inertia toward it. Capacity/density are the engine deck's `fuel` block", required=False),
    Field("status.mass", "enum", allowed=("estimated", "measured", "reconciled")),
    Field("status.cg", "enum", allowed=("estimated", "measured", "reconciled")),
    Field("status.inertia", "enum", allowed=("estimated", "measured", "reconciled")),
    Field("confidence.mass", "enum", allowed=("low", "medium", "high")),
    Field("confidence.cg", "enum", allowed=("low", "medium", "high")),
    Field("confidence.inertia", "enum", allowed=("low", "medium", "high")),
    Field("provenance.method", "str", doc="'ledger_point_masses' in v0"),
    Field("provenance.ledger_sha256", "str", pattern=SHA_RE),
    Field("provenance.contract_version", "str", equals=SCHEMA_VERSION),
)

#: Per-field provenance vocabulary for the engine deck: what a number IS, not how good it looks.
#:   measured   — read off the bench logs (a steady window, an ECU counter)
#:   fitted     — a model constant regressed from bench transients (spool τ, ṁ(N) polynomial)
#:   datasheet  — the manufacturer's spec sheet
#:   estimated  — a declared prior with no supporting measurement (e.g. thrust ∝ N^k with no load cell)
SOURCE_KINDS = ("measured", "fitted", "datasheet", "estimated")

ENGINE_DECK_FIELDS: tuple[Field, ...] = (
    Field("schema.name", "str", equals="engine_deck"),
    Field("schema.version", "str", equals=SCHEMA_VERSION),
    Field("engine", "str", doc="e.g. 'Hybl H20PRO'"),
    # --- static maps: the DATA. Setting axis is what the ECU actually regulates. -----------------
    Field("static.setting_kind", "enum", allowed=("throttle_frac", "rpm"), doc="what the setting axis is"),
    Field("static.setting", "axis", "-", "throttle fraction [0..1] or RPM, strictly increasing"),
    Field("static.thrust_N", "vector", "N", "static thrust per setting", shape=("n_setting",)),
    Field("static.fuel_flow_kg_s", "vector", "kg/s", "fuel flow per setting", shape=("n_setting",), required=False),
    Field("static.egt_K", "vector", "K", "exhaust gas temperature per setting", shape=("n_setting",), required=False),
    Field("static.source", "object", doc="per-column provenance: {thrust_N, fuel_flow_kg_s, egt_K} → SOURCE_KINDS + note",
          required=False),
    # --- limits: the ECU/manufacturer envelope the consumer must respect --------------------------
    Field("limits.setting_idle", "number", "-", "minimum idle setting (same axis as static.setting)"),
    Field("limits.setting_max_continuous", "number", "-", "maximum continuous setting"),
    Field("limits.setting_max_transient", "number", "-", "absolute (time-limited) maximum setting", required=False),
    Field("limits.source", "enum", allowed=SOURCE_KINDS, required=False),
    # --- fuel: capacity is an AIRCRAFT number, density is a FUEL number; both live with the deck
    #     because the consumer's fuel-mass state needs them together ---------------------------------
    Field("fuel.capacity_kg", "number", "kg", "usable fuel at takeoff (aircraft tankage × density)", required=False),
    Field("fuel.density_kg_m3", "number", "kg/m^3", "fuel density used to convert bench volumetric flow", required=False),
    Field("fuel.type", "str", required=False, doc="e.g. 'Jet A-1 + 5% turbine oil'"),
    # --- thrust model: how static.thrust_N was PRODUCED when no load cell existed -----------------
    Field("thrust_model.kind", "enum", allowed=("measured", "power_law"), required=False,
          doc="'measured' → static.thrust_N is bench data; 'power_law' → T = T_anchor·(N/N_anchor)^k, a declared prior"),
    Field("thrust_model.exponent", "number", "-", "k in the power law (small turbojets: 2–3 in the upper band)", required=False),
    Field("thrust_model.anchor_thrust_N", "number", "N", required=False),
    Field("thrust_model.anchor_setting", "number", "-", "setting at which anchor_thrust_N applies", required=False),
    Field("thrust_model.source", "enum", allowed=SOURCE_KINDS, required=False),
    # --- dynamics PARAMETERS (not a model): the consumer builds the ODE, these are its constants.
    #     Recommended consumer structure, matching the measured H20PRO ECU behaviour:
    #        setting_cmd  = throttle → setting map;  setting_lim' = clamp((setting_cmd − setting_lim)/dt,
    #        −slew_down, +slew_up);  setting' = (setting_lim − setting)/τ(direction).
    #     Big transients are RATE-limited (ECU acceleration schedule), small ones τ-limited. -----------
    Field("dynamics.spool_up_time_constant_s", "number", "s", "first-order tracking τ for setting increases", required=False),
    Field("dynamics.spool_down_time_constant_s", "number", "s", "first-order tracking τ for setting decreases", required=False),
    Field("dynamics.slew_up_per_s", "number", "setting/s", "maximum sustained setting increase rate", required=False),
    Field("dynamics.slew_down_per_s", "number", "setting/s", "maximum sustained setting decrease rate", required=False),
    Field("dynamics.spool_fit", "object", required=False,
          doc="how the constants were obtained: {method, n_steps_up, n_steps_down, n_runs_slew_up, n_runs_slew_down, steps: [...]}"),
    Field("dynamics.source", "enum", allowed=SOURCE_KINDS, required=False),
    # --- installation --------------------------------------------------------------------------------
    Field("ambient.pressure_Pa", "number", "Pa", required=False),
    Field("ambient.temperature_K", "number", "K", required=False),
    Field("thrust_line.point_m", "vec3", "m", "a point on the thrust line, FRD from the datum"),
    Field("thrust_line.direction_b", "vec3", "-", "unit direction of thrust in FRD"),
    Field("status", "enum", allowed=("estimated", "measured", "reconciled"),
          doc="overall: 'measured' only when thrust itself is measured; power-law thrust ⇒ 'estimated'"),
    Field("provenance.bench_file_sha256", "str", pattern=SHA_RE,
          doc="sha256 of the primary bench source (or of a manifest of several)"),
    Field("provenance.bench_files", "list[object]", required=False,
          doc="every bench source used: [{path, sha256, role}]"),
    Field("provenance.test_date", "str", doc="ISO date of the bench test — provenance of the DATA, not a build timestamp"),
    Field("provenance.notes", "str"),
    Field("provenance.contract_version", "str", equals=SCHEMA_VERSION),
)

MANIFEST_FIELDS: tuple[Field, ...] = (
    Field("id", "str", pattern=ID_RE),
    Field("contract_version", "str", equals=SCHEMA_VERSION),
    Field("files", "object", doc="filename → sha256 of every hashed file in the release"),
    Field("geometry_sha256", "str", pattern=SHA_RE),
    Field("campaign_sha256", "str", pattern=SHA_RE),
    Field("streamline_commit", "str"),
    Field("openvsp_version", "str"),
    Field("unpinned", "bool"),
)

SCHEMAS = {
    "aerodb": AERODB_FIELDS,
    "massprops": MASSPROPS_FIELDS,
    "engine_deck": ENGINE_DECK_FIELDS,
    "manifest": MANIFEST_FIELDS,
}

# --- walking ---------------------------------------------------------------------------------

_MISSING = object()   # "the field is absent" — distinct from a present null
_RAISE = object()


def get(doc: Any, path: str, default: Any = _RAISE) -> Any:
    """Dotted-path lookup. Raises KeyError when the path is absent unless a default is given."""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            if default is _RAISE:
                raise KeyError(path)
            return default
        cur = cur[part]
    return cur


def _resolve_shape(shape: tuple[str, ...], doc: Any) -> tuple[int, ...] | None:
    syms = {}
    axes = get(doc, "axes", None)
    if isinstance(axes, dict):
        for sym, key in (("n_alpha", "alpha_rad"), ("n_beta", "beta_rad"),
                         ("n_V", "airspeed_m_s"), ("n_flap", "flap_rad")):
            v = axes.get(key)
            if isinstance(v, list):
                syms[sym] = len(v)
    setting = get(doc, "static.setting", None)
    if isinstance(setting, list):
        syms["n_setting"] = len(setting)
    out = []
    for s in shape:
        if isinstance(s, int):
            out.append(s)
        elif s in syms:
            out.append(syms[s])
        else:
            return None
    return tuple(out)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_kind(f: Field, v: Any, doc: Any, errors: list[str]) -> None:
    p = f.path
    k = f.kind
    if k == "str":
        if not isinstance(v, str):
            errors.append(f"{p}: expected string, got {type(v).__name__}"); return
        if f.pattern and not f.pattern.match(v):
            errors.append(f"{p}: {v!r} does not match {f.pattern.pattern}")
    elif k == "number":
        if not _is_number(v):
            errors.append(f"{p}: expected finite number, got {v!r}")
    elif k == "int":
        if not (isinstance(v, int) and not isinstance(v, bool)):
            errors.append(f"{p}: expected integer, got {v!r}")
    elif k == "bool":
        if not isinstance(v, bool):
            errors.append(f"{p}: expected bool, got {v!r}")
    elif k == "object":
        if not isinstance(v, dict):
            errors.append(f"{p}: expected object, got {type(v).__name__}")
    elif k == "list[str]":
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            errors.append(f"{p}: expected list of strings")
    elif k == "list[object]":
        if not (isinstance(v, list) and all(isinstance(x, dict) for x in v)):
            errors.append(f"{p}: expected list of objects")
    elif k == "enum":
        if v not in (f.allowed or ()):
            errors.append(f"{p}: {v!r} not in {list(f.allowed or ())}")
    elif k == "enum_list":
        if not (isinstance(v, list) and all(x in (f.allowed or ()) for x in v)):
            errors.append(f"{p}: entries must be in {list(f.allowed or ())}")
    elif k in ("vec3", "range", "vector", "axis", "matrix3", "table"):
        try:
            arr = np.asarray(v, dtype=float)
        except (TypeError, ValueError):
            errors.append(f"{p}: not a numeric array"); return
        if arr.size and not np.all(np.isfinite(arr)):
            errors.append(f"{p}: contains NaN/Inf"); return
        if k == "vec3" and arr.shape != (3,):
            errors.append(f"{p}: expected shape (3,), got {arr.shape}")
        elif k == "range":
            if arr.shape != (2,) or not arr[0] < arr[1]:
                errors.append(f"{p}: expected [lo, hi] with lo < hi, got {v!r}")
        elif k == "matrix3":
            if arr.shape != (3, 3):
                errors.append(f"{p}: expected 3x3, got {arr.shape}")
            elif not np.allclose(arr, arr.T, atol=1e-9 * max(1.0, float(np.abs(arr).max()))):
                errors.append(f"{p}: not symmetric")
            elif np.any(np.linalg.eigvalsh(arr) <= 0):
                errors.append(f"{p}: not positive definite")
        elif k == "axis":
            if arr.ndim != 1 or arr.size < 1:
                errors.append(f"{p}: expected a 1-D axis, got shape {arr.shape}")
            elif arr.size > 1 and not np.all(np.diff(arr) > 0):
                errors.append(f"{p}: not strictly increasing")
        elif k in ("vector", "table"):
            want = _resolve_shape(f.shape or (), doc)
            if want is None:
                errors.append(f"{p}: cannot resolve expected shape {f.shape} (axes missing?)")
            elif arr.shape != want:
                errors.append(f"{p}: expected shape {want}, got {arr.shape}")
    else:  # pragma: no cover
        errors.append(f"{p}: unknown kind {k!r} in the schema itself")


def validate(doc: Any, which: str) -> list[str]:
    """Every violation found, as strings; empty means valid."""
    fields = SCHEMAS[which]
    errors: list[str] = []
    if not isinstance(doc, dict):
        return [f"{which}: document is not an object"]

    known_top = {f.path.split(".")[0] for f in fields}
    for k in doc:
        if k not in known_top:
            errors.append(f"unknown top-level key {k!r}")

    for f in fields:
        v = get(doc, f.path, _MISSING)
        if v is _MISSING:
            if f.required:
                errors.append(f"{f.path}: missing")
            continue
        _check_kind(f, v, doc, errors)
        if f.equals is not None and v != f.equals:
            errors.append(f"{f.path}: must equal the pinned value")

    if which == "aerodb":
        errors += _extra_aerodb_checks(doc)
    return errors


def _extra_aerodb_checks(doc: dict) -> list[str]:
    errors = []
    tables = doc.get("tables")
    if isinstance(tables, dict):
        for grp in tables:
            if grp not in ("base", "rate", "control"):
                errors.append(f"tables.{grp}: unknown table group")
        for grp, allowed in (("rate", cv.RATES), ("control", cv.CONTROL_SURFACES)):
            sub = tables.get(grp)
            if isinstance(sub, dict):
                for name in sub:
                    if name not in allowed:
                        errors.append(f"tables.{grp}.{name}: not in {list(allowed)}"
                                      + (" (flaps enter via the axis)" if name.startswith("flap") else ""))
        base = tables.get("base")
        if isinstance(base, dict):
            for name in base:
                if name not in cv.COEFFICIENTS:
                    errors.append(f"tables.base.{name}: not a coefficient")
    for status_field, allowed in (("lint.results", ("pass", "warn", "fail", "waived")),
                                  ("completeness.flags", ("clear", "open", "waived"))):
        rows = get(doc, status_field, None)
        if isinstance(rows, list):
            for i, r in enumerate(rows):
                if isinstance(r, dict) and r.get("status") not in allowed:
                    errors.append(f"{status_field}[{i}].status: {r.get('status')!r} not in {list(allowed)}")
    return errors


def check(doc: Any, which: str) -> None:
    errs = validate(doc, which)
    if errs:
        raise ContractError(f"{which} violates contract {SCHEMA_VERSION}:\n  " + "\n  ".join(errs))


def fields_for(which: str) -> Iterable[Field]:
    return SCHEMAS[which]
