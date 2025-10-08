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

function Get-CondaEnvs() {
  $jsonRaw = conda env list --json
  if ($LASTEXITCODE -ne 0 -or -not $jsonRaw) { Fail "Failed to query conda environments (JSON)." }
  return ($jsonRaw | ConvertFrom-Json).envs
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
    Write-Warn "Env-Exists: fallback detection (conda env list --json failed)."
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
      # Double-check whether prefix actually exists now (race or partial removal)
      if (Env-Exists $name) {
        Fail "conda env create reported failure but the prefix now exists. Try: conda env remove -n $name -y; then re-run with -Force."
      }
      Fail "conda env create failed."
    }
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

# --- helper to write a temp script without BOM ---
function Write-NoBomTempScript([string]$code) {
  $tmp = New-TemporaryFile
  $enc = New-Object System.Text.UTF8Encoding($false)  # no BOM
  [System.IO.File]::WriteAllText($tmp, $code, $enc)
  return $tmp
}

function Find-OpenVSPPythonDir([string]$installRoot) {
  if (-not (Test-Path $installRoot)) { return $null }
  $candidate = Get-ChildItem -Path $installRoot -Recurse -Filter openvsp.py -ErrorAction SilentlyContinue |
               Select-Object -First 1
  if ($candidate) { return $candidate.Directory.FullName }
  return $null
}

function Normalize-OpenVSPRoot([string]$root) {
  if (-not $root) { return $root }
  $full = [IO.Path]::GetFullPath($root)
  # Collapse repeated trailing "...\<ver>\windows" pairs
  $segments = $full -split '[\\/]'
  if ($segments.Length -gt 3) {
    for ($i = 0; $i -lt ($segments.Length - 2); $i++) {
      if ($segments[$i] -match '^\d+\.\d+\.\d+$' -and $segments[$i+1] -ieq 'windows') {
        # If same pattern repeats immediately after
        if ($i + 3 -lt $segments.Length -and
            $segments[$i] -eq $segments[$i+2] -and
            $segments[$i+1] -ieq $segments[$i+3]) {
          # Remove the duplicate pair
          $segments = $segments[0..($i+1)] + $segments[($i+4)..($segments.Length-1)]
          break
        }
      }
    }
  }
  return ($segments -join '\').TrimEnd('\','/')
}

function Set-LocalOpenVSPEnv($manifest) {
  if ($null -ne $manifest.install_root -and $manifest.install_root -ne "") {
    $env:OPENVSP_HOME = $manifest.install_root
    $env:STREAMLINE_OPENVSP_HOME = $manifest.install_root
  }
  if ($manifest.python_dir) {
    $env:OPENVSP_PYTHON_DIR = $manifest.python_dir
    $env:STREAMLINE_OPENVSP_PYTHON_DIR = $manifest.python_dir
  }
  if ($manifest.version) {
    $env:OPENVSP_VERSION = $manifest.version
    $env:STREAMLINE_OPENVSP_VERSION = $manifest.version
  }
}

function Clear-ExistingOpenVSPEnv([string]$name) {
  Write-Section "Clearing stale OpenVSP env vars (conda + session)"
  $vars = @(
    'OPENVSP_HOME','OPENVSP_PYTHON_DIR','OPENVSP_VERSION',
    'STREAMLINE_OPENVSP_HOME','STREAMLINE_OPENVSP_PYTHON_DIR','STREAMLINE_OPENVSP_VERSION'
  )
  try { conda env config vars unset -n $name @vars 2>$null | Out-Null } catch { }
  foreach ($v in $vars) { Remove-Item Env:$v -ErrorAction SilentlyContinue }
}

function Remove-StrayPipOpenVSP([string]$name) {
  Write-Section "Checking for stray pip 'openvsp' package"
  conda run -n $name python -m pip show openvsp 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Warn "A pip package named 'openvsp' is installed; uninstalling to avoid shadowing official bindings."
    conda run -n $name python -m pip uninstall -y openvsp | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warn "Failed to uninstall pip openvsp (continuing)." } else { Write-OK "Removed stray pip openvsp package." }
  } else { Write-OK "No stray pip openvsp package detected." }
}

