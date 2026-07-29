# =============================================================================
# Aion Hand Windows Installer
# 
# Usage:
#   irm https://raw.githubusercontent.com/your-org/aion-hand/main/install.ps1 | iex
#
# Or locally:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AION_VERSION = "0.1.0"
$INSTALL_DIR = Join-Path $env:LOCALAPPDATA "aion-hand"
$BIN_DIR = Join-Path $INSTALL_DIR "bin"
$VENV_DIR = Join-Path $INSTALL_DIR "venv"
$REPO_URL = "https://github.com/your-org/aion-hand"
$BRANCH = "main"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Info    { param([string]$Msg) Write-Host "  [INFO] $Msg" -ForegroundColor Blue }
function Write-Ok      { param([string]$Msg) Write-Host "  [OK]   $Msg" -ForegroundColor Green }
function Write-Warn    { param([string]$Msg) Write-Host "  [WARN] $Msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$Msg) Write-Host "  [ERR]  $Msg" -ForegroundColor Red }
function Write-Step    { param([string]$Msg) Write-Host "  -- $Msg --" -ForegroundColor Magenta }

function Write-Banner {
    Write-Host ""
    Write-Host "     ===============================" -ForegroundColor Magenta
    Write-Host "        AION HAND  v$AION_VERSION" -ForegroundColor Magenta
    Write-Host "     The AI Operating System" -ForegroundColor Magenta
    Write-Host "     ===============================" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  Installing to: $INSTALL_DIR" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Check requirements ─────────────────────────────────────────────────────

function Test-Requirements {
    Write-Step "Checking system requirements"
    $hasError = $false

    # Python
    $python = $null
    foreach ($cmd in @("python3", "python", "python3.11", "python3.12")) {
        $p = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($p) {
            $python = $p.Source
            break
        }
    }

    if ($python) {
        $verOutput = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($verOutput -match "^(\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                Write-Ok "Python $verOutput ($python)"
                $script:PYTHON = $python
            } else {
                Write-Err "Python 3.11+ required (found $verOutput)"
                Write-Host "  Download: https://www.python.org/downloads/" -ForegroundColor DarkGray
                $hasError = $true
            }
        }
    } else {
        Write-Err "Python 3 not found"
        Write-Host "  Download: https://www.python.org/downloads/" -ForegroundColor DarkGray
        Write-Host "  Or: winget install Python.Python.3.12" -ForegroundColor DarkGray
        $hasError = $true
    }

    # pip
    $pip = Get-Command "pip" -ErrorAction SilentlyContinue
    if ($pip) {
        Write-Ok "pip found"
    } elseif ($python) {
        $pipCheck = & $python -m pip --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "pip available via python -m pip"
        } else {
            Write-Warn "pip not found — will bootstrap"
        }
    }

    # git
    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($git) {
        $gitVer = & git --version 2>$null
        Write-Ok $gitVer
    } else {
        Write-Warn "git not found — auto-update unavailable"
    }

    if ($hasError) {
        Write-Err "Missing required dependencies. Fix above and retry."
        exit 1
    }
    Write-Host ""
}

# ── Create directories ─────────────────────────────────────────────────────

function New-InstallDirectories {
    Write-Step "Creating installation directories"
    $dirs = @(
        $BIN_DIR,
        (Join-Path $INSTALL_DIR "data"),
        (Join-Path $INSTALL_DIR "memory"),
        (Join-Path $INSTALL_DIR "skills"),
        (Join-Path $INSTALL_DIR "tools"),
        (Join-Path $INSTALL_DIR "logs"),
        (Join-Path $INSTALL_DIR "knowledge"),
        (Join-Path $INSTALL_DIR "benchmarks"),
        (Join-Path $INSTALL_DIR "config")
    )
    foreach ($d in $dirs) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
    Write-Ok "Directories created at $INSTALL_DIR"
    Write-Host ""
}

# ── Create venv ────────────────────────────────────────────────────────────

