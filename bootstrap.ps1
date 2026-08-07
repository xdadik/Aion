$ErrorActionPreference = 'Stop'

# Aion Hand Windows bootstrap installer.
# irm https://raw.githubusercontent.com/xdadik/Aion/main/bootstrap.ps1 | iex

$RepoUrl = 'https://github.com/xdadik/Aion.git'
$InstallDir = if ($env:AION_HOME) { $env:AION_HOME } else { Join-Path $env:LOCALAPPDATA 'aion-hand' }
$SrcDir = Join-Path $InstallDir 'src'
$VenvDir = Join-Path $InstallDir 'venv'
$BinDir = Join-Path $InstallDir 'bin'

function Fail($message) { Write-Error "[Aion] $message"; exit 1 }
function Log($message) { Write-Host "`n[Aion] $message" -ForegroundColor Cyan }

$pythonCmd = $null
foreach ($candidate in @('py','python','python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $ok = $false
        try { & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
        if ($ok) { $pythonCmd = $candidate; break }
    }
}
if (-not $pythonCmd) { Fail 'Python 3.11+ is required. Install it and rerun.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'git is required.' }

New-Item -ItemType Directory -Force -Path $InstallDir,$BinDir | Out-Null

if (Test-Path 'pyproject.toml') {
    $SrcDir = (Get-Location).Path
} elseif (Test-Path (Join-Path $SrcDir '.git')) {
    Log 'Updating Aion source'
    Push-Location $SrcDir
    git pull --ff-only --quiet
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'Local Aion checkout cannot be fast-forwarded.' }
    Pop-Location
} else {
    Log 'Downloading Aion Hand'
    git clone --depth 1 --branch main $RepoUrl $SrcDir
    if ($LASTEXITCODE -ne 0) { Fail 'Could not clone Aion Hand.' }
}

Log 'Creating isolated environment'
& $pythonCmd -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { Fail 'Could not create the Python virtual environment.' }
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e "$SrcDir[all]"
if ($LASTEXITCODE -ne 0) { Fail 'Aion installation failed.' }

Log 'Verifying installation'
& $VenvPython -c "import aion_core; print('Aion Hand import OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Aion installed but could not be imported.' }

$Launcher = Join-Path $BinDir 'aion-hand.cmd'
@"
@echo off
"$VenvPython" -m aion_hand_cli.cli %*
"@ | Set-Content -Encoding ASCII $Launcher

Log 'Installed successfully'
Write-Host "Run: $Launcher --help" -ForegroundColor Green
Write-Host "Add $BinDir to your PATH for the global aion-hand command." -ForegroundColor Gray