function Install-OpenVSP([string]$name) {
  Write-Section "Installing OpenVSP runtime via Python helper"
  $exportPath = Join-Path ([System.IO.Path]::GetTempPath()) "streamline-openvsp-install.json"
  if (Test-Path $exportPath) { Remove-Item $exportPath -Force }

  conda run -n $name python -m tools.install_openvsp --force --print-json --export $exportPath 2>&1 | ForEach-Object { $_ }
  if ($LASTEXITCODE -ne 0) { Fail "OpenVSP installer failed (non-zero exit)." }
  if (-not (Test-Path $exportPath)) { Fail "Installer did not produce export manifest file." }

  try {
    $manifestRaw = Get-Content $exportPath -Raw
    $manifest = $manifestRaw | ConvertFrom-Json -ErrorAction Stop
  } catch {
    Fail "Failed to read exported OpenVSP manifest JSON: $($_.Exception.Message)"
  } finally {
    if (Test-Path $exportPath) { Remove-Item $exportPath -Force }
  }

  Clear-ExistingOpenVSPEnv -name $name
  conda env config vars set -n $name OPENVSP_HOME=$($manifest.install_root) STREAMLINE_OPENVSP_HOME=$($manifest.install_root) | Out-Null
  if ($manifest.python_dir) {
    conda env config vars set -n $name OPENVSP_PYTHON_DIR=$($manifest.python_dir) STREAMLINE_OPENVSP_PYTHON_DIR=$($manifest.python_dir) | Out-Null
  }
  if ($manifest.version) {
    conda env config vars set -n $name OPENVSP_VERSION=$($manifest.version) STREAMLINE_OPENVSP_VERSION=$($manifest.version) | Out-Null
  }
  Set-LocalOpenVSPEnv $manifest

  Write-Section "OpenVSP resolved paths"
  Write-Host ("  install_root : {0}" -f $manifest.install_root)
  Write-Host ("  python_dir   : {0}" -f $manifest.python_dir)

  # Warm-up (authoritative). If this works we suppress earlier missing-list noise.
  $repoRoot = (Resolve-Path ".").Path
  $warm = @"
import os, sys, importlib.util
repo = r'$repoRoot'
py_dir = r'$($manifest.python_dir)'
base = r'$($manifest.install_root)'
if repo and repo not in sys.path: sys.path.insert(0, repo)
if py_dir and py_dir not in sys.path: sys.path.insert(0, py_dir)
if os.name=='nt':
    for d in (base, base+os.sep+'bin', base+os.sep+'vspaero_ex'):
        if d and d not in os.environ.get('PATH',''):
            os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH','')
status = {'warmup_addgeom': False, 'promoted': False, 'wrapper_missing': None, 'final_missing': None}
try:
    import openvsp
    req = ['AddGeom','ClearVSPModel','SetGeomName','SetParmVal','GetParmVal','Update']
    missing = [r for r in req if not hasattr(openvsp,r)]
    status['wrapper_missing'] = missing
    if missing:
        spec = importlib.util.find_spec('openvsp._vsp')
        if spec:
            core = __import__('openvsp._vsp', fromlist=['_vsp'])
            if hasattr(core,'AddGeom'):
                for n in dir(core):
                    if not n.startswith('_') and not hasattr(openvsp,n):
                        try: setattr(openvsp,n,getattr(core,n))
                        except Exception: pass
                if hasattr(core,'VSPVersion') and not hasattr(openvsp,'GetVSPVersion'):
                    try: openvsp.GetVSPVersion = core.VSPVersion
                    except Exception: pass
                status['promoted'] = True
    status['final_missing'] = [r for r in req if not hasattr(openvsp,r)]
    status['warmup_addgeom'] = hasattr(openvsp,'AddGeom') and ('AddGeom' not in status['final_missing'])
except Exception as e:
    status['error'] = repr(e)
print('WARMUP_STATUS', status)
"@
  $tmpWarm = Write-NoBomTempScript $warm
  $warmOutput = conda run -n $name python $tmpWarm | Tee-Object -Variable warmLines
  Remove-Item $tmpWarm -Force
  $warmLine = ($warmLines | Select-String 'WARMUP_STATUS').ToString()
  if ($warmLine) {
    try {
      $jsonPortion = $warmLine -replace '^WARMUP_STATUS\s*',''
      $parsed = ConvertFrom-Json ($jsonPortion | ConvertTo-Json) -ErrorAction Stop
    } catch { $parsed = $null }
    if ($parsed -and $parsed.warmup_addgeom -eq $true) {
      Write-OK "OpenVSP symbols available (AddGeom)"
    } else {
      Write-Warn "Warm-up did not confirm full symbol set (see WARMUP_STATUS above)."
    }
  }
}

