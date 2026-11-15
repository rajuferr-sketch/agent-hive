#!/usr/bin/env bash
# AgentHive — start the API server (Linux / macOS / WSL / Git Bash).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=============================================================="
echo " AgentHive — Advanced multi-agent orchestration system"
echo " 1 Master Agent, 20 specialized AI agents"
echo "=============================================================="

# --- Activate the project virtual environment when present -------------------
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "==> Activated virtual environment (.venv)"
elif [[ -f .venv/Scripts/activate ]]; then
    # Git Bash on Windows uses the Windows-style venv layout
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
    echo "==> Activated virtual environment (.venv)"
fi

# --- Launch -------------------------------------------------------------------
if command -v agent-hive >/dev/null 2>&1; then
    echo "==> Starting: agent-hive start"
    exec agent-hive start
else
    echo "==> agent-hive not on PATH — falling back to: python -m agent_hive start"
    exec python -m agent_hive start
fi
