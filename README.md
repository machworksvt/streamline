# streamline

The AeroDB producer for the Icarus chain. It turns a versioned OpenVSP geometry into
contract-validated aerodynamic data (`aerodb.json`), mass properties (`massprops.json`) and a static
engine deck (`engine_deck.json`), plus the report a reviewer reads — and releases them, CI-only, to
`icarus-aerodb`, which `icarus-dynamics` pins by hash. Master Plan §8.

```
projects/icarus/geometry/icarus-A.vsp3 ──┐
projects/icarus/campaign/canonical.json ─┼─▶ streamline campaign run ─▶ raw rows ─▶ assemble ─▶ aerodb.json + siblings
projects/icarus/massprops/ledger.json ───┤                                             │  lint · signs · contract
projects/icarus/engine/bench_static.csv ─┘                                             ▼
                                                                                report.pdf · MANIFEST.json ─▶ icarus-aerodb/<id>/
```

## Environment

One environment, pinned: `flake.nix` ships OpenVSP **3.51.2** (the official Ubuntu 24.04 build,
wrapped in `nix/openvsp.nix`), Python 3.12, numpy, matplotlib, pytest. Nothing is installed by
hand; there is no conda path and no Windows path.

```bash
nix develop
```

That shell has `python` with `import openvsp` working, `vsp`/`vspaero`/`vspscript` on `PATH`, and
`make`. `streamline version` prints the pin status; canonical runs refuse an unpinned OpenVSP.

The GUI is a design-time convenience: `streamline gui projects/icarus/geometry/icarus-A.vsp3`
(under WSL, WSLg provides the display; try `LIBGL_ALWAYS_SOFTWARE=1` if GL misbehaves).

## Layout

| path | what |
|---|---|
| `src/streamline/` | the package — `vsp/` (session + geometry substrate), `analyses/`, `backends/`, `campaign/`, `export/`, `report/`, `cli.py` |
| `contract/aerodb_contract/` | **the AeroDB contract** — dependency-free (stdlib + numpy): schema-as-code, `conventions.md`, validator, loader, physics lint, sign fixtures, completeness checklist, generated `spec.md`. `icarus-dynamics` pins this. |
| `projects/icarus/` | the aircraft: `geometry/` (`.vsp3`, versioned by revision letter), `campaign/`, `massprops/`, `engine/`, `golden/reference/` |
| `nix/openvsp.nix` | the OpenVSP pin |
| `legacy/` | the pre-2026-08 workbench, frozen (see `legacy/README.md`) |
| `tests/` | the suite; real-VSP tests are the CI default and never skip for green-ness |

## Make targets

`make check` (contract + unit + real-VSP smoke) · `make test` (everything incl. slow solves) ·
`make golden` · `make determinism` · `make campaign` · `make report` · `make spec` — the last five
arrive with their phases and fail loudly until then.

## Rules that are contracts here

* Body **FRD**, SI, radians, trailing-edge-down positive — `contract/aerodb_contract/conventions.md`
  is locked with the schema, and the sign fixtures in it are asserted at export and at ingest.
* No implicit solver defaults: a run refuses unless the campaign names a value for every analysis
  input OpenVSP exposes, and the resolved set is written into the artifact.
* No wallclock, hostname or path inside a hashed artifact; timestamps live in `BUILD.json`.
* No laptop-produced AeroDB is ever released — `release publish` checks it is running in CI.
