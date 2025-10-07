# setup_streamline.ps1
# Streamline workspace bootstrapper (Windows, no Docker)
# - Uses OpenVSP's python\environment.yml and requirements-dev.txt directly
# - Creates/updates target env (default 'streamline') WITHOUT running vendor setup.ps1
# - Installs project requirements.txt (optional)
# - Sets env vars (STREAMLINE_DATA, STREAMLINE_PROJECTS, OPENVSP_HOME)
# - Validates vsp/pandas imports

[CmdletBinding()]
param(
  [string]$OpenVSPDir = "",
  [string]$EnvName    = "streamline",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Section($msg) { Write-Host "`n=== $msg ===`n" -ForegroundColor Cyan }
function Write-OK($msg)      { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Warning $msg }
function Fail($msg)          { Write-Error $msg; exit 1 }

function Test-Conda() {
  try { conda --version | Out-Null } catch { Fail "Conda not found. Install Anaconda/Miniforge and run 'conda init powershell', then restart PowerShell." }
}

function Env-Map() {
  $jsonRaw = conda env list --json
  if ($LASTEXITCODE -ne 0 -or -not $jsonRaw) { Fail "Failed to query conda environments (JSON)." }
  $json = $jsonRaw | ConvertFrom-Json
  $map = @{}
  foreach ($p in $json.envs) {
    if ($p -match '\\envs\\([^\\]+)$') { $name = $Matches[1] } else { $name = "base" }
    $map[$name] = $p
  }
  return $map
}
function Test-CondaEnvExistence([string]$name) { (Env-Map).ContainsKey($name) }

function Deactivate-IfActive([string]$name) {
  $current = $env:CONDA_DEFAULT_ENV
  if ($current -eq $name) {
    Write-Warn "Environment '$name' is currently active in this shell. Deactivating..."
    conda deactivate
    if ($LASTEXITCODE -ne 0) { Fail "Could not deactivate current environment. Open a new PowerShell window and rerun." }
  }
}

function Confirm-YesNo($prompt) { (Read-Host "$prompt (y/n)") -match '^(y|Y)$' }

function Find-OpenVSPFolder() {
  if ($OpenVSPDir -and (Test-Path $OpenVSPDir)) { return (Resolve-Path $OpenVSPDir).Path }
  $candidates = @(
    ".\OpenVSP-3.42.3-win64",
    ".\OpenVSP-3.42.3",
    ".\v3.42.3",
    ".\OpenVSP",
    ".\openvsp"
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return (Resolve-Path $c).Path } }
  Fail "Could not find your OpenVSP 3.42.3 folder. Pass: -OpenVSPDir C:\path\to\OpenVSP-3.42.3-win64"
}

function Get-VSPPythonFiles([string]$vspHome) {
  $pyDir = Join-Path $vspHome "python"
  $envYml = Join-Path $pyDir "environment.yml"
  $reqTxt = Join-Path $pyDir "requirements-dev.txt"
  if (-not (Test-Path $envYml)) { Fail "Missing: $envYml" }
  if (-not (Test-Path $reqTxt)) { Fail "Missing: $reqTxt" }
  return @{ PyDir = $pyDir; EnvYml = $envYml; ReqTxt = $reqTxt }
}

function Ensure-Folders() {
  foreach ($p in @(".\data",".\projects")) {
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
  }
}

function Create-Or-Update-Env([string]$envName, [string]$envYmlPath, [switch]$force) {
  Write-Section "Preparing conda env '$envName' from environment.yml"
  if (Test-CondaEnvExistence $envName) {
    if ($force) {
      Deactivate-IfActive $envName
      Write-Warn "Env '$envName' exists and -Force specified. Removing..."
      conda env remove -n $envName -y | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "Failed removing env '$envName'." }
      Write-OK "Removed '$envName'."
      Write-Host "Creating '$envName' from environment.yml (override name)..."
      conda env create -f "$envYmlPath" -n $envName | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "conda env create failed." }
      Write-OK "Created '$envName' from environment.yml."
    } else {
      if (Confirm-YesNo "Env '$envName' exists. Update it from environment.yml?") {
        Write-Host "Updating '$envName' from environment.yml..."
        conda env update -f "$envYmlPath" -n $envName | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "conda env update failed." }
        Write-OK "Updated '$envName'."
      } else {
        Write-OK "Keeping existing '$envName' unchanged."
      }
    }
  } else {
    Write-Host "Creating '$envName' from environment.yml (override name)..."
    conda env create -f "$envYmlPath" -n $envName | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "conda env create failed." }
    Write-OK "Created '$envName' from environment.yml."
  }
}

