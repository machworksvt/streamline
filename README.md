# Streamline Environment Setup

Streamline can be developed on Windows, macOS, or Linux using a standard Python 3.11 toolchain. The only vendor dependency is [OpenVSP](https://openvsp.org), which Streamline now downloads on demand via a cross-platform installer.

## Environment setup at a glance

1. **Install Python packages** – `pip install -r requirements.txt` (or use `environment.yml` with Conda).
2. **Provision OpenVSP** – run `python -m tools.install_openvsp` once per machine/CI worker. The runtime is cached under `~/.cache/openvsp/<version>` by default, so repeated test runs are fast.
3. **Run the test suite** – install the real OpenVSP runtime for full coverage. A lightweight stub is used automatically when OpenVSP is unavailable; set `STREAMLINE_ALLOW_VSP_STUB=0` to require the real bindings (as CI does).

The sections below expand each step with additional context and troubleshooting tips.

## Prerequisites

* Python 3.11 (any distribution – CPython, Conda, or pyenv – is fine)
* `pip` ≥ 22
* Git (for development)

> 💡 Conda users can continue to use `environment.yml` as before; the commands below work equally well inside an activated Conda environment.

## 1. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Install the OpenVSP runtime

Run the installer module from the repository root (the command is idempotent and safe to re-run):

```bash
python -m tools.install_openvsp
```

The installer will:

* Read `tools/openvsp.json` to select the correct OpenVSP archive for your OS.
* Download and unpack the runtime into `${STREAMLINE_OPENVSP_HOME:-~/.cache/openvsp}`.
* Drop an `openvsp-runtime.pth` file into the active environment so `import openvsp` works without tweaking `PYTHONPATH`.
* Cache the extracted payload, so subsequent executions reuse the existing runtime unless you pass `--force`.

On success it prints the installation path and any directories that should be added to your `PATH`/`LD_LIBRARY_PATH`. In CI you can capture this information with `--print-json`:

```bash
python -m tools.install_openvsp --print-json
```

### Optional flags

* `--platform {windows,linux,macos}` – override auto-detected platform.
* `--cache-root <path>` – install somewhere other than the default cache.
* `--force` – re-download even if the requested version already exists.
* `--no-pth` – skip writing the `.pth` helper (useful inside read-only environments).
* `--export <path>` – save the installation manifest as JSON for automation.

## 3. Configure environment variables (if needed)

The Python bindings usually work out-of-the-box once the `.pth` file is present. If you need to run the OpenVSP GUI or downstream tooling, add the reported directories to your `PATH` (Windows) or `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` (Linux/macOS). The installer output includes everything you need. In GitHub Actions we export the values that `--print-json` returns, so the workflow matches the local developer experience.

## 4. Running tests

By default the test suite falls back to an in-memory stub if the OpenVSP runtime is unavailable. To require the real bindings (matching CI), opt-in explicitly:

```bash
export STREAMLINE_ALLOW_VSP_STUB=0  # or set in PowerShell/Command Prompt
pytest
```

When the variable is **not** set, tests skip OpenVSP-dependent cases if the runtime is missing.

## Legacy PowerShell bootstrapper

Windows developers who prefer the existing PowerShell workflow can still run:

```powershell
./setup_streamline.ps1
```

The script now delegates the OpenVSP download to `python -m tools.install_openvsp`, then provisions the Conda environment as before. See the script for additional switches such as `-Force`.
