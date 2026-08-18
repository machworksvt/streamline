# Fusion 360 mass model → ledger

Source: Autodesk Fusion document **"Weight Estimates CAD"** (Mach Works hub, project *Mach
Works*, folder *1) System Integration*; owner Abu Razbir). Pulled 2026-08-18 through the Fusion
MCP server with `pull_bodies.py` into `bodies-2026-08-18.psv` (2398 B-Rep bodies, 11 top-level
occurrences + 1 root body). `streamline massprops from-fusion` (`make massprops`) turns the export
+ `../fusion-overrides.json` into `../ledger.json`; `tests/test_massprops_fusion.py` pins that the
committed ledger regenerates byte-for-byte.

## What the model is

A component-level assembly, not a uniform solid: every part is a solid with a material whose
density was calibrated so the part hits a weighed/catalogue mass ('Bottom fuselage' 1375,
'Wing skin' 392, 'Intake assembly + engine' 4294, 'Avionics' 1746, 'Wing gear' 3218, 'Nose gear'
4749, 'Foam core' 448, 'Garolite'/'Bottom frames' 1799, 'Main Spar' 1550, 'PA6' 1090 kg/m³ …).
Frame = OpenVSP's (X aft, Y right, Z up, common origin; nose tip at X = −822 mm, wing root LE at
−103 mm, span ±1129 mm, tails at 620–760 mm). Group masses as exported (kg, x = root-frame CG):

| group | kg | x mm | note |
|---|---|---|---|
| Bottom Fuselage (BOTTOM_SHELL) | 4.255 | −323 | one calibrated shell |
| Left / right wing assembly | 2 × 4.022 | +86 | skins 2.35, flap .45, aileron .24, gear .37, 2 servos .20 each side |
| 2026 MASTER INTAKE (intake + engine + exhaust) | 2.486 | +333 | one smeared density over 46 bodies (engine group alone reads 0.91 vs the H20PRO's 1.65 kg dry — the group total is what was calibrated) |
| Avionics Shell | 1.225 | −500 | 2 × Zeee 3S 8000 (0.413 each), distribution board .14, servo PDB .04, RFD900X, GPS-RTK, BNO055, BMP390; **no ECU / fuel pump / flight computer / harness** |
| V-tails ("sigh", "sigh v2(Mirror)") | 2 × 1.239 | +655 | **1.08 kg per tail is Fusion-default 'Steel'** — see overrides |
| Main tank rework (structure only) | 0.891 | −59 | PA12-CF tank .67 + hopper .18 + fittings |
| Recovery bay + nose gear | 0.634 | −316 | |
| Top Fuselage Assembly | 0.577 | +184 | TOP_SHELL 0.42 (hidden in the model) + G10 frames/longerons |
| Bottom Fuselage Structure | 0.280 | +484 | |
| ROOT Body23 'Main Spar' | 0.126 | +11 | modelled on the LEFT only (y = −320) |
| **Fuel** 'Fuel tank (full)' Body48 + Body49 | 3.901 | −60 | 3.32 + 0.59 L at WATER density (997.5); hidden |
| all bodies | 24.894 | +36 | |
| dry (all − fuel), as modelled | 20.994 | +54 | |

## What the Fusion 'Physical' panel reported, and why it is not used

The 20.63 kg / CoM (90.87, −6.27, 30.07) mm handed over on 2026-08-17 is exactly what the API
returns for the ROOT component at the panel's default (low) accuracy. It is not the sum of the
parts: visible bodies sum to 20.52 kg at x = +54 mm, all bodies to 24.89 kg at +36 mm; at high
accuracy the same root call returns 24.29 kg at +20 mm (all bodies, minus a Fusion quirk that
drops the 8 bodies living directly in `sigh:1`). Per-body numbers are accuracy-independent and
their positions check against the geometry (nose −822, wing LE −103, tails +650), so the ledger
is built from the bodies and the panel number is discarded. Two more traps in the panel path:
it counts only *visible* bodies (the fuel and the top shell were hidden), and its "density"
874 kg/m³ is just mass/volume of that set — the earlier "uniform fill" reading was wrong.

## What is odd in the tail (both `sigh:1` and `sigh v2(Mirror):1`)

Two things, both Fusion's default 'Steel' where the wing has calibrated materials:

| bodies (per side) | as modelled | wing equivalent | corrected |
|---|---|---|---|
| A6320 Servo ×2 (31.5 cm³ each) | Steel, 248 g each | same part in the wing: 'Servo' 3218 → 101.5 g | 203 g |
| Rib 1, Rib 2, Rib 3, Base Rib, Spar 1, Spar 2, Spar 3 (74.9 cm³ total) | Steel, 588 g | wing ribs + spar webs: 'Foam core panel' 448.5 (6 mm sandwich) | 34 g |
| ELEVATOR_SURFACE, VTail print ×3, vTail-Internals ×6, Elevator Base | Foam core 448.5, 157 g | — | as is |
| **per tail** | **1.239 kg** | | **0.394 kg** |

The geometry check settles the material question: a face census through the API shows every one
of the seven structural bodies is a **6.00 mm plate** (ribs chordwise, normal (0,1,0); "spars"
are swept spanwise webs, normals (−0.87,0.5,0)…(−0.94,0.34,0)) with no cylindrical faces — the
same construction as the wing's ribs and spar webs (also 6.00 mm plates, 'Foam core panel').
The only tube in the model is the root Main Spar (CF 1550, correctly assigned). Servo Adapter
brackets have no bodies; the tail's remaining parts are foam/print at 448.5 and plausible.

## Overrides applied (`../fusion-overrides.json`)

* fuel bodies excluded from the dry ledger → `fuel` block: 3.91 L, 3.13 kg at 800 kg/m³, CG
  x_FRD +0.060 m (60 mm ahead of the datum, ~62 mm ahead of the dry CG → burning fuel moves the
  CG AFT ~8 mm; the dry (landing) case is the aft-critical one).
* the four V-tail A6320 servos: 'Steel' (248 g each) → the calibrated 'Servo' density the same
  part carries in the wings (101.5 g). −0.58 kg at x ≈ 630 mm.
* the fourteen tail plates (7 per side): 'Steel' → the wing's 'Foam core panel' 448.5 (user
  2026-08-18: tail structure = wing structure, CF plate cut). −1.11 kg at x ≈ 660 mm.