function New-VirtualEnvironment {
    Write-Step "Creating Python virtual environment"

    if (Test-Path $VENV_DIR) {
        Write-Warn "Existing venv found — removing for fresh install"
        Remove-Item -Recurse -Force $VENV_DIR
    }

    & $script:PYTHON -m venv $VENV_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to create virtual environment"
        exit 1
    }

    $activateScript = Join-Path $VENV_DIR "Scripts" "Activate.ps1"
    if (-not (Test-Path $activateScript)) {
        Write-Err "Virtual environment activation script not found"
        exit 1
    }

    # Activate and upgrade pip
    & $activateScript
    $pipExe = Join-Path $VENV_DIR "Scripts" "pip.exe"
    if (-not (Test-Path $pipExe)) {
        & $script:PYTHON -m ensurepip --upgrade
    }
    & $pipExe install --quiet --upgrade pip wheel

    Write-Ok "Virtual environment ready"
    Write-Host ""
    $script:PIP = $pipExe
}

# ── Fetch source ───────────────────────────────────────────────────────────

function Get-Source {
    Write-Step "Fetching Aion Hand source"
    $srcDir = Join-Path $INSTALL_DIR "src"

    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($git -and (Test-Path (Join-Path $srcDir ".git"))) {
        Write-Info "Updating existing clone..."
        Push-Location $srcDir
        & git pull --ff-only --quiet 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Warn "Git pull failed — using existing source" }
        Pop-Location
    } elseif ($git) {
        Write-Info "Cloning from $REPO_URL..."
        & git clone --depth 1 --branch $BRANCH $REPO_URL $srcDir 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Clone failed — will try PyPI"
            $script:SRC_DIR = ""
            Write-Host ""
            return
        }
    } else {
        $script:SRC_DIR = ""
        Write-Host ""
        return
    }

    $script:SRC_DIR = $srcDir
    Write-Host ""
}

# ── Install ────────────────────────────────────────────────────────────────

function Install-AionHand {
    Write-Step "Installing Aion Hand v$AION_VERSION"
    $installed = $false

    # Try local clone
    if (-not $installed -and $script:SRC_DIR -and (Test-Path (Join-Path $script:SRC_DIR "pyproject.toml"))) {
        Write-Info "Installing from source clone..."
        & $script:PIP install --quiet -e "$($script:SRC_DIR)[all]" 2>$null
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }

    # Try current directory
    if (-not $installed -and (Test-Path "pyproject.toml")) {
        Write-Info "Installing from current directory..."
        & $script:PIP install --quiet -e ".[all]" 2>$null
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }

    # Try setup.py
    if (-not $installed -and (Test-Path "setup.py")) {
        Write-Info "Installing from setup.py..."
        & $script:PIP install --quiet -e . 2>$null
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }

    # Try PyPI
    if (-not $installed) {
        Write-Info "Installing from PyPI..."
        & $script:PIP install --quiet aion-hand 2>$null
        if ($LASTEXITCODE -eq 0) {
            $installed = $true
        } else {
            Write-Err "Could not install aion-hand from any source"
            exit 1
        }
    }

    Write-Ok "Aion Hand v$AION_VERSION installed"
    Write-Host ""
}

# ── Create CLI wrappers ─────────────────────────────────────────────────────

function New-CLIWrappers {
    Write-Step "Creating CLI commands"

    # aion-hand.cmd
    $cmdContent = @"
@echo off
set "AION_HOME=%LOCALAPPDATA%\aion-hand"
set "VENV_DIR=%AION_HOME%\venv"
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [ERROR] Aion Hand not installed. Run install.ps1
    exit /b 1
)
call "%VENV_DIR%\Scripts\activate.bat"
python -m aion_hand_cli.cli %*
"@
    $cmdPath = Join-Path $BIN_DIR "aion-hand.cmd"
    Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII

    # aion.cmd
    $aionContent = @"