function Install-VSPRequirements([string]$envName, [string]$reqTxtPath) {
    Write-Section "Installing OpenVSP Python requirements into '$envName'"
  
    $reqDir = Split-Path -Parent $reqTxtPath
  
    # Run pip exactly like the vendor script does: from the python/ folder.
    Push-Location $reqDir
    try {
      conda run -n $envName python -m pip install -U pip setuptools wheel | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "pip bootstrap failed." }
  
      # Important: use the relative path here so '-e utilities' resolves correctly.
      conda run -n $envName python -m pip install -r .\requirements-dev.txt
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r requirements-dev.txt failed." }
    }
    finally {
      Pop-Location
    }
  
    Write-OK "OpenVSP requirements installed."
  }
function Install-ProjectRequirements([string]$envName) {
  if (Test-Path ".\requirements.txt") {
    Write-Section "Installing project requirements.txt into '$envName'"
    conda run -n $envName python -m pip install -r .\requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "project requirements install failed." }
    Write-OK "Project requirements installed."
  } else {
    Write-Warn "requirements.txt not found at repo root (skipping)."
  }
}

function Set-EnvVars([string]$envName, [string]$vspHome) {
  Write-Section "Setting per-env vars"
  Ensure-Folders
  $dataPath     = (Resolve-Path ".\data").Path
  $projectsPath = (Resolve-Path ".\projects").Path

  conda env config vars set -n $envName STREAMLINE_DATA="$dataPath"         | Out-Null
  conda env config vars set -n $envName STREAMLINE_PROJECTS="$projectsPath" | Out-Null
  conda env config vars set -n $envName OPENVSP_HOME="$vspHome"             | Out-Null

  Write-OK "STREAMLINE_DATA=$dataPath"
  Write-OK "STREAMLINE_PROJECTS=$projectsPath"
  Write-OK "OPENVSP_HOME=$vspHome"
}

function Validate-Imports([string]$envName) {
  Write-Section "Validating environment"
  $code = @'
import sys
print("Python:", sys.version)
try:
    import openvsp as vsp
    print("vsp import: OK")
except Exception as e:
    print("vsp import: FAILED ->", e)
    raise
try:
    import pandas as pd
    print("pandas:", pd.__version__)
except Exception as e:
    print("pandas import: FAILED ->", e)
    raise
'@
  $tmp = New-TemporaryFile
  Set-Content -Path $tmp -Value $code -Encoding UTF8
  conda run -n $envName python $tmp
  $ec = $LASTEXITCODE
  Remove-Item $tmp -Force
  if ($ec -ne 0) { Fail "Validation failed (python exited $ec)." }
  Write-OK "Validation completed."
}

# ---------------- Main ----------------
Write-Section "Streamline environment setup"
Test-Conda

# download OpenVSP 3.46.0 from link
# link is: https://openvsp.org/download.php?file=zips/current/windows/OpenVSP-3.46.0-win64-Python3.11.zip

# download and unzip to current folder
Write-Section "Downloading and extracting OpenVSP 3.46.0"

# Define the download URL and target zip file
$vspUrl = "https://openvsp.org/download.php?file=zips/current/windows/OpenVSP-3.46.0-win64-Python3.11.zip"
$zipFile = ".\OpenVSP-3.46.0-win64-Python3.11.zip"

# Download the file
Write-Host "Downloading OpenVSP from $vspUrl..."
Invoke-WebRequest -Uri $vspUrl -OutFile $zipFile
if ($LASTEXITCODE -ne 0) { Fail "Failed to download OpenVSP." }
Write-OK "Downloaded OpenVSP to $zipFile."

# Unzip the file
Write-Host "Extracting $zipFile..."
Expand-Archive -Path $zipFile -DestinationPath "." -Force
if ($LASTEXITCODE -ne 0) { Fail "Failed to extract OpenVSP." }
Write-OK "Extracted OpenVSP."

# Clean up the zip file
Remove-Item $zipFile -Force
Write-OK "Removed $zipFile."

$vspHome = Find-OpenVSPFolder
Write-OK "Found OpenVSP at: $vspHome"

$files = Get-VSPPythonFiles -vspHome $vspHome
$pyDir   = $files.PyDir
$envYml  = $files.EnvYml
$reqTxt  = $files.ReqTxt

Write-Host "Using:" 
Write-Host "  environment.yml      = $envYml"
Write-Host "  requirements-dev.txt = $reqTxt"

Create-Or-Update-Env -envName $EnvName -envYmlPath $envYml -force:$Force
Install-VSPRequirements -envName $EnvName -reqTxtPath $reqTxt
Install-ProjectRequirements -envName $EnvName
Set-EnvVars -envName $EnvName -vspHome $vspHome
Validate-Imports -envName $EnvName

Write-Section "Done"
Write-Host "Activate with:  conda activate $EnvName" -ForegroundColor Yellow