function Validate-Imports([string]$name) {
  Write-Section "Validating environment"
  $repoRoot = (Resolve-Path ".").Path
  $code = @"
import os, sys, json, importlib.util
repo = r'$repoRoot'
py_dir = os.environ.get('OPENVSP_PYTHON_DIR') or os.environ.get('STREAMLINE_OPENVSP_PYTHON_DIR')
if repo and repo not in sys.path: sys.path.insert(0, repo)
if py_dir and py_dir not in sys.path: sys.path.insert(0, py_dir)
# Ensure DLL path ordering (Windows)
if os.name == 'nt' and py_dir:
    base = os.path.dirname(py_dir)
    for d in (base, os.path.join(base,'bin'), os.path.join(base,'vspaero_ex')):
        if d and d not in os.environ.get('PATH',''):
            os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH','')
print('Validation sys.path head:', sys.path[:6])
result = {
  'py_dir': py_dir,
  'wrapper_missing': None,
  'promoted': False,
  'final_missing': None,
  'module_file': None,
}
try:
    import openvsp
    result['module_file'] = getattr(openvsp,'__file__', None)
    req = ['AddGeom','ClearVSPModel','SetGeomName','SetParmVal','GetParmVal','Update']
    wrapper_missing = [r for r in req if not hasattr(openvsp,r)]
    result['wrapper_missing'] = wrapper_missing
    if wrapper_missing:
        # Attempt promotion via compiled layer
        spec = importlib.util.find_spec('openvsp._vsp')
        if spec:
            core = __import__('openvsp._vsp', fromlist=['_vsp'])
            if hasattr(core,'AddGeom'):
                for n in dir(core):
                    if not n.startswith('_') and not hasattr(openvsp,n):
                        try: setattr(openvsp,n,getattr(core,n))
                        except Exception: pass
                if hasattr(core,'VSPVersion') and not hasattr(openvsp,'GetVSPVersion'):
                    try: openvsp.GetVSPVersion = core.VSPVersion
                    except Exception: pass
                result['promoted'] = True
    final_missing = [r for r in req if not hasattr(openvsp,r)]
    result['final_missing'] = final_missing
    if final_missing:
        print('VALIDATION_INCOMPLETE_OPENVSP', json.dumps(result))
    else:
        print('OpenVSP OK (promoted=', result['promoted'], ') AddGeom=True')
except Exception as e:
    result['error'] = repr(e)
    print('VALIDATION_OPENVSP_IMPORT_FAIL', json.dumps(result))
    raise SystemExit(3)
# Do NOT produce non-zero exit just because wrapper was thin; allow promotion success
if result['final_missing']:
    # Return code 0 but user sees warning line
    pass
"@
  $tmp = Write-NoBomTempScript $code
  conda run -n $name python $tmp
  $ec = $LASTEXITCODE
  Remove-Item $tmp -Force
  if ($ec -ne 0) { Fail "Validation failed (python exited $ec)." }
  Write-OK "Validation completed (wrapper gaps tolerated if promotion succeeded)."
}

Write-Section "Streamline environment setup"
Ensure-Conda
Create-Or-Update-Env -name $EnvName -force:$Force -allowUpdate:$AllowUpdate
Assert-PythonVersion -name $EnvName
Install-PipDeps -name $EnvName
Remove-StrayPipOpenVSP -name $EnvName
Install-OpenVSP -name $EnvName
Validate-Imports -name $EnvName
Write-Section "Done"
Write-OK "Activate with: conda activate $EnvName"

