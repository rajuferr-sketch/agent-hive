# Operations Guide

Everything an operator needs: installation, database setup, first run, diagnostics, recovery, logs, backups and troubleshooting.

---

## 1. Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/agent-hive/agent-hive.git
cd agent-hive
.\scripts\install.ps1        # finds Python 3.11+, creates .venv, installs deps, copies .env.example → .env
.venv\Scripts\Activate.ps1
agent-hive init-db
agent-hive start             # http://127.0.0.1:8000
```

`scripts\install.ps1` locates `python`/`py` on PATH (or under `%LOCALAPPDATA%\Programs\Python`), verifies **Python ≥ 3.11**, creates the virtual environment and installs `requirements.txt` plus the editable package.

### Linux / macOS / WSL / Git Bash

```bash
git clone https://github.com/agent-hive/agent-hive.git
cd agent-hive
bash scripts/install.sh
source .venv/bin/activate
agent-hive init-db
agent-hive start
```

`scripts/install.sh` does the same checks for `python3`/`python`.

### Edit `.env` before going live

```bash
cp .env.example .env
```

Minimum for real AI: set `OPENAI_API_KEY` (and `OPENAI_BASE_URL` for non-OpenAI OpenAI-compatible servers) plus a production `DATABASE_URL`. With `ALLOW_MOCK=true` (default) the system runs fully offline — see the [Mock mode section in the README](../README.md#mock-mode-honest-simulation).

### Launchers & Make

- `scripts/start.sh` / `scripts/start.ps1` — activate the project venv (when present) and run `agent-hive start` (fallback: `python -m agent_hive start`).
- `make start | init-db | recover | diagnose | test | lint | typecheck | docker-up | docker-down` (Linux/macOS; on Windows use the `scripts\*.ps1` helpers).

---

## 2. PostgreSQL setup

SQLite (`sqlite+aiosqlite:///./data/agent_hive.db`) is the zero-config default for tests/local. **Use PostgreSQL in production.**

### Option A — docker compose (recommended)

`docker-compose.yml` ships `postgres:16-alpine` (health-checked with `pg_isready`) plus the app service:

```bash
export POSTGRES_PASSWORD="strong-password-here"
export OPENAI_API_KEY="sk-..."
docker compose up -d --build
```

The app container runs as the **non-root `hive` user**, mounts `./workspace`, and executes `agent-hive init-db && agent-hive start` with `DATABASE_URL=postgresql+asyncpg://agenthive:<pw>@db:5432/agenthive`. The compose file never hardcodes secrets — values come from your environment or a `.env` next to it.

### Option B — native PostgreSQL

Create the database and user, then set the connection string:

```bash
sudo -u postgres psql -c "CREATE USER agenthive WITH PASSWORD 'strong-password-here';"
sudo -u postgres psql -c "CREATE DATABASE agenthive OWNER agenthive;"
```

**`DATABASE_URL` format** (async driver required):

```text
postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE
```

Examples:

```bash
DATABASE_URL=postgresql+asyncpg://agenthive:strong-password-here@localhost:5432/agenthive
DATABASE_URL=postgresql+asyncpg://agenthive:strong-password-here@db.internal:5432/agenthive
DATABASE_URL=sqlite+aiosqlite:///./data/agent_hive.db   # tests / local
```

Then create the schema:

```bash
agent-hive init-db      # idempotent CREATE ALL over 6 tables:
                        # agents, tasks, messages, memories, events, verifications
```

---

## 3. First mission

```bash
# one-shot from the CLI (prints the deliverable; add --json for the full report)
agent-hive run "Design a small project management web application with a database, a REST API and unit tests" --mode C

# or start the API and use HTTP
agent-hive start
curl -X POST http://127.0.0.1:8000/api/missions \
  -H "Content-Type: application/json" \
  -d '{"text": "Design a small project management web application with a database, a REST API and unit tests"}'
```

Watch progress live on `ws://127.0.0.1:8000/ws` (`mission.started`, `task.created`, `task.completed`, `quality.verified`, `mission.completed`), or poll:

```bash
curl http://127.0.0.1:8000/api/missions/<MISSION_ID>
```

A smoke test covering Modes A and C end-to-end in mock mode exists:

```bash
python scripts/smoke_test.py
```

---

## 4. Diagnosing

```bash
agent-hive diagnose
# standalone, no external deps (works before pip install):
python scripts/diagnose.py
```

Both share the same checks (`src/agent_hive/diagnostics.py`):

| Check | Meaning | Failure action |
|---|---|---|
| `python` | Interpreter ≥ 3.11 + platform | Upgrade Python |
| `package` | `agent_hive` is importable | Reinstall (`pip install -e .`) |
| `configuration` | `configs/system.yaml` loads; all `configs/agents/*.yaml` load; every declared `role` resolves in `ROLE_REGISTRY` | Fix the broken YAML or add the missing role class |
| `database` | `SELECT 1` through the async engine (URL scheme only is ever printed — never credentials) | See troubleshooting below |
| **Providers** (informational) | One health probe per unique provider type across all agent chains (10 s timeout each): `openai_compatible` → `GET /models`, `ollama` → `GET /api/tags` | Non-fatal when `ALLOW_MOCK=true` (tagged mock fallback); fix connectivity or pull the model otherwise |

Exit code: `0` when the core (python/package/config/database) is healthy, `1` otherwise. Provider probes never fail the run. Secrets are never printed.

---

## 5. Recovery after a crash

