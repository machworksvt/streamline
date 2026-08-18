# Streamline workspace bootstrapper (Windows PowerShell)
#
# * Creates/updates a Conda environment from environment.yml
# * Installs project requirements.txt (optional)
# * Leaves OpenVSP installation to the user (see README)

[CmdletBinding()]
param(
  [string]$EnvName = "streamline",
  [switch]$Force,
  [switch]$SkipPip,
  [switch]$AllowUpdate
)

$ErrorActionPreference = "Stop"

function Write-Section($msg) { Write-Host "`n=== $msg ===`n" -ForegroundColor Cyan }
function Write-OK($msg)      { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Warning $msg }
function Fail($msg)          { Write-Error $msg; exit 1 }

function Ensure-Conda() {
  try { conda --version | Out-Null } catch { Fail "Conda not found. Install Anaconda/Miniforge and run 'conda init powershell', then restart PowerShell." }
}

function Env-Exists([string]$name) {
  try {
    $jsonRaw = conda env list --json 2>$null
    if (-not $jsonRaw) { return $false }
    $envPaths = ($jsonRaw | ConvertFrom-Json).envs
    foreach ($p in $envPaths) {
      if ([IO.Path]::GetFileName($p) -ieq $name) { return $true }
    }
    return $false
  } catch {
    $table = conda env list 2>$null
    if ($table) {
      return ($table -match "^\s*\S*\\envs\\$name(\s|$)") -or ($table -match "^\s*$name\s")
    }
    return $false
  }
}

function Deactivate-EnvIfActive([string]$name) {
  while ($env:CONDA_DEFAULT_ENV -eq $name) {
    Write-Section "Deactivating active environment '$name'"
    conda deactivate | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warn "conda deactivate returned non-zero; continuing."; break }
  }
}

function Remove-Env([string]$name) {
  Write-Warn "Removing env '$name'"
  conda env remove -n $name -y | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "Failed removing env '$name'." }
}

function Create-Or-Update-Env([string]$name, [switch]$force, [switch]$allowUpdate) {
  if ($force -and $allowUpdate) {
    Fail "Specify only one of -Force or -AllowUpdate."
  }

  $envFile = "./environment.yml"
  if (-not (Test-Path $envFile)) { Fail "environment.yml not found at repo root." }

  $exists = Env-Exists $name

  if ($exists) {
    if ($force) {
      Deactivate-EnvIfActive $name
      Write-Warn "Environment '$name' exists; removing due to -Force."
      Remove-Env $name
      $exists = $false
    } elseif ($allowUpdate) {
      Write-Section "Updating environment '$name'"
      conda env update -f $envFile -n $name | Out-Null
      if ($LASTEXITCODE -ne 0) { Fail "conda env update failed." }
      Write-OK "Environment updated: $name"
      return
    } else {
      Fail ("Environment '{0}' already exists. Use -Force to recreate or -AllowUpdate to update, or remove manually:`n  conda env remove -n {0}" -f $name)
    }
  }

  if (-not $exists) {
    Write-Section "Creating environment '$name'"
    conda env create -f $envFile -n $name | Out-Null
    if ($LASTEXITCODE -ne 0) {
      if (Env-Exists $name) {
        Fail "conda env create reported failure but the prefix now exists. Try: conda env remove -n $name -y; then re-run with -Force."
      }
      Fail "conda env create failed."
    }
  }

  Write-OK "Environment ready: $name"
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

Write-Section "Streamline environment setup"
Ensure-Conda
Create-Or-Update-Env -name $EnvName -force:$Force -allowUpdate:$AllowUpdate
Install-PipDeps -name $EnvName
Write-Section "Fetching OpenVSP package"

$repoRoot = Resolve-Path "."
$vspFolderName = "OpenVSP-3.46.0-win64"
$vspZipName = "$vspFolderName.zip"
$vspUrl = "https://openvsp.org/download.php?file=zips/current/windows/OpenVSP-3.46.0-win64-Python3.11.zip"
$vspZipPath = Join-Path $repoRoot $vspZipName
$vspExtractPath = Join-Path $repoRoot $vspFolderName

if (Test-Path $vspExtractPath) {
  Write-Warn "Existing $vspFolderName directory found; removing before re-install."
  Remove-Item -Recurse -Force $vspExtractPath
}

if (Test-Path $vspZipPath) {
  Remove-Item -Force $vspZipPath
}

Write-Section "Downloading OpenVSP ($vspFolderName)"
try {
  Invoke-WebRequest -Uri $vspUrl -OutFile $vspZipPath -UseBasicParsing
} catch {
  Fail "Failed to download OpenVSP archive: $($_.Exception.Message)"
}
Write-OK "Downloaded archive to $vspZipName"

Write-Section "Extracting OpenVSP archive"
try {
  Expand-Archive -Path $vspZipPath -DestinationPath $repoRoot -Force
} catch {
  Fail "Failed to extract OpenVSP archive: $($_.Exception.Message)"
}

if (Test-Path $vspZipPath) {
  Remove-Item -Force $vspZipPath
}
Write-OK "Extracted to $vspFolderName"

$vspPythonDir = Join-Path $vspExtractPath "python"
if (-not (Test-Path $vspPythonDir)) {
  Fail "OpenVSP python directory not found at $vspPythonDir"
}

Write-Section "Installing OpenVSP Python requirements"
Push-Location $vspPythonDir
try {
  conda run -n $EnvName python -m pip install -r requirements-dev.txt
  if ($LASTEXITCODE -ne 0) {
    Fail "pip install -r requirements-dev.txt failed."
  }
} finally {
  Pop-Location
}
Write-OK "OpenVSP Python requirements installed."

Write-Section "Done"
Write-OK "Activate with: conda activate $EnvName"
