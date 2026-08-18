"""`streamline` — the only path to artifacts (Master Plan §8.4).

Subcommands land with their phases; the P1 set is `version` and `gui`. Everything else is added
here, never as a loose script, so that "how was this artifact made" has one answer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _cmd_version(_: argparse.Namespace) -> int:
    from .vsp import session as sm
    try:
        s = sm.require_openvsp(allow_unpinned=True)
        pin = "pinned" if s.pinned else f"UNPINNED (want {sm.PINNED_OPENVSP})"
        print(f"streamline {__version__} · OpenVSP {s.version} ({pin})")
        return 0 if s.pinned else 1
    except sm.OpenVSPMissing as e:
        print(f"streamline {__version__} · OpenVSP: not importable — {e}", file=sys.stderr)
        return 2


def _cmd_gui(ns: argparse.Namespace) -> int:
    """Open a model in the OpenVSP GUI. Design-time convenience only — never on the pipeline path.
    Under WSL, X comes from WSLg; if GL is unhappy try LIBGL_ALWAYS_SOFTWARE=1."""
    from .vsp import session as sm
    s = sm.require_openvsp(graphics=True, allow_unpinned=ns.allow_unpinned)
    api = s.api
    if ns.model:
        p = Path(ns.model)
        if not p.exists():
            print(f"no such model: {p}", file=sys.stderr)
            return 2
        api.ReadVSPFile(str(p))
    api.StartGUI()
    return 0


def _cmd_geometry_apply(ns: argparse.Namespace) -> int:
    from .vsp import apply as apply_mod, session as sm
    session = sm.require_openvsp(allow_unpinned=ns.allow_unpinned)
    res = apply_mod.apply_spec(session, ns.spec)
    print(f"{res['out']}  sha256 {res['sha256']}")
    return 0


def _cmd_engine_fit(ns: argparse.Namespace) -> int:
    from aerodb_contract import canonical_json
    from .engine import deck as deck_mod
    doc = deck_mod.build_from_spec(ns.spec)
    out = Path(ns.out) if ns.out else Path(ns.spec).parent / "engine_deck.json"
    canonical_json.write(out, doc)
    st = doc["static"]
    print(f"{out}  ({doc['engine']}, status={doc['status']})")
    print(f"  thrust {st['thrust_N'][0]:.1f}..{st['thrust_N'][-1]:.1f} N [{st['source']['thrust_N']}], "
          f"fuel {st['fuel_flow_kg_s'][0]*1000:.2f}..{st['fuel_flow_kg_s'][-1]*1000:.2f} g/s [{st['source']['fuel_flow_kg_s']}], "
          f"tau up/down {doc['dynamics']['spool_up_time_constant_s']:.2f}/{doc['dynamics']['spool_down_time_constant_s']:.2f} s, "
          f"slew {doc['dynamics']['slew_up_per_s']:.0f}/{doc['dynamics']['slew_down_per_s']:.0f} rpm/s [{doc['dynamics']['source']}]")
    return 0


def _cmd_massprops_from_fusion(ns: argparse.Namespace) -> int:
    from . import massprops as mp_mod, massprops_fusion as mf
    doc = mf.build_ledger(ns.bodies, ns.overrides)
    out = mf.write_ledger(doc, ns.out)
    mp = mp_mod.from_ledger(out)
    print(f"{out}  ({len(doc['components'])} components)")
    print(f"  dry {mp.mass_kg:.3f} kg  cg_frd {np_fmt(mp.cg_m)} m  "
          f"I diag {np_fmt(mp.inertia_kg_m2.diagonal())} kg m^2")
    if doc.get("fuel"):
        f = doc["fuel"]
        print(f"  fuel {f['volume_l']:.2f} L = {f['mass_full_kg']:.3f} kg @ {f['density_kg_m3']:g} kg/m^3, cg_frd {f['cg_m']}")
    for c in doc["components"]:
        if c["source"].startswith("DECLARED"):
            print(f"  declared: {c['name']} {c['mass_kg']:.3f} kg @ {c['cg_m']}")
    return 0


def np_fmt(v) -> str:
    return "[" + ", ".join(f"{float(x):+.4f}" for x in v) + "]"


def _cmd_campaign_run(ns: argparse.Namespace) -> int:
    from .campaign import definition, runner
    from .vsp import session as sm
    campaign = definition.load(ns.campaign)
    k, n = (int(x) for x in ns.shard.split("/"))
    session = sm.require_openvsp(allow_unpinned=ns.allow_unpinned)
    out = Path(ns.out) / f"shard{k}.jsonl"
    runner.run(session, campaign, out, shard=(k, n))
    print(f"rows -> {out}")
    return 0


def _cmd_campaign_assemble(ns: argparse.Namespace) -> int:
    import subprocess
    from .campaign import assemble as asm, definition, export
    from .vsp import geometry as geom_mod, session as sm
    campaign = definition.load(ns.campaign)
    rows = asm.merge_shards([Path(p) for p in ns.raw])
    session = sm.require_openvsp(allow_unpinned=ns.allow_unpinned)
    geometry = geom_mod.load(session, campaign.path.parent.parent / "geometry" / campaign.geometry_file)
    commit = ns.commit or subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip() or "unknown"
    # Items the audit cannot read off the geometry are claimed by the campaign (recorded as
    # flags either way; only surfaces + reference quantities are release-required).
    claims = campaign.doc.get("completeness_claims", {})
    flags = asm.audit_completeness(geometry, campaign, has_ledger=ns.ledger is not None,
                                   has_engine_geometry=claims.get("engine_geometry", False),
                                   has_gear=claims.get("gear_geometry", False),
                                   has_airfoils=claims.get("airfoils_defined", False))
    doc = asm.assemble(campaign, rows, streamline_commit=commit, completeness_flags=flags)
    massprops_doc = None
    if ns.ledger:
        from . import massprops as mp_mod
        mp = mp_mod.from_ledger(ns.ledger)
        massprops_doc = mp_mod.to_artifact(mp, aircraft_name=campaign.aircraft,
                                           geometry_rev=campaign.geometry_rev,
                                           geometry_sha256=doc["aircraft"]["geometry_sha256"])
    engine_doc = None
    if ns.engine:
        from aerodb_contract import load as contract_load
        engine_doc = contract_load.EngineDeck.from_json(ns.engine).doc   # schema-checked on load
    export.write_release(Path(ns.out), aerodb=doc, massprops=massprops_doc, engine_deck=engine_doc,
                         raw_paths=[Path(p) for p in ns.raw], streamline_commit=commit)
    blocking = [r for r in doc["lint"]["results"] if r["status"] == "fail"]
    print(f"assembled {doc['id']} -> {ns.out}" + (f"  (BLOCKING LINT: {len(blocking)})" if blocking else ""))
    if ns.gate:
        export.release_gate(doc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streamline", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("version", help="print streamline and OpenVSP versions and the pin status")
    v.set_defaults(fn=_cmd_version)

    g = sub.add_parser("gui", help="open a .vsp3 in the OpenVSP GUI (design-time only)")
    g.add_argument("model", nargs="?", help="path to a .vsp3")
    g.add_argument("--allow-unpinned", action="store_true")
    g.set_defaults(fn=_cmd_gui)

    ge = sub.add_parser("geometry", help="geometry revision operations")
    gsub = ge.add_subparsers(dest="sub", required=True)
    ga = gsub.add_parser("apply", help="apply a committed spec JSON to produce a new .vsp3 revision")
    ga.add_argument("spec"); ga.add_argument("--allow-unpinned", action="store_true")
    ga.set_defaults(fn=_cmd_geometry_apply)

    en = sub.add_parser("engine", help="engine bench data → engine_deck.json")
    esub = en.add_subparsers(dest="sub", required=True)
    ef = esub.add_parser("fit", help="run the bench fits declared in an engine spec.json and write the deck")
    ef.add_argument("spec"); ef.add_argument("--out")
    ef.set_defaults(fn=_cmd_engine_fit)

    mp = sub.add_parser("massprops", help="mass ledger operations")
    msub = mp.add_subparsers(dest="sub", required=True)
    mff = msub.add_parser("from-fusion", help="Fusion body export + overrides → ledger.json")
    mff.add_argument("--bodies", required=True, help="pull_bodies.py export (.psv)")
    mff.add_argument("--overrides", required=True, help="declared corrections JSON")
    mff.add_argument("--out", required=True, help="ledger.json to write")
    mff.set_defaults(fn=_cmd_massprops_from_fusion)

    c = sub.add_parser("campaign", help="run / assemble a campaign")
    csub = c.add_subparsers(dest="sub", required=True)
    cr = csub.add_parser("run", help="run one shard of a campaign into raw rows")
    cr.add_argument("campaign"); cr.add_argument("--out", required=True)
    cr.add_argument("--shard", default="0/1"); cr.add_argument("--allow-unpinned", action="store_true")
    cr.set_defaults(fn=_cmd_campaign_run)
    ca = csub.add_parser("assemble", help="assemble raw rows into release artifacts")
    ca.add_argument("campaign"); ca.add_argument("--raw", nargs="+", required=True)
    ca.add_argument("--out", required=True); ca.add_argument("--ledger")
    ca.add_argument("--engine", help="a built engine_deck.json to ship in the same release")
    ca.add_argument("--commit"); ca.add_argument("--gate", action="store_true")
    ca.add_argument("--allow-unpinned", action="store_true")
    ca.set_defaults(fn=_cmd_campaign_assemble)
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    return int(ns.fn(ns))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