**Automatic.** Every `startup()` runs `TaskManager.recover()` before the scheduler starts: orphaned `running`/`assigned` tasks are reset to `queued` with `agent_name=None` and `error="recovered after restart"`, so they are re-assigned and retried normally (attempts/max_retries still apply).

**Manual.** After a crash (or to force a reset without restarting the server's process):

```bash
agent-hive recover
# → Recovered 3 orphaned task(s)
```

The `agents` table heartbeat (`sync_registry`, every 15 s) keeps the roster snapshot fresh; task state itself lives entirely in the database, so nothing else is lost across restarts.

---

## 6. Logs

- Logs are written to **stderr** by default in the format `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`, controlled by `LOG_LEVEL` (`DEBUG | INFO | WARNING | ERROR`).
- `setup_logging()` optionally accepts a file handler (`log_file`), and `logs/` is already git-ignored if you direct logs there.
- `httpx`, `httpcore`, `uvicorn.access` and `asyncio` loggers are silenced to `WARNING` to reduce noise.
- Useful structured sources beyond text logs: the `events` table (append-only audit log) and the live WebSocket feed `ws://127.0.0.1:8000/ws`.

---

## 7. Backups

- **PostgreSQL**: standard tooling — `pg_dump -Fc agenthive > agenthive_$(date +%F).dump` (and `pg_restore` to restore). All system state (tasks, memory, messages, verifications) lives in the database.
- **SQLite**: stop the process (or use the SQLite backup API) and copy `data/agent_hive.db`.
- `data/`, `logs/`, `workspace/` are git-ignored runtime directories; do not commit them.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Ollama returns **404** during a call | Model not pulled locally | `ollama pull llama3.2` (match the `model:` in the agent YAML) |
| Provider call returns **401** | Missing/invalid API key in the env var named by `api_key_env` | Set the key in `.env`; the chain automatically falls back to the next provider (e.g. Ollama) — check the `Providers` table in `agent-hive diagnose` |
| Every agent answers with `[MOCK]` output | All real providers failed/unconfigured and `ALLOW_MOCK=true` | Set a valid `OPENAI_API_KEY` / start Ollama; or `POST /api/system/settings {"allow_mock": false}` to fail hard and see the real error |
| `agent-hive start` → **port busy** (`[Errno 98]/WinError 10048`) | Port 8000 already in use | Change port: `agent-hive start --port 8001` (or `API_PORT=8001`); stop the other process |
| Startup fails with `ConfigError: Agent 'x' declares role 'y' but no role class is registered` | YAML `role` typo or missing role module | Fix the `role:` value or add the class in `src/agent_hive/agents/roles/`; verify with `agent-hive diagnose` |
| Startup/API fails with DB connection error | PostgreSQL unreachable, wrong credentials, or driver missing | Check `DATABASE_URL` format (`postgresql+asyncpg://…`), confirm the server is up (`docker compose ps`, `pg_isready`), run `agent-hive diagnose` |
| Tasks stay `queued` | No agent holds the requested capability, or a dependency never completed | Inspect `GET /api/tasks/{id}` (`depends_on`, error); check roster capabilities via `GET /api/agents` |
| Task failed with `timeout after Ns` | Task exceeded its `timeout_s` budget | Raise `DEFAULT_TASK_TIMEOUT`/per-task timeout or use a faster backend; retries happen automatically up to `max_retries` |
| Mission failed with `ProviderError: All providers failed` | Chain exhausted with `ALLOW_MOCK=false` | Restore at least one working provider in the chain |
| `403 … not authorized to use tool 'file_write'` | Tool not in the agent's YAML `tools`, or file tools disabled | Add the tool to the YAML and/or set `ENABLE_FILE_TOOLS=true`; file paths must stay inside `WORKSPACE_DIR` |
| `422` on `POST /api/missions` | `text` shorter than 5 chars or invalid `mode` (must be `A`/`C`/`B`) | Fix the payload |
| Quality gate fails repeatedly (score < 0.7) | Missing requirements, code syntax errors, secrets or TODO markers in deliverables | Read `report["quality"]["findings"]`; the Master already runs up to 2 revision rounds — improve the request or relax thresholds in `configs/system.yaml` |

---

## 9. Performance tuning

| Knob | Default | Guidance |
|---|---|---|
| `MAX_CONCURRENCY` | 8 | Tasks executing in parallel. For local LLM servers, match the server's parallel request capacity; for cloud APIs you can raise it substantially. More concurrency = more simultaneous provider calls. |
| `DEFAULT_TASK_TIMEOUT` | 120 s | Increase for slow local models (Ollama on CPU) or long generation tasks; the scheduler enforces it per attempt. |
| `DEFAULT_MAX_RETRIES` | 2 | Raise for flaky networks; every retry re-assigns the task (possibly to a different agent). |
| `SCHEDULER_INTERVAL` | 1.0 s | Poll frequency for ready tasks; lower = faster pickup, higher = less DB churn. |
| Provider chains | per agent | Put the *primary* backend first; the circuit breaker (skip after 2 consecutive failures for 60 s) keeps a down fallback from slowing calls. |
| Mode selection | thresholds in `configs/system.yaml` | For latency-critical workloads, raise `simple_threshold` so most requests use single-agent Mode A; reserve Mode B for genuinely complex missions. |

Note that mission duration is dominated by the *provider* latency and the number of tasks in the DAG (Mode B runs 20+ tasks plus the review/integration/QA/validation pipeline).
