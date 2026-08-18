"""Render `spec.md` from the schema, the lint list, the sign fixtures and the checklist.

`python -m aerodb_contract.spec > contract/aerodb_contract/spec.md` (`make spec`); a test asserts
the committed file is current, so the human-readable spec cannot drift from the code.
"""

from __future__ import annotations

from . import completeness as comp, conventions as cv, lint, schema, signs


def _table(fields) -> str:
    lines = ["| path | kind | unit | required | meaning |", "|---|---|---|---|---|"]
    for f in fields:
        shape = f" shape `{'×'.join(map(str, f.shape))}`" if f.shape else ""
        eq = " (pinned value)" if f.equals is not None else ""
        lines.append(f"| `{f.path}` | {f.kind}{shape} | {f.unit} | {'yes' if f.required else 'no'} | {f.doc}{eq} |")
    return "\n".join(lines)


def render() -> str:
    out = []
    out.append(f"# AeroDB contract — schema {schema.SCHEMA_VERSION}\n")
    out.append("Generated from `schema.py`, `lint.py`, `signs.py`, `completeness.py` by `make spec`. "
               "Do not edit by hand. Conventions are in `conventions.md` (locked with this schema).\n")
    out.append("## Artifacts\n")
    out.append("One release = `aerodb.json` + `massprops.json` + `engine_deck.json` + `MANIFEST.json` "
               "(all hashed, canonical JSON: sorted keys, compact, shortest-repr floats, one trailing "
               "newline, no NaN) + `BUILD.json` (unhashed: timestamps, host, wall time) + `report.pdf`/"
               "`report.json`.\n")
    for which, title in (("aerodb", "aerodb.json"), ("massprops", "massprops.json"),
                         ("engine_deck", "engine_deck.json"), ("manifest", "MANIFEST.json")):
        out.append(f"### `{title}`\n")
        out.append(_table(schema.fields_for(which)) + "\n")
    out.append("Table shape symbols: `n_flap × n_V × n_beta × n_alpha` = lengths of "
               "`axes.flap_rad`, `axes.airspeed_m_s`, `axes.beta_rad`, `axes.alpha_rad`; row-major.\n")
    out.append("## Vocabulary\n")
    out.append(f"Surfaces (order is contract): `{'`, `'.join(cv.SURFACES)}`.  \n"
               f"Control derivatives exist for: `{'`, `'.join(cv.CONTROL_SURFACES)}` (flaps enter via the axis).  \n"
               f"Coefficients: `{'`, `'.join(cv.COEFFICIENTS)}`; rates: `{'`, `'.join(cv.RATES)}`.\n")
    out.append(f"## Physics lint (version {lint.LINT_VERSION})\n")
    out.append("| check | severity | what |\n|---|---|---|")
    for ck in lint.CHECKS:
        out.append(f"| `{ck.name}` | {ck.severity} | {ck.doc} |")
    out.append("")
    out.append(f"## Sign fixtures (version {signs.SIGNS_VERSION})\n")
    out.append("Evaluated at flap 0, the middle airspeed, β≈0, α≈0. Asserted at export and at ingest.\n")
    out.append("| fixture | expects | waivable |\n|---|---|---|")
    for fx in signs.FIXTURES:
        out.append(f"| `{fx.name}` | {fx.doc} | {'yes' if fx.waivable else 'no'} |")
    out.append("")
    out.append(f"## Completeness checklist (version {comp.CHECKLIST_VERSION})\n")
    out.append("| item | required for release | what |\n|---|---|---|")
    for it in comp.CHECKLIST:
        out.append(f"| `{it.id}` | {'yes' if it.required_for_release else 'no'} | {it.doc} |")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":  # pragma: no cover
    print(render(), end="")
