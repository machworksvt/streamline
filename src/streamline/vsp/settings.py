"""The no-implicit-defaults register (plan §3.1).

OpenVSP's analyses carry dozens of silent defaults, several of them imperial-flavoured
(`Rho 0.002377`, `Vinf 100`, `Sref 100`) — a run that forgets one produces a plausible number that
is wrong. So a wrapper never calls `SetAnalysisInputDefaults` and moves on: it asks the API which
inputs the analysis has (`GetAnalysisInputNames`), refuses unless a value is supplied for EVERY one
of them, sets each with the API's own type, and hands back the resolved set — which the campaign
runner writes into the raw rows and the exporter into `provenance.backend.settings`.

An OpenVSP bump that adds an input therefore fails loudly ("missing: NewFlag") instead of quietly
defaulting; one that removes an input fails too ("unknown: OldFlag") so the campaign definition is
revisited rather than silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .session import Session


class SettingsError(ValueError):
    """The supplied settings do not cover the analysis's inputs exactly."""


@dataclass(frozen=True)
class InputSpec:
    name: str
    kind: str          # int | double | string | vec3d
    default: tuple     # OpenVSP's own default, as the API reports it


@dataclass(frozen=True)
class Resolved:
    analysis: str
    values: dict[str, list]
    overrides: tuple[str, ...] = ()   # which inputs the campaign set away from the solver default

    def as_json(self) -> dict:
        return {k: list(v) for k, v in sorted(self.values.items())}

    def override_table(self, specs: dict) -> list[dict]:
        """One row per input: name, the solver default, our value, whether we changed it. This is
        `docs/solver-settings.md` — the review surface for OpenVSP's silent defaults (plan §3.1)."""
        rows = []
        for name in sorted(self.values):
            default = list(specs[name].default) if name in specs else None
            ours = self.values[name]
            rows.append({"name": name, "default": default, "value": ours,
                         "overridden": name in self.overrides})
        return rows


_KIND = {}


def _kinds(api) -> dict:
    if not _KIND:
        _KIND.update({api.INT_DATA: "int", api.DOUBLE_DATA: "double",
                      api.STRING_DATA: "string", api.VEC3D_DATA: "vec3d"})
    return _KIND


def describe(session: Session, analysis: str) -> dict[str, InputSpec]:
    """Every input the analysis exposes, with OpenVSP's default — after resetting the analysis to
    defaults, so what is reported is what a naive caller would silently get."""
    api = session.api
    api.SetAnalysisInputDefaults(analysis)
    out = {}
    for name in api.GetAnalysisInputNames(analysis):
        t = api.GetAnalysisInputType(analysis, name)
        kind = _kinds(api)[t]
        if kind == "int":
            d = tuple(api.GetIntAnalysisInput(analysis, name))
        elif kind == "double":
            d = tuple(api.GetDoubleAnalysisInput(analysis, name))
        elif kind == "string":
            d = tuple(api.GetStringAnalysisInput(analysis, name))
        else:
            d = tuple((p.x(), p.y(), p.z()) for p in api.GetVec3dAnalysisInput(analysis, name))
        out[name] = InputSpec(name, kind, d)
    return out


def _as_list(v: Any) -> list:
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def complete(session: Session, analysis: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """A COMPLETE input dict for `analysis`: every input at OpenVSP's default, with `overrides`
    applied on top. This is how the no-implicit-defaults rule is kept practical (plan §3.1): the
    campaign names the handful of inputs that matter, and the wrapper turns that into the full set
    so that `resolve` can refuse a missing OR unknown input AND every input is recorded in
    provenance — none is silently defaulted-and-forgotten.

    An override that names an input this OpenVSP does not have raises here, not later: a campaign
    written against a different version must be revisited, not quietly ignored.
    """
    specs = describe(session, analysis)
    unknown = sorted(k for k in overrides if k not in specs)
    if unknown:
        raise SettingsError(f"{analysis}: overrides name inputs this OpenVSP does not have: {unknown}")
    out: dict[str, Any] = {name: list(spec.default) for name, spec in specs.items()}
    out.update(overrides)
    return out


def resolve(session: Session, analysis: str, supplied: Mapping[str, Any],
            *, overrides: Mapping[str, Any] | None = None) -> Resolved:
    """Set EVERY input of `analysis` from `supplied` (scalar or list per key), or refuse.

    Types are coerced to what the API declares (an int input given 1.0 is set as 1; a double given
    2 is set as 2.0; a string input given a non-string is an error) — the API is picky and would
    otherwise raise something far less legible mid-solve. `overrides`, if given, records which keys
    the campaign chose away from the solver default (for the review table); it does not change what
    is set.
    """
    api = session.api
    specs = describe(session, analysis)
    missing = sorted(n for n in specs if n not in supplied)
    unknown = sorted(n for n in supplied if n not in specs)
    if missing or unknown:
        raise SettingsError(
            f"{analysis}: settings must name every input exactly."
            + (f"\n  missing ({len(missing)}): {missing}" if missing else "")
            + (f"\n  unknown ({len(unknown)}): {unknown}" if unknown else ""))

    values: dict[str, list] = {}
    for name, spec in specs.items():
        vals = _as_list(supplied[name])
        if spec.kind == "int":
            ivals = []
            for v in vals:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) != int(v):
                    raise SettingsError(f"{analysis}.{name}: expected integer(s), got {vals!r}")
                ivals.append(int(v))
            api.SetIntAnalysisInput(analysis, name, ivals)
            values[name] = ivals
        elif spec.kind == "double":
            try:
                dvals = [float(v) for v in vals]
            except (TypeError, ValueError):
                raise SettingsError(f"{analysis}.{name}: expected number(s), got {vals!r}")
            api.SetDoubleAnalysisInput(analysis, name, dvals)
            values[name] = dvals
        elif spec.kind == "string":
            if not all(isinstance(v, str) for v in vals):
                raise SettingsError(f"{analysis}.{name}: expected string(s), got {vals!r}")
            api.SetStringAnalysisInput(analysis, name, list(vals))
            values[name] = list(vals)
        else:  # vec3d
            pts = []
            for v in vals:
                if len(v) != 3:
                    raise SettingsError(f"{analysis}.{name}: expected [x,y,z] triples, got {vals!r}")
                pts.append(api.vec3d(float(v[0]), float(v[1]), float(v[2])))
            api.SetVec3dAnalysisInput(analysis, name, pts)
            values[name] = [[float(x) for x in v] for v in vals]
    return Resolved(analysis, values, overrides=tuple(sorted(overrides or ())))
