# AgentHive — one-shot installation script (Windows PowerShell).
# Requires Python 3.10+.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=============================================================="
Write-Host " AgentHive - Advanced multi-agent orchestration system"
Write-Host " 1 Master Agent, 20 specialized AI agents"
Write-Host "=============================================================="

# --- Locate a suitable Python interpreter -------------------------------------
function Find-Python {
    # 1) Commands already on PATH
    foreach ($cmd in @("python", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    # 2) Standard per-user install locations
    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPython) {
        $candidates = Get-ChildItem -Path $localPython -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "python.exe" } |
            Where-Object { Test-Path $_ }
        if ($candidates) { return $candidates[0] }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "ERROR: no Python interpreter found." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://www.python.org/downloads/ and re-run."
    exit 1
}

$versionOutput = & $python -c "import sys; print('{}.{}'.format(sys.version_info[0], sys.version_info[1]))"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: failed to query version of $python." -ForegroundColor Red
    exit 1
}
$parts = $versionOutput.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Write-Host "ERROR: Python >= 3.10 is required (found: $versionOutput at $python)." -ForegroundColor Red
    exit 1
}
Write-Host "==> Using Python $versionOutput at $python"

# --- Virtual environment -------------------------------------------------------
$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "==> Creating virtual environment (.venv)"
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: failed to create the virtual environment." -ForegroundColor Red
        exit 1
    }
}
else {
    Write-Host "==> Reusing existing virtual environment (.venv)"
}

Write-Host "==> Upgrading pip"
& $venvPython -m pip install --upgrade pip --quiet

Write-Host "==> Installing dependencies"
& $venvPython -m pip install -r requirements.txt

Write-Host "==> Installing AgentHive (editable)"
& $venvPython -m pip install -e .

# --- Environment template --------------------------------------------------------
$envFile = Join-Path $RepoRoot ".env"
$envExample = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "==> Created .env from .env.example - edit it with your real values."
}
else {
    Write-Host "==> .env already present - leaving it untouched."
}

# --- Next steps -------------------------------------------------------------------
Write-Host ""
Write-Host "Installation complete. Next steps:"
Write-Host "  1. .venv\Scripts\Activate.ps1"
Write-Host "  2. Edit .env (database URL, provider keys, feature switches)"
Write-Host "  3. agent-hive init-db        # create database tables"
Write-Host "  4. agent-hive diagnose       # verify the environment"
Write-Host "  5. agent-hive start          # launch the API server"
Write-Host ""
Write-Host "Or run everything at once with Docker: docker compose up -d --build"
