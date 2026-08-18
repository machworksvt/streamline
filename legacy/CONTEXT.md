# Streamline Project Deep Overview

## 0. Mission & Scope
- Streamline extends NASA's OpenVSP Python API into a stability-and-control focused aircraft design workbench aimed at GNC workflows and accessible to undergraduate design teams.
- The tool shepherds project requirements into design alternatives by managing OpenVSP Sets, Modes, and Variable Presets so that flaps, payloads, hinges, and UDPs can be toggled deterministically.
- Analyses produce canonical aero tables, linearized models, and mission feasibility metrics, recorded as structured JSON/CSV artifacts for downstream consumers such as Simulink and future report generators.
- Current emphasis is on deterministic, well-typed data contracts and dependable OpenVSP orchestration; upcoming expansions include XFOIL loops, structural checks, optimization, and richer reporting.

## 1. Platform, Environment, and Assumptions
- Target platform is Windows; the supported workflow uses the `setup_streamline.ps1` script to build/refresh a Conda environment.
- OpenVSP v3.42.3 (with the vendor Python bindings) is the validated runtime; the manager can auto-init the GUI session when requested.
- SI units are the default throughout Streamline except where the OpenVSP API expects other units (conversions happen at the boundary).
- Reference frames follow conventional aerospace practice: NED for states, stability axes for aerodynamic coefficients (with converters available in `core/converters.py`).
- One project is active at a time; higher-level surfaces such as the future TUI will bind to a single project root during a session.
- Static reference data (taxonomy tables, airfoil libraries, presets) live under `data/`, while projects carry their own tuned assets under `projects/<id>/`.

## 2. Repository Layout (high-level)
Key modules align tightly with the orchestration story:

```
streamline/
  main.py
  analysis/
    manager.py
  core/
    schema.py
    errors.py
    logging.py
    converters.py
    tables.py
    taxonomy.py
  design/
    params.py
  exports/
    simulink.py
  io/
    fs.py
    config_catalog.py
    op_catalog.py
    results_index.py
  vsp/
    session.py
    sets.py
    configure.py
    operating_point.py
    util.py
    analysis.py
    results.py
    run_utils.py
    hooks.py
    contracts.py
    contracts/
      base.py
      compute_geometry.py
      stability.py
      parasite_drag.py
    analyses/
      compute_geometry.py
      stability.py
      parasite_drag.py
projects/
  <project_id>/ ... project-scoped configs, ops, missions, results
data/
  taxonomy/dod_uav_groups.json and other shared reference tables
setup_streamline.ps1
```

- `streamline/analysis/manager.py` owns the AnalysisManager queue, caching, dependency tracking, VSP lock, and artifact materialization.
- `streamline/core/` holds shared Pydantic models, logging helpers, taxonomy converters, and table utilities.
- `streamline/io/` wraps project filesystem access, catalog loading, and the persistent results index.
- `streamline/vsp/` encapsulates all OpenVSP bindings: session lifecycle, configuration applicators, operating-point helpers, reusable analysis helpers, and per-analysis runners/contracts.
- `projects/` hosts user-generated geometry, definitions, results, and exports; `data/` retains repository-wide resources; `setup_streamline.ps1` bootstraps the environment.

## 3. Core Data Contracts (Pydantic + Pandas)
Structured models keep JSON on disk and payloads in memory consistent.

### 3.1 ProjectDefinition (`streamline/core/schema.py`)
- `project_id`, `description`, `aircraft_file`, `default_set` capture the high-level identity and baseline OpenVSP set.
- `versions` tracks schema/tool provenance; `references` lists relative paths to missions, powerplants, operating points, and configurations.
- `uav` embeds a `UAVDefinition`; `control_policy` and `mixing_profiles` prepare for future control allocation logic; `notes` records freeform context.