* mirrored right half of the root 'Main Spar' body (+0.126 kg at y = +320).
* `forward_equipment_and_ballast`: sized by the generator to put the dry CG at x_FRD −0.005 m
  (5 mm aft of the datum ≈ 120 mm behind the wing root LE). With the tail corrected the dry CG
  lands at −0.0019 m on its own — forward of the target — so the entry is sized to **zero and
  omitted**. It re-appears automatically if a re-pull moves the CG aft of the target.

## What the CG needs (x = root frame, mm aft of the datum; NP_vlm +47, NP with Munk fuselage
## correction ≈ +35, c̄ 0.242 m; aft limit +10, target 0…+10, forward limit −40)

| case | dry kg | dry CG | SM vlm / corr | nose mass to reach +5 |
|---|---|---|---|---|
| as modelled (steel tails) | 20.99 | +54 | −3 % / −8 % | 1.46 kg |
| tail servos fixed | 20.41 | +37 | +4 % / −1 % | 0.94 kg |
| **+ tail plates at the wing's density (ledger of record)** | **19.43** | **+2** | **+19 % / +14 %** | **0** |
| (if the plates were solid CF 1550) | 19.60 | +7 | +17 % / +12 % | 0 |

So the CAD airplane balances itself once the tail carries its real mass. Two consequences: the
equipment the CAD lacks (ECU, pump, FC, harness) will push the CG FORWARD if it goes in the
nose bay — the aft end of the box (+10) is where to aim, and the sim already says the pitch axis
is on the stiff side there (short period CAP 5.1 vs the 8785C Level-1 ceiling 3.6, ζ 0.296 vs
0.30 → Level 2 at 50–65 m/s with the VLM neutral point; the fuselage-corrected NP softens
that to about the boundary). Ballast, if any, may end up in the TAIL. Remaining questions:
tankage 3.9 L modelled vs "4.5 kg" recalled; what is not in the CAD and where; then a
two-scale weighing.

## Re-pulling

Open the document in Fusion, run `pull_bodies.py` (Scripts and Add-Ins, or through the MCP
`fusion_mcp_execute` script feature), save the printed rows as `bodies-<date>.psv`, point
`make massprops` (Makefile) at it, regenerate, and re-check the overrides still match (an
unmatched override is an error by design).
