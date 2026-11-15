# AgentHive - start the API server (Windows PowerShell).

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=============================================================="
Write-Host " AgentHive - Advanced multi-agent orchestration system"
Write-Host " 1 Master Agent, 20 specialized AI agents"
Write-Host "=============================================================="

# --- Activate the project virtual environment when present ---------------------
$activateScript = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
    Write-Host "==> Activated virtual environment (.venv)"
}

# --- Launch -----------------------------------------------------------------------
$agentHive = Get-Command agent-hive -ErrorAction SilentlyContinue
if ($agentHive) {
    Write-Host "==> Starting: agent-hive start"
    & agent-hive start
    exit $LASTEXITCODE
}

Write-Host "==> agent-hive not on PATH - falling back to: python -m agent_hive start"
& python -m agent_hive start
exit $LASTEXITCODE