### 3.2 UAVDefinition
- Encodes DoD group, propulsion type, and notes for classification; propulsion literals are `"electric_prop"`, `"ic_prop"`, `"micro_jet"`, `"turbofan"`, `"custom"`.
- Detailed mass and geometry data stay out of the static definition and are instead derived per-analysis from OpenVSP results.

### 3.3 MissionDefinition & MissionPhase
- Missions comprise weighted phases (`MissionPhase` with type literals such as `takeoff`, `climb`, `cruise`, `loiter`, `descent`, `landing`, `sprint`, `reserve`).
- Each phase carries target values (e.g., `speed_mps`, `mach`, `altitude_m`) plus optional constraints; mission-level `environment`, `reserves`, and `objectives` round out the scenario description.

### 3.4 PowerplantDefinition
- Describes propulsion metadata: maps, dynamics, limits, and energy models as dictionaries for flexible extension.
- Shares the `PropulsionType` enum with the UAV definition for consistency.

### 3.5 OperatingPoint
- Requires exactly one of `mach` or `tas_mps` (validated post-init) alongside `altitude_m` and optional mass/atmosphere overrides.
- Provides hooks for density/pressure/temperature overrides so analyses can reference either ISA-derived or custom freestream states.

### 3.6 Configuration
- Couples `ModeRef` (preferred) with optional explicit `geom_set_index`/`geom_set_name` fallbacks.
- Lists `VarPresetRef` entries, `control_surface_groups`, `hinges`, `payloads_toggle`, and both `udp_overrides` and `runtime_overrides` for deterministic configuration application.
- Notes allow human-readable justification for presets or overrides.

### 3.7 RunManifest & Results Index
- `RunManifest` records tool versions, ticket hash, timestamps, and artifact paths; every receipt includes one.
- `streamline/io/results_index.py` serializes `ResultIndexEntry` objects under `<project>/results/index.json`, capturing analysis key, ticket hash, artifact directory, summary metadata, and manifest snapshot.
- Materializers update the index via `append_result_entry`, while invalidation utilities handle stale entries when artifacts disappear.

## 4. OpenVSP Integration (session, GUI, sets, modes)
- `vsp/session.py` initializes OpenVSP (headless or GUI), binds version metadata, and provides `vsp_guard` lock helpers and GUI lock/unlock wrappers.
- `vsp/hooks.py` centralizes callbacks that the GUI can trigger (e.g., to coordinate with the manager when the GUI is paused).
- `vsp/sets.py` enumerates sets, counts membership, and picks a populated fallback when requested sets are empty.
- `vsp/configure.py` translates `Configuration` models into OpenVSP actions, preferring Modes but gracefully falling back to set/preset toggles and UDP overrides.
- `vsp/operating_point.py` and `vsp/util.py` apply operating-point data, control deflections, UDP overrides, and list helpers expected by the OpenVSP API.
- `vsp/analysis.py`, `vsp/results.py`, and `vsp/run_utils.py` wrap common ExecAnalysis workflows, CSV dumping, and artifact path handling.

## 5. Analysis Pattern: Tickets, Payloads, Receipts, Manager
- The `streamline/vsp/contracts` package defines a base `Ticket`/`Receipt` Pydantic layer plus per-analysis payload dataclasses; `contracts.py` keeps legacy helper aliases for convenience.
- Each analysis runner accepts a typed Ticket and optional applied configuration/operating-point objects, returns a Payload, and leaves filesystem side effects to the manager's materializers.
- `AnalysisManager` orchestrates job submission, priority queueing, dependency tracking, and caching under a global VSP lock. It auto-registers builtin analyses and exposes `submit`, `drain`, and `invalidate` APIs for higher layers.
- The manager hashes tickets, checks in-memory caches keyed by analysis and ticket hash, and records dependency keys so later invalidation (e.g., config edit, freestream change) can purge stale receipts.
- Materializers convert payloads into disk artifacts (`ticket.json`, CSV tables, `summary.json`, `run_manifest.json`), append entries to the project results index, and return enriched receipts to callers.

## 6. Implemented Analyses (current)