@echo off
"%LOCALAPPDATA%\aion-hand\bin\aion-hand.cmd" %*
"@
    $aionPath = Join-Path $BIN_DIR "aion.cmd"
    Set-Content -Path $aionPath -Value $aionContent -Encoding ASCII

    Write-Ok "Commands: aion-hand.cmd, aion.cmd"
    Write-Host ""
}

# ── Configure PATH ─────────────────────────────────────────────────────────

function Set-UserPath {
    Write-Step "Configuring user PATH"

    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$BIN_DIR*") {
        [Environment]::SetEnvironmentVariable("Path", "$currentPath;$BIN_DIR", "User")
        # Also update current session
        $env:Path = "$env:Path;$BIN_DIR"
        Write-Ok "Added $BIN_DIR to user PATH"
    } else {
        Write-Ok "PATH already configured"
    }
    Write-Host ""
}

# ── Setup .env ──────────────────────────────────────────────────────────────

function Set-EnvFile {
    Write-Step "Setting up configuration"
    $envFile = Join-Path $INSTALL_DIR ".env"

    if (Test-Path $envFile) {
        Write-Info "Existing .env preserved"
    } else {
        $defaultEnv = @"
# Aion Hand Configuration
# =======================

# AI Provider: openai | anthropic | ollama
AION_PROVIDER=ollama

# API Key (not needed for Ollama)
# AION_API_KEY=sk-...

# Default model
AION_MODEL=

# Logging level: DEBUG | INFO | WARNING | ERROR
AION_LOG_LEVEL=INFO

# Data directory
AION_DATA_DIR=$INSTALL_DIR\data

# Memory directory
AION_MEMORY_DIR=$INSTALL_DIR\memory
"@
        Set-Content -Path $envFile -Value $defaultEnv -Encoding UTF8
        Write-Ok ".env template created at $envFile"
        Write-Host "  Edit this file to add your API keys." -ForegroundColor DarkGray
    }
    Write-Host ""
}

# ── Uninstall ──────────────────────────────────────────────────────────────

function Uninstall-AionHand {
    if (-not (Test-Path $INSTALL_DIR)) {
        Write-Warn "Aion Hand not found at $INSTALL_DIR"
        return
    }
    Write-Host "  Uninstalling Aion Hand from $INSTALL_DIR..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $INSTALL_DIR

    # Remove from PATH
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $BIN_DIR }) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")

    Write-Ok "Uninstalled. Open a new terminal for PATH changes."
}

# ── Print success ──────────────────────────────────────────────────────────

function Write-Success {
    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host "  Aion Hand installed successfully!" -ForegroundColor Green
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  1. Open a NEW terminal (for PATH update)" -ForegroundColor Cyan
    Write-Host "  2. Run: aion-hand setup" -ForegroundColor Cyan
    Write-Host "  3. Run: aion-hand" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Config: $INSTALL_DIR\.env" -ForegroundColor DarkGray
    Write-Host "  Logs:   $INSTALL_DIR\logs" -ForegroundColor DarkGray
    Write-Host "  Data:   $INSTALL_DIR\data" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Main ────────────────────────────────────────────────────────────────────

param(
    [switch]$Uninstall,
    [switch]$Help,
    [string]$Dir
)

if ($Dir) {
    $INSTALL_DIR = $Dir
    $BIN_DIR = Join-Path $INSTALL_DIR "bin"
    $VENV_DIR = Join-Path $INSTALL_DIR "venv"
}

if ($Uninstall) {
    Uninstall-AionHand
    exit 0
}

if ($Help) {
    Write-Host "Aion Hand Windows Installer v$AION_VERSION"
    Write-Host ""
    Write-Host "Usage: install.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Dir DIR       Installation directory"
    Write-Host "  -Uninstall     Remove installation"
    Write-Host "  -Help          Show this help"
    exit 0
}

Write-Banner
Test-Requirements
New-InstallDirectories
New-VirtualEnvironment
Get-Source
Install-AionHand
New-CLIWrappers
Set-UserPath
Set-EnvFile
Write-Success