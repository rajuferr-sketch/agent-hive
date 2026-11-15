#!/usr/bin/env bash
# AgentHive — one-shot installation script (Linux / macOS / WSL / Git Bash).
# Requires Python 3.11+.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=============================================================="
echo " AgentHive — Advanced multi-agent orchestration system"
echo " 1 Master Agent, 20 specialized AI agents"
echo "=============================================================="

# --- Locate a suitable Python interpreter -----------------------------------
PYTHON_CMD=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_CMD="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo "ERROR: no 'python3' or 'python' found on PATH." >&2
    echo "Install Python 3.11+ and re-run this script." >&2
    exit 1
fi

if ! "$PYTHON_CMD" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "ERROR: Python >= 3.11 is required (found: $("$PYTHON_CMD" -V 2>&1))." >&2
    exit 1
fi

echo "==> Using $("$PYTHON_CMD" -V 2>&1) at $(command -v "$PYTHON_CMD")"

# --- Virtual environment -----------------------------------------------------
if [[ ! -d .venv ]]; then
    echo "==> Creating virtual environment (.venv)"
    "$PYTHON_CMD" -m venv .venv
else
    echo "==> Reusing existing virtual environment (.venv)"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing dependencies"
python -m pip install -r requirements.txt

echo "==> Installing AgentHive (editable)"
python -m pip install -e .

# --- Environment template -----------------------------------------------------
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "==> Created .env from .env.example — edit it with your real values."
else
    echo "==> .env already present — leaving it untouched."
fi

# --- Next steps -----------------------------------------------------------------
echo ""
echo "Installation complete. Next steps:"
echo "  1. source .venv/bin/activate"
echo "  2. Edit .env (database URL, provider keys, feature switches)"
echo "  3. agent-hive init-db        # create database tables"
echo "  4. agent-hive diagnose       # verify the environment"
echo "  5. agent-hive start          # launch the API server"
echo ""
echo "Or run everything at once with Docker: docker compose up -d --build"
