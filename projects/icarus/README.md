# projects/icarus — the aircraft

Everything specific to the Icarus airframe, versioned (Master Plan §8.2). Nothing under here is
produced by a run; runs write to `results/` (gitignored) and releases go to `icarus-aerodb`.

| path | content | who supplies it |
|---|---|---|
| `geometry/icarus-A.vsp3` | revision **A** = `machworksvt/utils@5eb0f15b geometry/icarus_mk4.vsp3` verbatim, sha256 `03502561…499f99`. See `geometry/AUDIT-A.md`. | user (landed 2026-08-17) |
| `geometry/icarus-B.vsp3` | revision **B** = A + `geometry apply geometry/apply-B.json` (sha256 `0c011854…ef03d5`): the 7 contract control groups with per-side gains (Surf0 = right), `flap_detent` applier group, `streamline_vlm` / `streamline_parasite` sets, zeroed deflections, name hygiene. Geoms, meshes and mass data untouched. A revision letter increments on any OML / mass / control-surface change that invalidates aero data. `.vsp3` files ride **Git LFS** (`.gitattributes`; run `git lfs install` once). | P3, 2026-08-17 |
| `campaign/canonical.json` | the release campaign: D7 envelope (α −8…16×2°, β ±15×5°, V {20,30,45}, flaps {0,15,30} — detents user-confirmed 2026-08-17), moment reference = the datum, every solver setting, `cl_max_estimate`, lint waivers. **The envelope is this file and nothing else.** 819 stab points — CI-sharded, never run whole locally. | P3/P5 |
| `campaign/golden.json` | the coarse grid every PR runs (§8.9 #2): 9 stab points, one V, clean config | P3/P5 |
| `golden/reference/` | the pinned outputs of the golden campaign, committed by a human after review | P5 |
| `massprops/ledger.json` | component masses and positions (FRD from the OpenVSP origin, metres, kg). Rough is fine; the artifact says `estimated` / `confidence: low`. | user |
| `engine/bench/<rosbag>/` + `engine/spec.json` → `engine/engine_deck.json` | H20PRO static bench runs (machpilot rosbag2 → CSV, four bags Mar–Nov 2025, raw `.db3` on LFS) + the declared spec (datasheet block, power-law thrust prior — **no load cell exists** —, fuel density, thrust line); `streamline engine fit` builds the deterministic deck. `engine/PROVENANCE.md` has the full evidence: fuel-flow unit verification, per-field sources, ECU dynamics as measured. `fuel.capacity_kg` is a placeholder pending the tankage number. | user (bags, 2026-08-17) / streamline |

Not here: anything a solver writes (`.vspaero`, `.stab`, `.history`, `.vspgeom`, …) — see the
root `.gitignore`.
