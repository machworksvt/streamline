# AeroDB contract — schema 0.1.0

Generated from `schema.py`, `lint.py`, `signs.py`, `completeness.py` by `make spec`. Do not edit by hand. Conventions are in `conventions.md` (locked with this schema).

## Artifacts

One release = `aerodb.json` + `massprops.json` + `engine_deck.json` + `MANIFEST.json` (all hashed, canonical JSON: sorted keys, compact, shortest-repr floats, one trailing newline, no NaN) + `BUILD.json` (unhashed: timestamps, host, wall time) + `report.pdf`/`report.json`.

### `aerodb.json`

| path | kind | unit | required | meaning |
|---|---|---|---|---|
| `schema.name` | str | - | yes | 'aerodb' (pinned value) |
| `schema.version` | str | - | yes | this schema's version (pinned value) |
| `id` | str | - | yes | <aircraft>-<rev>.<campaign8>.<streamline8> — identity of the INPUTS; the content hash lives in MANIFEST.json |
| `aircraft.name` | str | - | yes | e.g. 'icarus' |
| `aircraft.geometry_rev` | str | - | yes | revision letter of the .vsp3 (§8.2) |
| `aircraft.geometry_file` | str | - | yes | basename of the .vsp3 |
| `aircraft.geometry_sha256` | str | - | yes | sha256 of the .vsp3 bytes |
| `conventions` | object | - | yes | copy of conventions.CONVENTIONS; must equal the pinned one (pinned value) |
| `reference.S_m2` | number | m^2 | yes | reference area |
| `reference.b_m` | number | m | yes | reference span |
| `reference.cbar_m` | number | m | yes | reference chord |
| `reference.moment_reference_point_m` | vec3 | m | yes | moment reference point, FRD from the datum (NOT the CG) |
| `surfaces` | enum_list | - | yes | the seven physical surfaces, in contract order (pinned value) |
| `axes.alpha_rad` | axis | rad | yes | angle of attack breakpoints, strictly increasing |
| `axes.beta_rad` | axis | rad | yes | sideslip breakpoints, strictly increasing |
| `axes.airspeed_m_s` | axis | m/s | yes | true-airspeed breakpoints, strictly increasing |
| `axes.flap_rad` | axis | rad | yes | flap detent breakpoints (both flaps together), strictly increasing |
| `conditions.altitude_m` | number | m | yes | geometric altitude the campaign ran at |
| `conditions.atmosphere` | str | - | yes | 'ISA' or a named override |
| `conditions.density_kg_m3` | vector shape `n_V` | kg/m^3 | yes | density per airspeed breakpoint (metadata; not a model input) |
| `conditions.mach` | vector shape `n_V` | - | yes | Mach per airspeed breakpoint |
| `conditions.reynolds_cbar` | vector shape `n_V` | - | yes | Reynolds number on cbar per airspeed breakpoint |
| `tables.base.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total CX on the grid |
| `tables.base.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total CY on the grid |
| `tables.base.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total CZ on the grid |
| `tables.base.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total Cl on the grid |
| `tables.base.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total Cm on the grid |
| `tables.base.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | - | yes | total Cn on the grid |
| `tables.rate.p_hat.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.p_hat.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.p_hat.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.p_hat.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.p_hat.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.p_hat.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂p_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.q_hat.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂q_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂r_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂r_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂r_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂r_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂r_hat (per unit non-dimensional rate) |
| `tables.rate.r_hat.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂r_hat (per unit non-dimensional rate) |
| `tables.control.aileron_left.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_left.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_left.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_left.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_left.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_left.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂δ_aileron_left (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.aileron_right.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂δ_aileron_right (per rad, trailing-edge down positive) |
| `tables.control.stabilator.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.stabilator.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.stabilator.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.stabilator.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.stabilator.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.stabilator.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂δ_stabilator (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_left.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂δ_ruddervator_left (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.CX` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CX/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.CY` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CY/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.CZ` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂CZ/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.Cl` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cl/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.Cm` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cm/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `tables.control.ruddervator_right.Cn` | table shape `n_flap×n_V×n_beta×n_alpha` | 1/rad | yes | ∂Cn/∂δ_ruddervator_right (per rad, trailing-edge down positive) |
| `model.composition` | str | - | yes | the composition formula, verbatim from conventions (pinned value) |
| `model.base_includes` | list[str] | - | yes | what is summed into base, e.g. ['vspaero_vlm_inviscid', 'parasite_cd0_rotated_to_body'] |
| `model.flaps_enter_via` | str | - | yes | 'axis' (pinned value) |
| `validity.alpha_rad` | range | rad | yes | [lo, hi] the producer stands behind |
| `validity.beta_rad` | range | rad | yes | [lo, hi] |
| `validity.delta_rad_max` | number | rad | yes | largest surface deflection the linear derivatives are meant for |
| `validity.notes` | str | - | yes | free text: what the method cannot see (stall, hinge moments, ...) |
| `validity.stall.cl_max_estimate` | vector shape `n_flap` | - | yes | CL_max estimate per flap detent (from the campaign; low confidence) |
| `validity.stall.source` | str | - | yes | where the estimate came from |
| `validity.stall.points_beyond` | list[object] | - | yes | grid points whose CL exceeds the estimate: {flap_i, V_i, beta_i, alpha_i, CL} |
| `provenance.backend.name` | str | - | yes | 'vspaero' |
| `provenance.backend.openvsp_version` | str | - | yes | e.g. '3.51.2' |
| `provenance.backend.method` | str | - | yes | 'VLM' |
| `provenance.backend.unpinned` | bool | - | yes | true if produced on an OpenVSP other than the pinned one; the release lint refuses |
| `provenance.backend.settings` | object | - | yes | every solver input, as resolved (the no-implicit-defaults register) |
| `provenance.campaign_sha256` | str | - | yes | sha256 of the canonical campaign definition |
| `provenance.streamline_commit` | str | - | yes | git commit of streamline that produced this ('dirty' suffix allowed for non-release runs) |
| `provenance.contract_version` | str | - | yes | aerodb_contract version (pinned value) |
| `provenance.per_table_source` | object | - | yes | table path → source id (multi-backend later) |
| `provenance.confidence.default` | str | - | yes | 'unquantified' in v0 |
| `knockdowns.control_effectiveness` | object | - | yes | surface → {factor, uncertainty, source}; 1.0/null/'unquantified' in v0 |
| `lint.version` | int | - | yes | lint list version |
| `lint.results` | list[object] | - | yes | [{check, status: pass|warn|fail|waived, detail}] |
| `completeness.version` | int | - | yes | checklist version |
| `completeness.flags` | list[object] | - | yes | [{item, status: clear|open|waived, note}] |

### `massprops.json`

| path | kind | unit | required | meaning |
|---|---|---|---|---|
| `schema.name` | str | - | yes |  (pinned value) |
| `schema.version` | str | - | yes |  (pinned value) |
| `aircraft.name` | str | - | yes |  |
| `aircraft.geometry_rev` | str | - | yes |  |
| `aircraft.geometry_sha256` | str | - | yes |  |
| `mass_kg` | number | kg | yes | total mass |
| `cg_m` | vec3 | m | yes | CG, FRD from the datum |
| `inertia_kg_m2` | matrix3 | kg m^2 | yes | inertia tensor about the CG, FRD; symmetric, positive definite |
| `components` | list[object] | - | yes | [{name, mass_kg, cg_m[3], inertia_local_kg_m2[3][3] | shape, source}] |
| `fuel.cg_m` | vec3 | m | no | where the fuel mass sits, FRD from the datum; the consumer's fuel state moves the CG and inertia toward it. Capacity/density are the engine deck's `fuel` block |
| `status.mass` | enum | - | yes |  |
| `status.cg` | enum | - | yes |  |
| `status.inertia` | enum | - | yes |  |
| `confidence.mass` | enum | - | yes |  |
| `confidence.cg` | enum | - | yes |  |
| `confidence.inertia` | enum | - | yes |  |
| `provenance.method` | str | - | yes | 'ledger_point_masses' in v0 |
| `provenance.ledger_sha256` | str | - | yes |  |
| `provenance.contract_version` | str | - | yes |  (pinned value) |

### `engine_deck.json`

| path | kind | unit | required | meaning |
|---|---|---|---|---|
| `schema.name` | str | - | yes |  (pinned value) |
| `schema.version` | str | - | yes |  (pinned value) |
| `engine` | str | - | yes | e.g. 'Hybl H20PRO' |
| `static.setting_kind` | enum | - | yes | what the setting axis is |
| `static.setting` | axis | - | yes | throttle fraction [0..1] or RPM, strictly increasing |
| `static.thrust_N` | vector shape `n_setting` | N | yes | static thrust per setting |
| `static.fuel_flow_kg_s` | vector shape `n_setting` | kg/s | no | fuel flow per setting |
| `static.egt_K` | vector shape `n_setting` | K | no | exhaust gas temperature per setting |
| `static.source` | object | - | no | per-column provenance: {thrust_N, fuel_flow_kg_s, egt_K} → SOURCE_KINDS + note |
| `limits.setting_idle` | number | - | yes | minimum idle setting (same axis as static.setting) |
| `limits.setting_max_continuous` | number | - | yes | maximum continuous setting |
| `limits.setting_max_transient` | number | - | no | absolute (time-limited) maximum setting |
| `limits.source` | enum | - | no |  |
| `fuel.capacity_kg` | number | kg | no | usable fuel at takeoff (aircraft tankage × density) |
| `fuel.density_kg_m3` | number | kg/m^3 | no | fuel density used to convert bench volumetric flow |
| `fuel.type` | str | - | no | e.g. 'Jet A-1 + 5% turbine oil' |
| `thrust_model.kind` | enum | - | no | 'measured' → static.thrust_N is bench data; 'power_law' → T = T_anchor·(N/N_anchor)^k, a declared prior |
| `thrust_model.exponent` | number | - | no | k in the power law (small turbojets: 2–3 in the upper band) |
| `thrust_model.anchor_thrust_N` | number | N | no |  |
| `thrust_model.anchor_setting` | number | - | no | setting at which anchor_thrust_N applies |
| `thrust_model.source` | enum | - | no |  |
| `dynamics.spool_up_time_constant_s` | number | s | no | first-order tracking τ for setting increases |
| `dynamics.spool_down_time_constant_s` | number | s | no | first-order tracking τ for setting decreases |
| `dynamics.slew_up_per_s` | number | setting/s | no | maximum sustained setting increase rate |
| `dynamics.slew_down_per_s` | number | setting/s | no | maximum sustained setting decrease rate |
| `dynamics.spool_fit` | object | - | no | how the constants were obtained: {method, n_steps_up, n_steps_down, n_runs_slew_up, n_runs_slew_down, steps: [...]} |
| `dynamics.source` | enum | - | no |  |
| `ambient.pressure_Pa` | number | Pa | no |  |
| `ambient.temperature_K` | number | K | no |  |
| `thrust_line.point_m` | vec3 | m | yes | a point on the thrust line, FRD from the datum |
| `thrust_line.direction_b` | vec3 | - | yes | unit direction of thrust in FRD |
| `status` | enum | - | yes | overall: 'measured' only when thrust itself is measured; power-law thrust ⇒ 'estimated' |
| `provenance.bench_file_sha256` | str | - | yes | sha256 of the primary bench source (or of a manifest of several) |
| `provenance.bench_files` | list[object] | - | no | every bench source used: [{path, sha256, role}] |
| `provenance.test_date` | str | - | yes | ISO date of the bench test — provenance of the DATA, not a build timestamp |
| `provenance.notes` | str | - | yes |  |
| `provenance.contract_version` | str | - | yes |  (pinned value) |

### `MANIFEST.json`

| path | kind | unit | required | meaning |
|---|---|---|---|---|
| `id` | str | - | yes |  |
| `contract_version` | str | - | yes |  (pinned value) |
| `files` | object | - | yes | filename → sha256 of every hashed file in the release |
| `geometry_sha256` | str | - | yes |  |
| `campaign_sha256` | str | - | yes |  |
| `streamline_commit` | str | - | yes |  |
| `openvsp_version` | str | - | yes |  |
| `unpinned` | bool | - | yes |  |

Table shape symbols: `n_flap × n_V × n_beta × n_alpha` = lengths of `axes.flap_rad`, `axes.airspeed_m_s`, `axes.beta_rad`, `axes.alpha_rad`; row-major.

## Vocabulary

Surfaces (order is contract): `aileron_left`, `aileron_right`, `flap_left`, `flap_right`, `stabilator`, `ruddervator_left`, `ruddervator_right`.  
Control derivatives exist for: `aileron_left`, `aileron_right`, `stabilator`, `ruddervator_left`, `ruddervator_right` (flaps enter via the axis).  
Coefficients: `CX`, `CY`, `CZ`, `Cl`, `Cm`, `Cn`; rates: `p_hat`, `q_hat`, `r_hat`.

## Physics lint (version 1)

| check | severity | what |
|---|---|---|
| `finite` | fail | no NaN/Inf anywhere |
| `symmetry_beta0` | fail | CY, Cl, Cn ≈ 0 at β = 0 (symmetric configuration) |
| `lr_mirror` | fail | left/right derivative tables mirror (longitudinal equal, lateral opposite) |
| `cl_alpha_band` | fail | CL_α within 3–7 /rad (catches per-degree and reference-area slips) |
| `cl_monotone` | warn | CL(α) monotone inside the validity range |
| `cm_q_band` | fail | Cm_q within −60…−2 per unit q̂ (catches dimensional rates) |
| `static_margin_band` | warn | static margin about the reference point in 0.02–0.40 |
| `stall_points` | warn | grid points beyond the CL_max estimate |
| `pinned` | fail | produced on the pinned OpenVSP |
| `completeness_required` | fail | release-required completeness items are clear |

## Sign fixtures (version 1)

Evaluated at flap 0, the middle airspeed, β≈0, α≈0. Asserted at export and at ingest.

| fixture | expects | waivable |
|---|---|---|
| `lift_up_is_negative_CZ` | ∂CZ/∂α < 0: lift up is −Z | no |
| `drag_is_negative_CX` | CX < 0 at α = 0: drag points aft | no |
| `sideforce_opposes_sideslip` | ∂CY/∂β < 0 | no |
| `weathercock` | ∂Cn/∂β > 0 (directional stability) | yes |
| `dihedral_effect` | ∂Cl/∂β < 0 | yes |
| `static_longitudinal_stability` | ∂Cm/∂α < 0 | yes |
| `roll_damping` | ∂Cl/∂p̂ < 0 | no |
| `pitch_damping` | ∂Cm/∂q̂ < 0 | no |
| `yaw_damping` | ∂Cn/∂r̂ < 0 | no |
| `stabilator_te_down_is_nose_down` | ∂Cm/∂δ_stab < 0 | no |
| `stabilator_te_down_lifts` | ∂CZ/∂δ_stab < 0 (tail lift up) | no |
| `ruddervators_together_are_an_elevator` | Σ ∂Cm/∂δ_rv < 0 | no |
| `left_aileron_te_down_rolls_right` | ∂Cl/∂δ_aL > 0 | no |
| `right_aileron_te_down_rolls_left` | ∂Cl/∂δ_aR < 0 | no |
| `ailerons_lift_when_te_down` | Σ ∂CZ/∂δ_a < 0 | no |

## Completeness checklist (version 1)

| item | required for release | what |
|---|---|---|
| `reference_quantities` | yes | S, b, cbar set explicitly (not OpenVSP defaults) and match the wing |
| `moment_reference_point` | yes | the moment reference point is set from the campaign, not left at 0 |
| `surfaces_present` | yes | all seven control surfaces exist as OpenVSP subsurfaces |
| `surfaces_hinged` | yes | every control surface has a hinge line and TE-down-positive sense verified |
| `surface_vocabulary` | yes | VSPAERO control groups are named exactly per conventions.SURFACES, one group per surface |
| `flap_detents_defined` | yes | flap detent angles in the campaign match the geometry's flap groups |
| `engine_geometry` | no | intake / nacelle / exhaust bodies present in the analysed set |
| `gear_geometry` | no | landing gear geometry present and in a set that can be toggled |
| `mass_ledger` | no | a component mass ledger exists for massprops |
| `airfoils_defined` | no | wing/tail sections carry the intended airfoils, not the OpenVSP default |