### 6.1 VSPAERO Compute Geometry
- `vsp/analyses/compute_geometry.py` prepares VSPAERO geometry inputs, honoring Mode/Set resolution and symmetry/analysis-method flags from the ticket.
- Outputs a `ComputeGeometryPayload` and `ComputeGeometryReceipt` capturing the VSP results ID, run manifest, and artifact paths; subsequent analyses can rely on cached geometry data.

### 6.2 VSPAERO Stability (single-point)
- `vsp/analyses/stability.py` applies configurations, control deflections, and operating points before executing a one-point `VSPAEROSweep` in stability mode (alpha, beta, Mach locked with Npts=1).
- Pulls base stability-axes and body-axes coefficients plus derivative tables into Pandas DataFrames, calculates static margin and neutral point, and surfaces control group metadata in the receipt.
- The materializer writes ticket/context snapshots, derivative CSVs, summary JSON, and updates the results index with core metrics (e.g., static margin).

### 6.3 Parasite Drag
- `vsp/analyses/parasite_drag.py` configures the Parasite Drag analysis with resolved set/mode, freestream inputs (Mach or Vinf, density, temperature), and UDP overrides.
- Produces totals, per-component, and excrescence DataFrames alongside flight-condition metadata; receipts highlight `total_cd`, per-component CSVs, and context payload details.
- Parasite drag results feed future mission sizing and drag build-up reports; ongoing validation focuses on ensuring realistic CD0 magnitudes.

## 7. Parasite Drag Status & Validation
- The analysis is implemented end-to-end (ticket, runner, payload, receipt, materializer) and integrated into the smoke workflow, but the CD0 calibration remains an open task noted in TODOs.
- Additional checks are planned for ISA overrides, component labeling, and excrescence modeling to support mission feasibility studies.

## 8. CLI & Workflows (`streamline/main.py`)
- `init` scaffolds a project directory, seeds JSON definitions, and creates an empty `.vsp3` tied to the project ID.
- `gui` launches OpenVSP in GUI mode via the session helpers, allowing manual editing within the managed environment.
- `configs`, `ops`, and `results` list available configurations, operating points, and recorded analysis receipts, respectively, pulling from catalog loaders and the results index.
- `smoke` demonstrates the deterministic pipeline: it opens the GUI, prompts the user to save geometry, resolves configuration/operating-point context, submits compute-geometry/stability/parasite-drag jobs through the manager, drains the queue, and reports artifact locations.
- A zero-to-analysis flow is: run `setup_streamline.ps1`, `python -m streamline.main init <id>`, edit geometry in the GUI, then `python -m streamline.main smoke <id> --set baseline --mach 0.15 --alpha-deg 2.0`.

## 9. Data I/O & Organization
- JSON helpers in `io/fs.py` provide consistent read/write and ensure UTF-8 encoding across project definitions.
- Results land under `<project>/results/<analysis>/<timestamp_hash>/` with `ticket.json`, `summary.json`, analysis-specific CSVs, and `run_manifest.json`; paths stored in receipts are relative to the results root for portability.
- `io/results_index.append_result_entry` maintains `<project>/results/index.json`, enabling fast CLI queries and future UI summaries.
- Ticket hashes enforce cache determinism; dependency keys (e.g., `config:<id>`, `op:<id>`, `mach:<value>`) allow targeted invalidation when design artifacts change.

## 10. Constraints & Objectives (schema baseline)
- Constraint and objective scaffolding lives in the schema to eventually express runway, weight, or mission limits alongside optimization weights.
- Hard constraints map naturally to UDP bounds or mission targets, while soft constraints/objectives will leverage OpenVSP gradients in later optimization passes.

## 11. Export Control (Simulink, Reports)
- `exports/simulink.py` is the placeholder for packaging linear model data (A/B/C/D matrices, state/control metadata) once stability receipts are aggregated.
- Planned report generation will draw from manifests and CSVs to produce PDFs summarizing mission phases, S&C metrics, drag breakdowns, and annotated figures.

