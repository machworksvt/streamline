# Streamline workspace bootstrapper (Windows PowerShell)
#
# * Creates/updates a Conda environment from environment.yml
# * Installs project requirements.txt
# * Installs OpenVSP via python -m tools.install_openvsp inside the environment
# * Records OPENVSP_HOME/STREAMLINE_OPENVSP_HOME as conda env vars

[CmdletBinding()]
param(
  [string]$EnvName = "streamline",
  [switch]$Force,
  [switch]$SkipPip
)

$ErrorActionPreference = "Stop"

function Write-Section($msg) { Write-Host "`n=== $msg ===`n" -ForegroundColor Cyan }
function Write-OK($msg)      { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Warning $msg }
function Fail($msg)          { Write-Error $msg; exit 1 }

function Ensure-Conda() {
  try { conda --version | Out-Null } catch { Fail "Conda not found. Install Anaconda/Miniforge and run 'conda init powershell', then restart PowerShell." }
}

function Get-CondaEnvs() {
  $jsonRaw = conda env list --json
  if ($LASTEXITCODE -ne 0 -or -not $jsonRaw) { Fail "Failed to query conda environments (JSON)." }
  return ($jsonRaw | ConvertFrom-Json).envs
}

function Env-Exists([string]$name) {
  foreach ($path in Get-CondaEnvs) {
    if ($path -match "\\\envs\\$name`$") { return $true }
  }
  return $false
}

function Remove-Env([string]$name) {
  Write-Warn "Removing env '$name'"
  conda env remove -n $name -y | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "Failed removing env '$name'." }
}

function Create-Or-Update-Env([string]$name, [switch]$force) {
  $envFile = "./environment.yml"
  if (-not (Test-Path $envFile)) { Fail "environment.yml not found at repo root." }

  if (Env-Exists $name) {
    if ($force) {
      Remove-Env $name
      Write-Section "Creating environment '$name'"
      conda env create -f $envFile -n $name | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "conda env create failed." }
    } else {
      Write-Section "Updating environment '$name'"
      conda env update -f $envFile -n $name | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "conda env update failed." }
    }
  } else {
    Write-Section "Creating environment '$name'"
    conda env create -f $envFile -n $name | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "conda env create failed." }
  }
  Write-OK "Environment ready: $name"
}

function Get-RequiredPythonVersions() {
  $metaPath = "./tools/openvsp.json"
  if (-not (Test-Path $metaPath)) { return @() }

  try {
    $meta = Get-Content $metaPath -Raw | ConvertFrom-Json
  } catch {
    Write-Warn "Unable to parse tools/openvsp.json; skipping Python version validation."
    return @()
  }

  $platform = "windows"
  if (-not $meta.platforms -or -not $meta.platforms.$platform) { return @() }

  $versions = $meta.platforms.$platform.python_versions
  if (-not $versions) { return @() }

  return @($versions)
}

function Assert-PythonVersion([string]$name) {
  $required = Get-RequiredPythonVersions
  if (-not $required -or $required.Count -eq 0) {
    Write-Warn "No OpenVSP Python version metadata found; skipping interpreter check."
    return
  }

  $expected = ($required -join ", ")
  $result = conda run -n $name python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
  if ($LASTEXITCODE -ne 0) { Fail "Failed querying Python version for environment '$name'." }

  $actual = ($result | Select-Object -First 1).Trim()
  if (-not $required.Contains($actual)) {
    $msg = "Environment '$name' is using Python $actual but OpenVSP requires Python $expected. " +
           "Recreate the environment with -Force or ensure environment.yml pins the supported version."
    Fail $msg
  }

  Write-OK "Python $actual satisfies OpenVSP requirement ($expected)."
}

function Install-PipDeps([string]$name) {
  if ($SkipPip) { Write-Warn "Skipping pip installs per -SkipPip"; return }
  if (-not (Test-Path "./requirements.txt")) { Write-Warn "requirements.txt not found (skipping)."; return }

  Write-Section "Installing Python requirements into '$name'"
  conda run -n $name python -m pip install --upgrade pip setuptools wheel | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "pip bootstrap failed." }

  conda run -n $name python -m pip install -r ./requirements.txt
  if ($LASTEXITCODE -ne 0) { Fail "pip install -r requirements.txt failed." }
  Write-OK "Project requirements installed."
}

function Install-OpenVSP([string]$name) {
  Write-Section "Installing OpenVSP runtime via Python helper"
  $exportPath = Join-Path ([System.IO.Path]::GetTempPath()) "streamline-openvsp-install.json"
  if (Test-Path $exportPath) { Remove-Item $exportPath -Force }

  conda run -n $name python -m tools.install_openvsp --export $exportPath | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "OpenVSP installer failed." }

  if (-not (Test-Path $exportPath)) { Fail "Installer did not produce export manifest." }

  $manifest = Get-Content $exportPath -Raw | ConvertFrom-Json
  Remove-Item $exportPath -Force

  if (-not $manifest.install_root) { Fail "Installer did not report an install root." }

  conda env config vars set -n $name OPENVSP_HOME=$($manifest.install_root) | Out-Null
  conda env config vars set -n $name STREAMLINE_OPENVSP_HOME=$($manifest.install_root) | Out-Null
  if ($manifest.version) {
    conda env config vars set -n $name OPENVSP_VERSION=$($manifest.version) | Out-Null
    conda env config vars set -n $name STREAMLINE_OPENVSP_VERSION=$($manifest.version) | Out-Null
  }
  Write-OK "OPENVSP_HOME=$($manifest.install_root)"

  if ($manifest.path_entries) {
    Write-Section "Add these directories to PATH if you launch the GUI or CLI tools manually"
    foreach ($entry in $manifest.path_entries) {
      Write-Host "  $entry"
    }
  }
}

function Validate-Imports([string]$name) {
  Write-Section "Validating environment"
  $code = @'
import openvsp
import pandas
print("OpenVSP:", openvsp.VSPVersion())
print("Pandas:", pandas.__version__)
'@
  $tmp = New-TemporaryFile
  Set-Content -Path $tmp -Value $code -Encoding UTF8
  conda run -n $name python $tmp
  $ec = $LASTEXITCODE
  Remove-Item $tmp -Force
  if ($ec -ne 0) { Fail "Validation failed (python exited $ec)." }
  Write-OK "Validation completed."
}

Write-Section "Streamline environment setup"
Ensure-Conda
Create-Or-Update-Env -name $EnvName -force:$Force
Assert-PythonVersion -name $EnvName
Install-PipDeps -name $EnvName
Install-OpenVSP -name $EnvName
Validate-Imports -name $EnvName
Write-Section "Done"
Write-OK "Activate with: conda activate $EnvName"
