# icarus rev A geometry audit

Source: `machworksvt/utils@5eb0f15b` `geometry/icarus_mk4.vsp3`, copied verbatim as
`icarus-A.vsp3`. sha256 `03502561a2a546363e444bfdfb3378469a13e41e3673f9edc7c18acc22499f99`.
Audited on OpenVSP 3.51.2 (pinned), 2026-08-17.

## What is in the file

16 geoms. Aero: `MainWing` (3 sections, span 2.283, area 0.629, AR 8.07, dihedral 1°/5°/30°,
sweep 8°/8°/15°), `Fusealge` [sic] (1.60 long), `VTail` (X-rot 62.5° → steep V, span 0.548,
area 0.100), `Elevator` (span 0.457, area 0.064, low-set behind/below the V), `H20PRO` stack
(buried aft, point mass 1.5), `Intake` (sym pair of dorsal/flank ducts). Non-aero: fuel tank +
full/half fuel conformals, SPAR stack, 2× `Servo` mesh (name collision), `ER-40` + 2 gear-strut
meshes (one side only), `Aileron Servo` mesh. The six CAD meshes are ~150k tris = ~50 of the
52 MB. No declared length unit (`Measure:LenUnit = UNITLESS`); dimensions are unambiguously
meters. 189 unused default FEA properties (discarded on load, with an O(n²) load-time warning).

Sets: `[1] Aerodynamic Surfaces` = wings + fuselage + stacks **+ `Aileron Servo` mesh**;
`[2] Inertial Components` = masses/gear/servos; `[3] Set_0` = MainWing, VTail, Elevator (a
ready-made VLM set).

Control subsurfaces (all `Surf_Type=2` both-sides, `Tess_Num=15`):

| geom / subsurf | mode | span | chord | note |
|---|---|---|---|---|
| MainWing / Flaps | **U** (EtaFlag=0) | U 0.234–0.387 (η 0.077–0.427) | 30 % | inside section 1's U band, 0.013 U margin to the section boundary |
| MainWing / Ailerons | **U** (EtaFlag=0) | U 0.436–0.529 (η 0.539–0.751) | 25 % | inside section 2's U band |
| VTail / Ruddervators | eta | η 0.10–0.90 | 25 % | |
| Elevator / SS_CONT_0 | eta | η 0.147–**1.0** | **100 %** | the stabilator, realised as a full-chord flap; reaches the tip |

Control groups as authored: `Ailerons` gains (1, 1) — the antisymmetric-pair trap, unusable for
per-side derivatives; `Flaps` gains (−1, +1) — **positive deflection is trailing-edge UP**
(measured: dCZ/dδ = +1.27, lift loss); `FF_Elevator` gains (1, −1) ✓ symmetric TE-down, but
**stored deflection −6°**; `RV_Pitch` (1, −1) and `RV_Yaw` (1, 1) — a pitch/yaw mixer, two
groups over the same subsurface copies. Copy→side on all three lifting geoms: **Surf0 = right,
Surf1 = left** (measured by mid-surface y).

Stored VSPAERO refs are stale: Sref 0.6369 / cref 0.2479 vs the current wing's 0.6288 / 0.2435
(RefFlag=1, so runs pick up the current values — the probe echoed 0.6288/0.2435). Moment ref
stored at the datum. cref via RefFlag=1 is the wing's **average** chord (TotalChord), not MAC.

## Probe solve (α=2°, β=0, V=30, pure VLM on Set_0, moment ref = datum)

ComputeGeometry tagged **all 10** group surface copies (the U-mode wing strips included — the
U-span rule is satisfied; the 0.013 margin held). Steady stab completed and every group produced
a derivative column.

CL ≈ 0.20, CL_α ≈ 4.0/rad, Cm_α = −0.58, SM about datum = +0.145 (X_np 35 mm aft of datum);
CY_β = −0.27, **Cn_β = +0.063, Cl_β = −0.093** — statically stable in all three axes.
Stabilator Cm_δ = −0.43/rad ✓; RV_Yaw CY_δ = −0.14, Cn_δ = +0.044 ✓. Magnitudes are
3-wake-iter probe quality; signs are the finding.

## Defects / hazards found

1. `Ailerons` (1,1) and `Flaps` (−1,+1) gains violate the contract's TE-down-positive-per-side
   convention; RV mixer groups cannot give per-surface derivatives. Rev B must carry the seven
   vocabulary groups: right (1,0), left (0,−1), stabilator (1,−1).
2. Stored −6° elevator deflection (runner now zeroes all groups — pipeline fix, this session).
3. `Aileron Servo` CAD mesh sits in `Aerodynamic Surfaces`; it is also one-sided. Keep it out
   of any solver set.
4. Sets are positional (`Set_0`) or overloaded; the campaign needs named, purpose-built sets.
5. In-file mass data is abandoned midway (`Density=1.0` defaults everywhere; `Fuel Mass Full`
   at density 1.0 vs `Fuel Mass Half` at 820) — confirms D8: massprops come from the ledger,
   never from OpenVSP MassProp.
6. Cosmetic-but-propagating: `Fusealge` typo, duplicate `Servo` names, `SS_CONT_0` default name.
7. OpenVSP 3.51.2 API hazards confirmed on this model: `GetGeomBBox*` **segfaults on Mesh
   geoms**; `ExportFile(EXPORT_OBJ)` exported only the CAD mesh, not the surface geoms.

## Rev B (landed 2026-08-17)

`streamline geometry apply apply-B.json` → `icarus-B.vsp3`
(sha256 `0c0118548e695cd2eced76f4606b0ef4d8e51607e736f9a94a4c597f35ef03d5`): defects 1–4 and 6
fixed — 7 vocabulary groups with per-side gains + a `flap_detent` applier group (1, −1),
deflections zeroed, `streamline_vlm` / `streamline_parasite` sets, renames (`Fuselage`,
`Servo_VTail`/`Servo_Elevator`, `Stabilator`). Geoms, meshes and mass data untouched — defect 5
stays by design (D8: ledger-computed massprops). User decisions folded in: flap detents
{0, 15, 30}°, moment reference = the datum, `.vsp3` on Git LFS.

Golden-campaign gate on rev B (same date): **25/25 lint rows pass, all 15 sign fixtures, no
waivers** — `icarus-B.5bbfd5aa.770ec9d8`. En route the gate caught VSPAERO's unsteady-stability
lever-arm defect (Cm_q +1.05); all rate tables are analytic as a consequence — evidence in
`src/streamline/vsp/rates.py`, formulas in `src/streamline/backends/analytic.py`, inputs in the
campaign `analytic_rates` blocks.