## 12. Airfoils Subsystem (planned)
- Global airfoil assets live under `data/airfoils/`; per-project tuned variants will be stored within each project for versioned analysis.
- A future XFOIL loop will populate or refine these files and feed OpenVSP updates via UDPs or geometry edits.

## 13. UI (Textual) � planned shape
- The planned Textual TUI will provide panes for set/mode exploration, quick analyses, and discipline-focused views (S&C, mission, structures).
- Immediate edits initiated by users will persist instantly; tool-driven edits may be staged via `StagedEditBatch` models for review before application.
- Keyboard and pointer interactions will be supported, with the UI operating on a single project context at a time.
- `streamline/tui` now provides the session runtime (event bus, project context, background worker) so the Textual front end can listen for job, cache, and results updates without poking core orchestration.

## 14. Conventions & Standards
- SI units, explicit frame labels, and deterministic configuration application are mandatory; conversions happen at module boundaries to keep tickets/receipts unit-clean.
- Validation is embedded in Pydantic models (e.g., OperatingPoint Mach/TAS exclusivity) and reinforced by runtime guardrails in analysis runners.
- JSON and CSV artifacts remain ASCII-friendly and reproducible to ease diffing and CI storage.

## 15. Error Handling & Robustness
- Session initialization attempts multiple module import names and surfaces clear diagnostics when OpenVSP bindings are missing.
- Analyses run under `vsp_guard()` to serialize OpenVSP API access; the GUI can be temporarily locked during background runs to avoid conflicts.
- All OpenVSP inputs use `Set*AnalysisInput` with list-wrapped scalars as the API expects; if results parsing fails, CSVs still land on disk for manual inspection.
- `AnalysisManager` tracks dependencies and can prune stale cache entries when inputs are invalidated or artifacts disappear.

## 16. Developer Onboarding (quick)
- Install Anaconda, execute `.\setup_streamline.ps1` from the repo root to (re)build the `streamline` Conda environment with vendor dependencies.
- Activate the environment, initialize a project, edit geometry in OpenVSP, and use the smoke pipeline to generate stability/drag artifacts.
- Logging is configurable via CLI flags or environment variables (`STREAMLINE_LOG_LEVEL`, `STREAMLINE_LOG_FILE`).
- GitHub Actions (`.github/workflows/tests.yml`) runs `pytest` on every push/PR using the repository requirements, so new tests need to remain CLI-friendly and guard against missing OpenVSP bindings.
- To exercise the native OpenVSP API, make sure the vendor bundle is unpacked and both `PATH` and `PYTHONPATH` point at its `python/` directory (extend the CI workflow to download the official release when full fidelity is required).

## 17. Current Code: Notable Functions & Responsibilities
- `main.smoke_run` demonstrates end-to-end orchestration, dependency key assignment, and queue-driven execution for compute-geometry, stability, and parasite-drag analyses.
- `analysis/manager.AnalysisManager` encapsulates registration, submission, execution, materialization, caching, invalidation, and VSP session ownership.
- `streamline/main.py` exposes `streamline cache list|clear` via `AnalysisManager.cache_summaries` and `clear_cache`, letting operators audit or purge persisted receipts without touching code.
- `tui/session.ProjectSession` wraps `AnalysisManager` with an event-driven session model and background worker so UI layers can request jobs and observe their lifecycle asynchronously.
- `core/schema.py` defines the persistent and runtime models; `core/logging.py` and `core/errors.py` standardize logging and exception handling.
- `io/config_catalog.py` and `io/op_catalog.py` load project catalogs; `io/results_index.py` maintains the artifact ledger.
- `vsp/analyses/*` house the pure OpenVSP calls; `vsp/contracts/*` define the tickets, payloads, and receipts they consume/produce.
- `vsp/test_factory.py` offers CI-friendly helpers to generate canonical OpenVSP geometry for tests, falling back to an in-memory stub when native bindings or DLLs are unreachable.
- `vsp/run_utils.py`, `vsp/results.py`, and `vsp/util.py` hold shared helpers for JSON dumping, CSV writing, list coercion, and control group discovery.

