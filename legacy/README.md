# legacy/ — the first streamline, frozen

This is the pre-2026-08-16 package, moved here verbatim (decision D1, Master Plan §8.1: frozen, not
deleted). Nothing in the repository imports it; it is excluded from packaging, tests and CI.

What it was: an OpenVSP/VSPAERO design workbench — AnalysisManager queue + cache, Pydantic
tickets/receipts, a Textual TUI, a GUI↔configuration bridge, mission/powerplant schemas. `CONTEXT.md`
is its design document and reads as intent, not as a description of what ran: at the freeze every
CLI path raised, the stability materializer failed after every real solve, and no aero database
existed. The audit is in the plan that replaced it.

What was carried forward, as ideas rather than code: tickets hashed as canonical JSON, a manifest per
run, a results ledger, and the VSPAERO result-key knowledge in `streamline/vsp/analyses/stability.py`
and `parasite_drag.py`.

Do not fix things here. If something in this tree turns out to be needed, port it into `src/streamline/`
under the current contracts and tests.
