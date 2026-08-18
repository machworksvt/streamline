# AeroDB conventions — locked with the schema

**This is contract, not documentation** (Master Plan §8.6). `conventions.py` holds the same
content as a dict; every `aerodb.json` carries a copy in its `conventions` block and the validator
requires it to equal the pinned one. `signs.py` turns the sign statements below into fixtures that
are asserted when streamline exports and again when `icarus-dynamics` ingests. Changing anything
here is a contract version bump and invalidates every released AeroDB.

`icarus-dynamics/docs/conventions.md` is the plant's own convention document and says the same
things about frames and signs; where the two could drift, the fixtures — not the prose — are what
both repositories test against.

## 1. Frames and the datum

* Body frame **FRD**: X forward (nose), Y right (starboard), **Z down**. Right-handed.
* The **datum** is the OpenVSP model origin, expressed in FRD. OpenVSP/VSPAERO model axes are
  X-aft, Y-right, Z-up; the exporter converts with the proper rotation
  `X_FRD = −X_vsp, Y_FRD = Y_vsp, Z_FRD = −Z_vsp` (det +1) and nothing downstream sees the VSP frame.
* `reference.moment_reference_point_m` is a **fixed geometric point** in FRD from the datum — the
  point every moment coefficient is about. It is **not the CG**. The consumer transfers to its CG:
  `M_cg = M_ref + (r_ref − r_cg) × F`. Choosing a geometric point (not the estimated CG) is what
  keeps a bad mass estimate out of the aero tables.

## 2. Angles, rates, units

* SI everywhere; angles in **radians**. Degrees appear in plot labels and nowhere else.
* `α = atan2(w, u)`, `β = asin(v / V)`, `V` = true airspeed [m/s], all air-relative, body components.
* Non-dimensional rates: `p̂ = p b / 2V`, `q̂ = q c̄ / 2V`, `r̂ = r b / 2V`.
* Density is **not** in the artifact. The consumer supplies ρ; the per-airspeed ρ, Mach and Re the
  producer used are metadata (`conditions`) so the run is reproducible, not inputs to the model.

## 3. Coefficients

Body-axis force and moment coefficients: `CX, CY, CZ` (÷ q̄S), `Cl` (÷ q̄Sb), `Cm` (÷ q̄Sc̄), `Cn`
(÷ q̄Sb). Right-hand moments about the body axes: `+Cl` rolls **right wing down**, `+Cm` pitches
**nose up**, `+Cn` yaws **nose right**. Lift up is **negative** `CZ`; drag at α = 0 is **negative** `CX`.

Model composition (`model.composition` in the artifact):

```
C(α, β, V, δ_flap, p̂, q̂, r̂, δ) = base(α, β, V, δ_flap)
                                 + Σ_r  C_r̂(α, β, V, δ_flap) · r̂          r ∈ {p̂, q̂, r̂}
                                 + Σ_s  C_δs(α, β, V, δ_flap) · δ_s        s ∈ control_surfaces
```

`base` is **total** — inviscid VLM plus parasite `CD0` rotated into body axes
(`ΔC = −CD0 · v̂`, `v̂ = (cosα cosβ, sinβ, sinα cosβ)`); the split is recorded in `provenance`.
Rate and control derivatives are linear in their variable and evaluated at the same
`(α, β, V, δ_flap)` as the base. **Flaps enter only through the `flap_rad` axis** and never as a
control derivative — both at once would double count.

## 4. Control surfaces

Seven physical surfaces, by name, in this order:
`aileron_left, aileron_right, flap_left, flap_right, stabilator, ruddervator_left, ruddervator_right`.

**Positive deflection is trailing-edge down about the hinge line, per physical surface.** For a
V-tail panel, "down" means toward the panel's lower surface (the side facing the belly). Consequences
the fixtures assert:

| perturbation | expected | why |
|---|---|---|
| `+α` | `∂CZ/∂α < 0` | lift up is −Z |
| `+β` (wind from the right) | `∂CY/∂β < 0`, `∂Cn/∂β > 0`, `∂Cl/∂β < 0` | side force opposes sideslip; weathercock; dihedral effect |
| `+stabilator` (TE down) | `∂Cm/∂δ < 0` | tail lift up → nose down |
| `+ruddervator_left` and `+ruddervator_right` together | `∂Cm/∂δ < 0` | elevator sense |
| `+aileron_left` (TE down) | `∂Cl/∂δ > 0` | left lift up → right wing down |
| `+aileron_right` (TE down) | `∂Cl/∂δ < 0` | mirror |
| `+p̂` | `∂Cl/∂p̂ < 0` | roll damping |
| `+q̂` | `∂Cm/∂q̂ < 0` | pitch damping |
| `+r̂` | `∂Cn/∂r̂ < 0` | yaw damping |
| `+α` | `∂Cm/∂α < 0` | static longitudinal stability (waivable — a design property, not a frame fact) |

Left/right pairs mirror: longitudinal effects (`CX, CZ, Cm`) equal, lateral (`CY, Cl, Cn`) opposite.

The consumer maps these names onto its own actuator indices; the artifact knows nothing about the
FSW's `surface_cmd` layout.

## 5. Grids and validity

* Every axis is strictly increasing; tables are dense, finite, row-major, shape
  `(n_flap, n_V, n_beta, n_alpha)`.
* `validity` states the α/β range and maximum deflection the producer stands behind, and
  `validity.stall` lists grid points that are likely beyond stall (from the campaign's `CL_max`
  estimate) — those points are in the table because interpolation needs them; a consumer that trims
  there should say so.

## 6. What a consumer must do

Validate the file against this contract at load; assert the sign fixtures; transfer moments to its
CG; interpolate `base`, `rate` and `control` over all four axes (bspline is what `icarus-dynamics`
uses — cubic along axes with ≥ 4 breakpoints, linear along shorter ones, singleton axes squeezed;
`tests/test_casadi_ingest.py` shows the tables support it and codegen to `<math.h>`-only C); apply
flaps through the axis only; treat `provenance.confidence` and `completeness` as data, not
decoration.