## 18. Design Alternatives (Sets) & Configurations (Modes/Presets)
- Sets represent geometric variants; Modes bundle a set with a suite of Variable Preset settings so analyses can flip between alternatives deterministically.
- `apply_configuration` prioritizes Modes (via `UseModeFlag` and `ModeID`), but can fall back to set selection, preset activation, hinge/payload toggles, and per-parameter overrides when necessary.
- Runtime overrides allow trim loops or sensitivity studies without mutating the stored configuration JSON.

## 19. Future Additions
- Wire Textual views on top of the new `EventBus`/`ProjectSession` scaffolding to surface queue state, cache summaries, and results timelines.
- Extend cache tooling into the upcoming TUI (CLI cache listing/clearing now lives in `streamline cache`).
- Broaden analysis coverage (e.g., additional VSPAERO regimes) and integrate mission sizing routines that stack parasite drag with performance estimators.
- Harden parasite drag inputs (ISA checks, validation ranges) and implement inertia overrides in operating points.
- Introduce regression tests (unit tests for CLI commands, headless smoke runs) and CI automation (formatting, linting, minimal analysis checks).
- Extend exports (Simulink packager, nonlinear model bundles) and kick off PDF report generation once receipts stabilize.

## 20. Key Principles Summary
- Determinism: Tickets plus Mode/Set resolution ensure analyses run the intended configuration every time.
- Contracts: Typed tickets, payloads, and receipts coupled with manifests keep inputs/outputs explicit and auditable.
- Separation: Higher layers submit jobs; only materializers touch the filesystem, producing inspectable artifacts and a durable index.
- Extensibility: Adding a new analysis means introducing a ticket/payload/receipt trio and registering it with the manager; surrounding infrastructure stays unchanged.
- Transparency: Every run writes tickets, summaries, and manifests so manual inspection, debugging, and future reporting remain straightforward.

## 21. Configuration GUI Bridge & Sync Workflow (new)
- Purpose: Allow users to author Sets, Modes, and Variable Preset groups/settings inside the OpenVSP GUI, then register deterministic Streamline `Configuration` objects without hand-editing JSON.
- Introspection helpers (in `vsp/configure.py`): `list_modes`, `get_active_mode_id`, `capture_active_mode_ref`, `list_var_preset_groups`, `list_var_presets(group)`, `capture_active_var_presets`, `snapshot_current_configuration`, `build_ephemeral_configuration_dict`, `build_configuration_model`, `compute_configuration_diff`, `register_current_configuration`.
- Registration flow:
  1. User configures geometry, creates Mode + Var Preset Sets in GUI.
  2. Streamline (under VSP lock) calls `snapshot_current_configuration()` to capture active Mode, first/active Set, and active presets (best-effort).
  3. Builds a `Configuration` model via `build_configuration_model(config_id, snapshot)`.
  4. Persists JSON with `save_configuration_json` / `register_current_configuration` into `projects/<id>/configs/<config_id>.json`.
  5. Catalog reload + (future) `CatalogChanged(type='config')` event not yet wired.
- Update/diff cycle:
  - On GUI change, capture a fresh snapshot and run `compute_configuration_diff(existing_cfg, new_snapshot)`; if diffs non-empty, prompt user to (a) overwrite, (b) create versioned config (e.g. `cfg_v2`), or (c) discard changes.
  - Planned event: `ConfigurationUpdated(config_id, diff)` for UI reactive refresh & cache invalidation (`dependency key: config:<id>`).
