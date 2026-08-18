"""The campaign runner: geometry → solver wrappers → `raw.jsonl` rows. Resumable and shardable.

One JSON object per line, keyed by the point's fixed enumeration key; a re-run skips keys already
present, so a crashed shard continues instead of restarting. Rows carry everything the assembler
needs and nothing it has to go back to OpenVSP for — assembly is a pure function of (campaign,
rows), which is what the determinism double-run diffs.
"""

from __future__ import annotations

import json
from pathlib import Path

from aerodb_contract import canonical_json

from .. import atmosphere as atm
from ..vsp import geometry as geom_mod, parasite as par_mod, stab as stab_mod
from ..vsp.session import Session
from .definition import Campaign, CampaignError


def _load_and_check_geometry(session: Session, campaign: Campaign) -> geom_mod.Geometry:
    gpath = campaign.path.parent.parent / "geometry" / campaign.geometry_file
    geometry = geom_mod.load(session, gpath)
    if geometry.sha256 != campaign.expected_geometry_sha256:
        raise CampaignError(
            f"geometry {gpath.name} is sha256 {geometry.sha256[:12]}… but the campaign pins "
            f"{campaign.expected_geometry_sha256[:12]}… — the .vsp3 changed without a campaign "
            "edit; bump the revision or fix the pin")
    for contract_name, group_name in campaign.surface_groups.items():
        geometry.group(group_name)   # raises with the available names if absent
    return geometry


def _existing_keys(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    keys = set()
    with out_path.open() as fh:
        for line in fh:
            if line.strip():
                keys.add(json.loads(line)["key"])
    return keys


def _append(out_path: Path, row: dict) -> None:
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(canonical_json.to_jsonable(row), sort_keys=True,
                            separators=(",", ":")) + "\n")


def _apply_flap(session: Session, geometry: geom_mod.Geometry, campaign: Campaign, flap_rad: float) -> None:
    """Set EVERY control group's deflection: the flap group to its detent, all others to zero.

    Zeroing the others is not hygiene but correctness — a .vsp3 stores group deflections, and a
    real model arrives with whatever the author last trimmed (icarus rev A ships its elevator at
    −6°). VSPAERO's stab derivatives are taken about the stored baseline, so a non-zeroed group
    would silently bias every base coefficient in the campaign."""
    for cg in geometry.control_groups:
        if campaign.flap_group is not None and cg.name == campaign.flap_group:
            continue
        geom_mod.set_group_deflection(session, cg, 0.0)
    if campaign.flap_group is None:
        if abs(flap_rad) > 1e-12:
            raise CampaignError("campaign has flap detents but no flap_group to apply them with")
        return
    geom_mod.set_group_deflection(session, geometry.group(campaign.flap_group), flap_rad)


