# Streamline Environment Setup

Streamline can be developed on Windows, macOS, or Linux using a standard Python 3.11 toolchain. The only vendor dependency is [OpenVSP](https://openvsp.org); you install it manually using the bindings that ship with the official download.

## Environment setup at a glance

1. **Install Python packages** – `pip install -r requirements.txt` (or use `environment.yml` with Conda).
2. **Provision OpenVSP** – download the official OpenVSP package for your platform, extract it adjacent to this repository, and run the upstream helper (see below).
3. **Run the test suite** – full coverage requires the real OpenVSP bindings. When the runtime is missing the test suite falls back to a stub unless you set `STREAMLINE_REQUIRE_REAL_VSP=1`.

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

1. Download the platform archive from the [OpenVSP downloads page](https://openvsp.org/download.php).
2. Extract it next to this repository so you have a folder such as `OpenVSP-3.46.0-win64/`.
3. Run the helper inside the package to install the Python bindings. On Windows that is:

   ```powershell
   cd OpenVSP-3.46.0-win64/python
   ./setup.ps1
   ```

   On Linux/macOS use the provided shell script:

   ```bash
   cd OpenVSP-3.46.0-linux/python
   ./setup.sh
   ```

4. Activate your Streamline environment and verify the bindings:

   ```powershell
   conda activate streamline
   python -c "import openvsp; print(openvsp.GetVSPVersion())"
   ```

If you keep the extracted directory beside the repository (the same parent folder) and run the upstream setup script inside your active environment, `import openvsp` should work without additional path tweaks.

## 3. Running tests

By default the test suite falls back to an in-memory stub if the OpenVSP runtime is unavailable. To require the real bindings (matching CI), opt-in explicitly:

```bash
export STREAMLINE_ALLOW_VSP_STUB=0  # or set in PowerShell/Command Prompt
pytest
```

When the variable is **not** set, tests skip OpenVSP-dependent cases if the runtime is missing.

## PowerShell convenience script

Windows developers can run:

```powershell
./setup_streamline.ps1
```

The script creates or updates the Conda environment, installs the Python requirements, downloads the Windows OpenVSP package, extracts it beside the repository, and runs `pip install -r requirements-dev.txt` inside the package’s `python/` directory.
