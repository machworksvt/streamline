# Streamline Aircraft Design Workflow Vision

This document outlines a target end-to-end experience for aerospace designers using Streamline with the `AnalysisManager` orchestration pattern and OpenVSP as the primary geometry backbone. The goal is to provide a consistent mental model for how the Textual app should evolve so that the tooling accelerates concept development, detailed design, and optimization.

## 1. Concept Framing & Project Setup
- **Design brief intake:** Prompt for mission requirements (payload, range, speed, field length, noise regulations) and certification basis. Capture the rationale as project metadata.
- **Reference library access:** Surface curated catalogs of baseline missions, propulsion architectures, configurations, and technology assumptions already supported by the repository. Enable quick cloning of a reference design to seed a new project.
- **Requirement envelopes:** Provide widgets to translate high-level targets into derived constraints (wing loading, thrust-to-weight bands, cabin volume) that can be stored alongside the project definition.
- **Collaboration hooks:** Track authorship, design stage, and review notes within the project manifest so teams can coordinate edits and analysis runs.

## 2. Geometry Authoring with OpenVSP
- **Component palette:** Expose OpenVSP primitives (wings, bodies, pods, nacelles, propellers) with presets matching common aircraft categories (GA, eVTOL, MALE UAV, regional jet). Allow insertion, cloning, and hierarchy editing directly from the TUI.
- **Parametric editing:** Map OpenVSP parameters (span, sweep, twist, airfoil selections) to Streamline `EditBatch` operations so designers can adjust geometry numerically or via sliders. Provide constraint-aware editing that respects symmetry, continuity, and configuration-specific rules.
- **Visualization cues:** While the TUI is text-first, integrate quick previews (ASCII summary tables, sparkline plots) and allow launching the full OpenVSP GUI with the current project model for detailed inspection.
- **Geometry validation:** Automate checks for watertightness, component intersections, and control surface linkage completeness using existing OpenVSP diagnostics. Report issues via the notification center with actionable fixes.

## 3. Configuration & Catalog Management
- **Structured edits:** Use `StagedEditBatch` flows so users can queue multiple geometry and configuration tweaks before committing, with diffs previewed against the current catalog entries.
- **Variant tracking:** Support branching configurations (baseline, stretch, freighter) using the results index to tag receipts and artifacts, ensuring analyses stay associated with the correct variant.
- **Payload & interior planning:** Provide forms to manage cabin layouts, payload bay dimensions, and CG envelopes, leveraging existing schema modules for mass properties.

## 4. Aerodynamic Analysis Pipeline
- **Quick-look analyses:** One-click submissions for parasite drag builds, lifting-line approximations, and stability/trim sweeps using OpenVSP’s VSPAero and MassProp back-ends orchestrated by the `AnalysisManager`.
- **Job orchestration:** Display real-time job queues, worker status, and cached receipts. Allow reruns with cache invalidation when geometry changes invalidate previous results.
- **Result visualization:** Summaries for polars, stability derivatives, and control deflection requirements. Provide export options to CSV/JSON for post-processing.

## 5. Propulsion & Powertrain Integration
- **Architecture templates:** Wizards for selecting turbofan, turboprop, piston, hybrid-electric, or distributed propulsion setups. Tie into propulsion catalogs already defined in the repository.
- **Sizing loops:** Automate iteration between propulsion sizing (thrust/power curves) and mission analysis, using the `AnalysisManager` to coordinate dependencies.
- **Performance maps:** Display power lapse, SFC tables, and throttle schedules, with hooks to update mission segments.

## 6. Weights, Balance, and Structures
- **Mass estimation:** Integrate empirical weight models and OpenVSP MassProp outputs. Allow component-level overrides and sensitivity tracking.
- **CG management:** Visualize loading diagrams and ensure mission fuel burn keeps CG within limits. Provide trim margin checks tied to stability analyses.
- **Structural checks:** Connect to finite-beam approximations or external FEA hooks for wing/boom sizing, exposing placeholder adapters for future solvers.

## 7. Mission Simulation & Performance Evaluation
- **Mission builder:** Drag-and-drop (or command-driven) assembly of mission segments with climb, cruise, loiter, and reserve logic. Support branching scenarios for different payloads or environmental conditions.
- **Performance dashboards:** Present key results—payload-range diagrams, field performance, climb gradients—aggregated from cached analysis receipts.
- **Certification views:** Map results to FAR/CS compliance checklists, flagging items needing additional substantiation.

## 8. Optimization & Trade Studies
- **Design variables:** Allow tagging of OpenVSP parameters, mission settings, and propulsion knobs as optimization variables with bounds and step sizes.
- **Objective/constraint management:** Provide a catalog of common objectives (fuel burn, DOC, takeoff distance) and constraints, with the ability to assemble multi-objective studies.
- **Optimization drivers:** Start with DOE/parameter sweeps orchestrated via `AnalysisManager` ticket batches, and plan for integration with gradient-free optimizers (e.g., NLopt, pyOptSparse) as external workers.
- **Trade study tracking:** Store each optimization or sweep as a manifest entry with metadata, making it easy to revisit, compare, and export results.

## 9. User Experience & Automation Layers
- **Session dashboard:** Central hub summarizing project state, recent edits, queued analyses, and outstanding issues.
- **Guided workflows:** Task-based checklists that walk designers from requirements capture through preliminary design, ensuring critical analyses are run before major decisions.
- **Scripting hooks:** Expose a lightweight command language (or Python REPL) within the TUI for power users to script edits and analyses.
- **Notification & logging:** Channel all errors, warnings, and success messages through a consistent UI element, using `StreamlineError` metadata to provide context.

## 10. Future Integrations
- **External toolchain bridges:** Plan adapters for CFD (SU2, OpenFOAM), structural solvers, and cost models, keeping the `AnalysisManager` interface consistent.
- **Cloud/offload support:** Allow analyses to dispatch to remote workers or cloud instances, tracking provenance in the receipts.
- **Team collaboration:** Integrate version control awareness (Git hooks) and shared project repositories with permissions and review workflows.

---

This vision keeps Streamline’s existing modular patterns front and center—project manifests, catalog-driven configuration, and the `AnalysisManager` execution engine—while extending the Textual interface into a comprehensive aircraft design cockpit. It should guide prioritization of upcoming development tasks and highlight where OpenVSP’s strengths (rapid geometry changes, embedded analysis tools) can be leveraged most effectively.