def run(session: Session, campaign: Campaign, out_path: Path, *, shard: tuple[int, int] = (0, 1),
        log=print) -> Path:
    """Run this shard's stab points (plus, on shard 0, the rate and parasite rows) into out_path."""
    # Absolute before anything else: the sweep runs inside session.workdir() (a chdir), where a
    # relative out_path would silently point into the scratch dir — found the day a real CLI
    # invocation passed `--out build/golden` (the tests' tmp fixtures are always absolute).
    out_path = Path(out_path).resolve()
    geometry = _load_and_check_geometry(session, campaign)
    isa = atm.isa(campaign.altitude_m)
    wing_id = geometry.by_name(campaign.reference_wing).id
    solver = campaign.solver
    done = _existing_keys(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    k, n = shard
    points = campaign.shard(k, n)
    todo = [p for p in points if p.key not in done]
    log(f"shard {k}/{n}: {len(todo)} of {len(points)} stab points to run "
        f"({len(points) - len(todo)} already present)")

    current_flap = None
    with session.workdir():
        # VSPAERO writes its case/geometry files next to the model FILE, not the CWD — re-anchor
        # the loaded model into this scratch directory so the committed .vsp3's directory stays
        # clean and the sweep finds what ComputeGeometry wrote.
        session.api.WriteVSPFile("model.vsp3", session.api.SET_ALL)
        for spec in todo:
            if spec.flap_rad != current_flap:
                _apply_flap(session, geometry, campaign, spec.flap_rad)
                stab_mod.run_compute_geometry(
                    session, geometry,
                    overrides=stab_mod.compute_geometry_overrides(geometry, vlm_set=campaign.vlm_set))
                current_flap = spec.flap_rad
            ov = stab_mod.steady_overrides(
                session, geometry, alpha_rad=spec.alpha_rad, beta_rad=spec.beta_rad,
                airspeed_m_s=spec.airspeed_m_s, density_kg_m3=isa.density_kg_m3,
                reynolds_cref=isa.reynolds(spec.airspeed_m_s, campaign.cref_m),
                mach=isa.mach(spec.airspeed_m_s), wing_id=wing_id,
                moment_ref_m=campaign.moment_ref_m, vlm_set=campaign.vlm_set,
                ncpu=solver["ncpu"], wake_iters=solver["wake_iters"],
                num_wake_nodes=solver["num_wake_nodes"], extra=solver.get("sweep_extra"))
            point = stab_mod.run_stability(session, geometry, overrides=ov)
            got_cref = point.flight_condition["FC_Cref_"]
            if abs(got_cref - campaign.cref_m) > 1e-3 * campaign.cref_m:
                raise CampaignError(f"campaign says cref_m={campaign.cref_m} but the wing's "
                                    f"reference chord is {got_cref} — fix the campaign")
            _append(out_path, {"key": spec.key, "kind": "stab",
                               "indices": [spec.flap_i, spec.v_i, spec.beta_i, spec.alpha_i],
                               "base": point.base, "d_alpha": point.d_alpha, "d_beta": point.d_beta,
                               "d_control": point.d_control, "static_margin": point.static_margin,
                               "neutral_point_x_m": point.neutral_point_x_m,
                               "flight_condition": point.flight_condition,
                               "settings": point.resolved_settings})
            log(f"  {spec.key} done")

        # No unsteady rate runs: ALL rate tables are analytic, computed at assembly. VSPAERO's
        # unsteady Q/R stability analyses are quarantined on this pin — measured wrong-phased
        # response for surfaces at a lever arm (vsp/rates.py has the evidence and reproducer).
        if k == 0:
            for vi, V in enumerate(campaign.airspeed):
                key = f"parasite/{vi}"
                if key in done:
                    continue
                # CD0 is flap-agnostic here (the buildup knows nothing of deflection); flap 0 geometry.
                if current_flap != float(campaign.flap_rad[0]):
                    _apply_flap(session, geometry, campaign, float(campaign.flap_rad[0]))
                    current_flap = float(campaign.flap_rad[0])
                ov = par_mod.parasite_overrides(
                    session, geometry, airspeed_m_s=float(V), mach=isa.mach(float(V)),
                    reynolds_per_m=isa.reynolds_per_length(float(V)), wing_id=wing_id,
                    parasite_set=campaign.parasite_set)
                res = par_mod.run_parasite(session, geometry, overrides=ov)
                _append(out_path, {"key": key, "kind": "parasite", "v_i": vi,
                                   "cd0_total": res.cd0_total, "sref_m2": res.sref_m2,
                                   "turb_cf_eqn": res.turb_cf_eqn,
                                   "components": [vars(c) for c in res.components],
                                   "settings": res.resolved_settings})
                log(f"  {key} done")

            _append_meta(out_path, session, campaign, geometry, done)
    return out_path


def _append_meta(out_path: Path, session: Session, campaign: Campaign,
                 geometry: geom_mod.Geometry, done: set) -> None:
    if "meta" in done:
        return
    _append(out_path, {"key": "meta", "kind": "meta",
                       "openvsp_version": session.version, "pinned": session.pinned,
                       "campaign_sha256": campaign.sha256,
                       "geometry_sha256": geometry.sha256})
