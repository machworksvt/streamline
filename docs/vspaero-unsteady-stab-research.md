# VSPAERO unsteady-stab (-qstab) defect — public-record research

Researched 2026-08-17. Scope: OpenVSP GitHub issues, OpenVSP Google Group, release notes/CHANGELOG, workshop materials, validation literature, community tools. Context defect: OpenVSP 3.51.2 / bundled VSPAERO ~7.x unsteady stability modes give wrong-phased response for surfaces at a lever arm from the rotation center (tailed Cm_q+ad weakens instead of strengthening; V-tail aircraft pitch damping positive; -pstab all-NaN for VLM).

## Q1 — Is the lever-arm/tailed-config unsteady-stab defect known publicly?

**GitHub issues: null.** GitHub search API over `repo:OpenVSP/OpenVSP` (issue titles+bodies, checked 2026-08-17) returns **zero** issues for every term tried: `qstab`, `pstab`, `rstab`, `Cmq`, `pitch damping`, `dynamic derivatives`, `damping derivatives`, `unsteady stability`, `stability derivatives`, `stab NaN`. https://github.com/OpenVSP/OpenVSP/issues (caveat: API does not index comments; still a strong null).

**Google Group: adjacent symptoms reported, defect itself not.** Closest hits:

- **[PQR Analysis thread](https://groups.google.com/g/openvsp/c/QcTDBufqOoM), last message Jul 17, 2026 (Minh Nguyen Ngoc), unanswered** — reports the current (new-solver) qstab behavior, extracted from raw thread HTML:
  > "The TimeStep and the Number of Time step input in vspaero does not considered by the solver at all. And the unsteady solver always run 128 timestep everytime. My wake solution got messed up quickly, and result of CL(a_dot + CLq) gave a ridiculous number." ... "for a good wake solution, my designs needed at least timestep smaller than 0.005. Is this a limitation of the Q_analysis mode...?"
  Confirms hardcoded 128 steps, ignored time-step inputs, and implausible combined derivatives in the wild — but no diagnosis, no tail/lever-arm framing, no developer reply as of today.
- **[Irregularities in the Dynamic derivatives when wing trailing wakes hit the tail](https://groups.google.com/g/openvsp/c/mHty4QKTGS8)** (Ashley M, Oct–Nov 2022, old solver v6, versions 3.26–3.30): tail moment contribution causing irregular CMx_p/CMy_q/CMz_r; devs (Litherland, McDonald) attributed it to mesh/wake impingement; partially persisted (CMz_r); absent in 3.21.1. Wake-impingement-specific, not the systematic weakening.
- **[Using VSPAero to build a full FDM](https://forum.flightgear.org/viewtopic.php?f=49&t=30832)** (FlightGear forum, Richard, Nov 26, 2016, old solver): "pitch moment due to pitch (CMMQ) had the wrong sign" among derivatives that made the FDM uncontrollable. Old, steady-mode era, but a prior public wrong-sign pitch-damping report.
- **[Stability Analysis of Cessna 182](https://groups.google.com/g/openvsp/c/1FaKNpfhv3s)** (Michael Stalls, May 2019): "The values for CLq output by VSPAERO differ quite a bit from those calculated in the reference" (Smetana handbook), full config with tail, steady mode, v6.
- **[stability analysis](https://groups.google.com/g/openvsp/c/s8VlU3P0jWY)** (Kun Drew, Aug 2024): questions on qstab/rstab combined terms; McDonald: "We left them as a combined term... if you need them as separate terms, just subtract." No accuracy discussion.

Nobody publicly describes the specific signature: tail present → combined Cm_(q+alpha_dot) *weakens* vs wing-alone, or positive pitch damping on a V-tail aircraft, or the missing/mis-phased omega-x-r rotary term at distant surfaces. No public report of -pstab all-NaN either.

**Verdict — known upstream: no.** Symptoms (hardcoded steps, ignored settings, "ridiculous" q+alpha_dot numbers) publicly reported Jul 17, 2026 and unanswered; the lever-arm mechanism and tailed-config quantification are not on the public record.

## Q2 — Do newer releases change the unsteady stab analyses?

- **3.51.2 (2026-07-26) is the newest release.** Confirmed in both [CHANGELOG.md](https://raw.githubusercontent.com/OpenVSP/OpenVSP/main/CHANGELOG.md) and [openvsp.org announcements](https://openvsp.org/blogs/announcements) (3.51.2 → Jul 26 2026; 3.51.1 → Jul 18; 3.51.0 → Jun 29; 3.50.x → May–Jun 2026). No 3.52/3.53 exists as of 2026-08-17. The measured version IS the latest.
- **The VSPAERO rewrite already shipped**: the Kinney "new solver" (v7: NGon meshes, thick/thin per component, hand-coded adjoint) landed in [OpenVSP 3.45.0, Jul 19, 2025](https://openvsp.org/blogs/announcements/2025/07/19/openvsp-3-45-0-released) ("~18 months of VSPAERO development"). 3.51.2 bundles it — the defect is in the rewrite, not something the rewrite will fix.
- **No stab-mode work advertised anywhere.** Full-changelog term search (all versions through 3.51.2): zero hits for unsteady stability / qstab / pstab / rstab / pitch damping / dynamic derivatives / PQR / STABILITY_Q. Release notes 3.45→3.51.2 cover adjoint, meshing, speedups ("re-audit everything", 3.51.2) — nothing on stability modes.
- **[2025 Workshop VSPAERO slides](https://openvsp.org/wiki/lib/exe/fetch.php?media=workshop25:2025_openvsp_workshop_vspaero.pdf)** (Kinney; [agenda](https://openvsp.org/wiki/doku.php?id=workshop2025)): adjoint/design-derivative content only; "derivatives" means hand-coded design gradients. No stability-analysis roadmap item. Minh's Jul 2026 post concurs: "no new update significantly on customization of VSPAERO PQR analysis on recent workshops."

**Verdict — fixed in version X: no.** No newer version exists (latest = 3.51.2, the version tested), and no release 3.45→3.51.2 mentions the unsteady stability modes at all.

## Q3 — Published validation of VSPAERO dynamic derivatives

- **[Mariën, "Software Testing: VSPAERO", HAW Hamburg master thesis, 2021](https://www.fzt.haw-hamburg.de/pers/Scholz/arbeiten/TextMarien.pdf)** (DOI 10.15488/11559): full-text checked — steady lift/drag/moment validation vs handbook/DATCOM only; "stability" appears twice, no dynamic derivatives, no pstab/qstab/rstab testing.
- **["Validation of VSPAERO for Basic Wing Simulation" (RIMNI, 2024)](https://cdn.techscience.cn/files/rimni/2024/online/RIMNI1012/TSP_RIMNI_56492/TSP_RIMNI_56492.pdf)** (+ [scripts repo](https://github.com/JARC99/vspaero-validation-studies)): steady wing polars vs DATCOM. No dynamic derivatives.
- **[F-15 stability thread](https://groups.google.com/g/openvsp/c/7XIR3hbx7cc)** (Feb 2025): gross static-derivative discrepancies traced toward reference-quantity/model errors; damping derivatives listed from reference but not evaluated against VSPAERO.
- **No AIAA paper, thesis, or slide deck found that validates VSPAERO *unsteady* damping derivatives (Cmq/Cnr/Clp) against wind tunnel, DATCOM, AVL, or flight test.** Searches across AIAA/NTRS/theses returned CFD forced-oscillation literature but nothing VSPAERO-specific. **Null result** — the -p/q/rstab modes appear publicly unvalidated.
- Community tools:
  - **[StabVSP (Kai2510)](https://github.com/Kai2510/StabVSP)** — postprocesses .stab/.p/q/rstab into eigenvalues; README itself hedges: on splitting alpha_dot terms "the validity remains to be checked. This way may be wrong", recommends keeping combined (q+alpha_dot) terms in the EOM, and warns OpenVSP "3.45.x's result may differ since the solver has been modified a lot."
  - **[vsptools (Rudolf339)](https://github.com/Rudolf339/vsptools)** — builds JSBSim FDMs from VSPAERO `.history` sweeps (steady), sidestepping the stab files; README states no motive. FlightGear-community practice (thread above) has been to hand-tune damping after VSPAERO sign/magnitude problems.

**Verdict — published validation of the unsteady modes: none found** (explicit null). Adjacent evidence: 2019 CLq/Cmq handbook disagreement (steady, v6), 2016 wrong-sign CMMQ, 2022 tail-wake irregularities, StabVSP's own validity hedge.

## Q4 — Hardcoded -qstab parameters documented anywhere?

- Old solver (v6) numbers were stated by Rob McDonald in the [PQR thread](https://groups.google.com/g/openvsp/c/QcTDBufqOoM) (2018/2020): "executing a full period sine oscillation of 1deg amplitude". Note this differs from the 7.x source values measured today (5 deg, N=128, omega=4*pi/(N*dt)) — amplitude apparently changed in the rewrite, undocumented.
- Current solver: the only public documentation of the hardcoding is user-observed — Minh Nguyen Ngoc, Jul 17, 2026 (same thread): always 128 timesteps, TimeStep/NumTimeSteps inputs "not considered by the solver at all". Matches the -qstab source reading exactly.
- Official docs are silent: the [VSPAERO tutorial wiki](https://openvsp.org/wiki/doku.php?id=vspaerotutorial) names the P/Q/R modes but documents no amplitude/steps/frequency and no way to set them; no release note ever exposed them.

**Verdict — parameters exposed in newer versions: no; documented officially: no** (only the 2018 forum description, now stale).

## Recommended action

1. File the defect upstream — nothing on record covers it. Best venue per project practice: OpenVSP Google Group post + GitHub issue, with the minimal repro pair (AR-8 wing alone Cm_q+ad ≈ -2.84 matching theory vs wing+tail ≈ -1.95 where tail-volume physics gives ≈ -11) and the V-tail positive-damping case; cite the unanswered Jul 17, 2026 PQR-thread post as corroboration (hardcoded 128 steps, ignored dt, implausible q+alpha_dot).
2. Until acknowledged/fixed: do not use 7.x -p/q/rstab outputs for any configuration with surfaces at a lever arm; the steady-mode rate columns are separately broken, so get damping derivatives from prescribed-motion unsteady runs with independent extraction, or from AVL/DATCOM.
3. Watch: https://github.com/OpenVSP/OpenVSP/issues and the PQR thread for developer response; next release after 3.51.2.

## Executive summary

1. The tailed-configuration/lever-arm unsteady-stab defect is **not publicly known**: zero matching GitHub issues, no Google Group thread describing it; closest is an **unanswered Jul 17, 2026 post** reporting hardcoded 128 steps, ignored time-step settings, and "ridiculous" CL(a_dot+q) from the same modes.
2. **No fix exists**: 3.51.2 (2026-07-26) is the newest release; the VSPAERO rewrite already landed in 3.45.0 (Jul 2025) and *is* the defective solver; no release note 3.45→3.51.2 touches the stability modes.
3. **No published validation** of VSPAERO's unsteady damping derivatives exists; existing validations (Mariën 2021, RIMNI 2024) are steady-only, and prior forum/handbook comparisons (2016, 2019, 2022) already flagged wrong-sign/off-magnitude rate derivatives on tailed configs.
4. The hardcoded parameters are **undocumented**; the old solver advertised 1 deg amplitude (2018 forum), the 7.x code uses 5 deg/128 steps, and users confirm inputs are ignored.
5. Action: report upstream with the wing-vs-wing+tail repro; meanwhile treat all 7.x -p/q/rstab damping derivatives on multi-surface configs as untrustworthy.


---

## Appendix — upstream issue draft (NOT filed; review before posting)

Venue per report: OpenVSP Google Group post first, GitHub issue second, cross-referencing.

> **Title:** VSPAERO -qstab: pitch-damping response of surfaces at a lever arm is wrong-phased
> (tail *weakens* Cm_q+alpha_dot; positive pitch damping on a tailed aircraft)
>
> **Environment:** OpenVSP 3.51.2 official Ubuntu 24.04 build, Linux x86-64, bundled VSPAERO
> (new solver), pure-VLM thin sets, `UnsteadyType = STABILITY_Q_ANALYSIS` via the Python API.
>
> **Repro (two runs, same settings):**
> 1. Rectangular wing, span 2.0 m, chord 0.25 m (AR 8), moment reference at root quarter-chord.
>    `-qstab` combined derivative: **Cm_(q+adot) = -2.84** — matches thin-wing theory
>    (-(pi/2+pi/2) with 3-D knockdown). Good.
> 2. Same wing + rectangular horizontal tail (span 0.8 m, chord 0.15 m, LE 0.65 m aft — arm
>    ~2.6 chords). Classical tail-volume physics adds ≈ -8, expected total ≈ -11.
>    Measured: **Cm_(q+adot) = -1.95** — the tail made pitch damping WEAKER.
> On a real V-tail aircraft this produces **positive** published pitch damping (+1.05) alongside
> a plausible CZ_(q+adot) (-4.6).
>
> **What we ruled out:** an independent least-squares re-extraction (basis 1, t, sin wt, cos wt)
> from the raw `model.history` time series reproduces the published numbers exactly, so the
> Fourier projection in `vspaero.C` is consistent with the time histories — the rendered
> *response* of surfaces distant from the rotation origin appears to be missing / mis-phasing
> the rotary (omega x r) contribution, leaving alpha-dot/lift-deficiency physics only. Wake and
> convergence settings are not the cause: results at WakeIters/NumWakeNodes 3/16, 5/16 and 5/64
> agree to 4 decimals — consistent with the `-qstab` branch of `vspaero.C` hardcoding
> N=128, theta_max=5 deg, WakeIterations=25, wake nodes 32 (API values never reach the solver).
>
> **Corroboration:** unanswered Jul 17, 2026 post in the PQR Analysis thread
> (https://groups.google.com/g/openvsp/c/QcTDBufqOoM) independently reports the hardcoded 128
> steps, ignored TimeStep/NumTimeSteps, and "ridiculous" CL(a_dot+q) numbers.
>
> Repro scripts (OpenVSP Python API, ~40 lines) available on request.