- Validation (current + planned):
  - Existence: referenced Mode ID, preset group/setting names, and Set name must resolve; fail fast with `ConfigurationIntrospectionError`.
  - Consistency: if a Mode is active and also presets differ from Mode defaults, flag as mixed source (warn user) until explicit policy decided.
  - Uniqueness: `config_id` must not collide (unless overwrite confirmed).
  - Normalization: ensure list fields default to `[]`, dict fields to `{}`; exclude `None` on disk.
  - Future: verify hinge / control surface group / payload toggle coherence once introspection for those is added.
- Ambiguities & fallbacks:
  - Active preset detection depends on `IsVarPresetSettingActive`; if unavailable returns empty, leaving `var_presets` blank (user can manually specify).
  - If no Set is explicitly chosen, first enumerated Set is used for `geom_set_name` (documented in snapshot helper).
  - Mode usage flag: falls back to `True` if API does not expose `GetUseModeFlag`.
- Concurrency & safety:
  - All helpers invoked via wrappers acquiring the AnalysisManager's VSP lock (`register_configuration_with_lock`, `register_configuration_from_active_mode_with_lock`, `revalidate_existing_configs_with_lock`).
  - If manager not supplied, fallback to `session.vsp_guard()`; final fallback no-op (avoid hard failure in tests without OpenVSP).
- Events (current):
  - `ConfigurationCreated` emitted after successful registration (`from: mode` for mode-based capture).
  - `CatalogChanged(kind='config', config_id=...)` emitted for UI refresh triggers.
  - `ConfigurationStale` emitted when batch revalidation finds broken links.
  - TODO: Add `ConfigurationUpdated`, `ConfigurationRemoved`.
- CLI integration (new commands):
  - `streamline configs list <project>`: list stored configurations (id, set, mode id).
  - `streamline configs capture <project> <config_id> [--set NAME] [--no-validate]`:
    * Snapshots current GUI state (active Mode if any, active presets if detectable) into a new configuration.
  - `streamline configs capture-mode <project> <config_id> [--no-presets] [--udp k=v ...] [--runtime k=v ...] [--no-validate]`:
    * Forces inclusion of active Mode; optionally omits presets and applies UDP / runtime overrides (float values only).
  - Overrides parsing: `k=v` pairs converted to floats; invalid pairs raise CLI error.
- Thread-safe pattern:
  - CLI commands construct an `AnalysisManager` (ensuring lock + session) then call lock-aware register helpers.
  - Event emission occurs post-lock release to avoid holding the lock during UI notifications.
- Revalidation:
  - `revalidate_existing_configs_with_lock` returns mapping config_id -> list of errors; emits `ConfigurationStale` when any non-empty.
  - Typical UI loop: periodic revalidation of currently loaded catalog; stale configs flagged visually.
- Pending extensions (gaps):
  - Introspection for hinges, control surface groups, payload toggles (needs additional VSP queries / conventions).
  - Event emission integration (`ConfigurationUpdated` on overwrite, `ConfigurationRemoved`).
  - Configuration revisioning strategy (incremental suffix vs semantic tags) and provenance metadata (e.g., originating Mode name hash).
  - Conflict resolution policy when Mode + manual preset applications diverge (decide: allow & record both, or force a choice).
  - Bulk import helper: iterate all Modes and produce one config per Mode (optionally cross product with selected preset sets) for rapid seeding.
  - Watcher / polling loop to auto-detect GUI-side changes and propose updates in the TUI.
  - Test coverage for snapshot/diff and CLI commands with mocked VSP API.
  - Enriched diff (nested: which preset groups changed, which UDP overrides added/removed) for granular UI highlighting.
  - Error taxonomy: split `ConfigurationIntrospectionError` into granular subclasses (ModeResolutionError, etc.).
- Recommended next steps:
  1. Add hinge/payload/control-group introspection utilities.
  2. Implement `ConfigurationUpdated` event (diff payload) and integrate with invalidation.
  3. Provide bulk Mode-to-Configuration seeding command (`streamline configs seed --all-modes`).
  4. Add revisioning opt-in flag (`--version-on-diff`).
  5. Extend tests (mocked VSP) for capture + capture-mode + revalidation + stale detection.








