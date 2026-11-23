# AgentHive

[![CI](https://github.com/rajuferr-sketch/agent-hive/actions/workflows/ci.yml/badge.svg)](https://github.com/rajuferr-sketch/agent-hive/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://github.com/astral-sh/ruff)

**AgentHive** is an advanced multi-agent orchestration system: **1 Master Agent + 20 specialized AI agents** that analyze your request, decompose it into tasks, collaborate through shared memory and a message bus, and deliver a single quality-gated result.

> One request in → one verified deliverable out. The hive decides *how*.

## AI chats and coding agents — start here

This repository is prepared for AI assistants. **Read [`AGENTS.md`](AGENTS.md) first** — it contains the bootstrap protocol (what to read, in which order), quick start, commands, repository map, conventions and guardrails. Then check **[`TASKS.md`](TASKS.md)** for the currently assigned task. A machine-readable index for LLMs is available at [`llms.txt`](llms.txt). `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` all point back to `AGENTS.md`, so every major AI tool auto-loads the same protocol.

## Try in 30 seconds

```bash
python run.py "Write a short haiku about automated testing in Python"
```

Install once: `pip install -r requirements.txt`. No API key required (deterministic mock provider). Output is Markdown.

---

## Universal AI Platform — every AI client, one hive

AgentHive is also a **universal AI connectivity layer**: any client — Claude
Desktop, ChatGPT, Gemini, Z.ai, DeepSeek, Qwen, Mistral, Grok, Perplexity,
Ollama frontends, LM Studio, vLLM, llama.cpp, LocalAI, plain REST/WebSocket —
reaches the *same* 18 tools, the *same* gateway and the *same* persistent
shared memory. Work started with one client can be continued with another.

```text
USER/AI CLIENT (MCP | REST | WS | OpenAI-compat | Ollama-compat | tool-calling)
        │
        ▼
  UNIVERSAL AI GATEWAY ── identify · validate · rate-limit · translate to mission
        │
        ▼
  MASTER AGENT → 20 SPECIALIST AGENTS (plan · delegate · parallel run · QA gate)
        │
        ▼
  UNIVERSAL SHARED MEMORY (episodic/semantic/operational/task/decision,
  full-text + vector search, TTL, versioning, per user/project/session)
```

* **MCP server** — 18 tools over Streamable HTTP (`POST /mcp`) and STDIO
  (`agent-hive mcp`), JSON-RPC 2.0, session handling, structured errors. No
  MCP SDK dependency. → [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md)
* **OpenAI-compatible server** — `/v1/models`, `/v1/chat/completions`
  (incl. streaming + tool invocation), `/v1/responses` session resume.
  → [`docs/CHATGPT_SETUP.md`](docs/CHATGPT_SETUP.md)
* **Ollama-compatible server** — `/api/tags`, `/api/chat`, `/api/generate`:
  point Open WebUI or any Ollama client at the hive. →
  [`docs/OLLAMA_SETUP.md`](docs/OLLAMA_SETUP.md)
* **WebSocket** — `/ws/universal` request/response protocol (+ `/ws` event
  firehose).
* **Cross-client memory** — the flagship feature: Claude creates a task →
  the hive executes it → results stored in universal memory → ChatGPT (or
  any client) picks it up later. Verified end-to-end by the mandatory
  `UNIVERSAL CROSS-CLIENT MEMORY TEST` in the suite.
* **Security by design** — scoped API tokens (hash-only storage, revoke,
  rotate), RBAC roles, rate limiting, audit trail, prompt-injection guard,
  secret redaction, optional enforced mode. → [`docs/SECURITY.md`](docs/SECURITY.md)
* **GitHub integration** — repo reads, branches, commits, PRs, issues,
  security scan; four safety modes (`read_only` → `autonomous`) with
  explicit confirmation for destructive operations.
* **Self-heal** — bounded auto-diagnostics loop (DB, scheduler, agents,
  memory) with retry caps, time budget and safe-stop.
* **Install** — `git clone && cd agent-hive && docker compose up -d` →
  [`docs/DOCKER_SETUP.md`](docs/DOCKER_SETUP.md).

The full REST/API surface: [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

---

## Features

- **Autonomous Master Agent** — analyzes complexity, decomposes work into a task DAG, delegates, monitors, integrates, and verifies before delivering (10 documented responsibilities, see [docs/architecture.md](docs/architecture.md)).
- **20 specialized agents** — programmer, architect, database, security, QA, tester, reviewer, integrator and more, each with its own role class, capabilities, tools and provider chain (see [docs/agents.md](docs/agents.md)).
- **3 operating modes** — *A* (simple: 1 agent), *C* (adaptive: 2–10 agents), *B* (collective: all 20 agents with cross-review → integration → QA → validation pipeline), chosen by a complexity heuristic or forced by you.
- **3-tier persistent memory** — individual per-agent memory, project-wide shared memory with versioned upserts and automatic archival, and an append-only history (see [docs/memory.md](docs/memory.md)).
- **Persistent message bus** — agents exchange `info / request / response / assistance / problem / proposal / challenge / review` messages; every message is stored in the database.
- **Provider fallback chains per agent** — `openai_compatible → ollama → mock` by default, with a circuit breaker (skip after 2 consecutive failures for 60 s). Works with OpenAI, vLLM, LM Studio, LiteLLM, Groq, DeepSeek, Ollama, or fully offline via the deterministic mock (see [docs/providers.md](docs/providers.md)).
- **Quality gate** — completeness, requirements coverage, static AST check of embedded Python, secret scanning and leftover-marker detection; score ≥ 0.7 required, up to 2 revision rounds.
- **Issue tracker** — GitHub-style issues (`open → in_progress → blocked → resolved → closed`) with labels, comments and capability-based triage: the hive assigns each issue to the best-matched agent.
- **Pull requests** — PR lifecycle (`open → changes_requested → approved → merged/closed`) with per-agent review verdicts, GitHub-style review aggregation and a **guarded merge** (only approved PRs land). The hive `reviewer` agent can review PRs end-to-end.
- **Agent management** — persistent DB-backed registry, hot enable/disable without restart, runtime registration of agent #21+ (spec persisted to `configs/agents/`), provider-chain health probes and per-agent workload stats.
- **REST + WebSocket API** — FastAPI with live event streaming (see [docs/api.md](docs/api.md)).
- **Security by design** — secrets only via environment variables, permission-controlled tools, sandboxed file access, non-root Docker image.

## Architecture at a glance

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        CLI["CLI (typer)"]
        REST["REST / WebSocket clients"]
    end
    subgraph Core["agent_hive core"]
        API["api/app.py<br/>FastAPI"]
        MASTER["Master Agent<br/>(orchestrator)"]
        QG["Quality Gate"]
        SCHED["Scheduler<br/>(concurrency + retries)"]
        TM["Task Manager<br/>(task DAG state machine)"]
        RT["AgentRuntime<br/>(20 agents)"]
        BUS["MessageBus<br/>(persistent + mailboxes)"]
        MEM["MemoryManager<br/>(3 tiers)"]
        PROV["Provider chains<br/>(openai_compatible / ollama / mock)"]
        TOOLS["Tool registry<br/>(permission-checked)"]
    end
    DB[("PostgreSQL / SQLite<br/>agents · tasks · messages ·<br/>memories · events · verifications")]

    CLI --> MASTER
    REST --> API --> MASTER
    MASTER --> TM
    TM --> SCHED --> RT
    RT --> BUS
    RT --> MEM
    RT --> PROV
    RT --> TOOLS
    MASTER --> QG
    MASTER --> MEM
    MASTER --> BUS
    TM --> DB
    BUS --> DB
    MEM --> DB
```

## Quick start

### Path 1 — Local install (script)

**Linux / macOS / WSL / Git Bash:**

```bash
git clone https://github.com/rajuferr-sketch/agent-hive.git
cd agent-hive
bash scripts/install.sh     # creates .venv, installs deps, copies .env.example → .env
source .venv/bin/activate
agent-hive init-db
agent-hive start            # API on http://127.0.0.1:8000
```

**Windows PowerShell:**

```powershell
git clone https://github.com/rajuferr-sketch/agent-hive.git
cd agent-hive
.\scripts\install.ps1       # creates .venv, installs deps, copies .env.example → .env
.venv\Scripts\Activate.ps1
agent-hive init-db
agent-hive start
```

> Edit the generated `.env` before starting: set `DATABASE_URL` and, for real AI, `OPENAI_API_KEY`. With `ALLOW_MOCK=true` (the default) the system runs fully offline.

### Path 2 — Docker Compose (PostgreSQL included)

```bash
cp .env.example .env        # fill in OPENAI_API_KEY and POSTGRES_PASSWORD
docker compose up -d --build
# app on http://localhost:8000, db on 5432 (postgres:16-alpine)
```

The compose stack starts `db` (health-checked) and `app` (non-root user, `agent-hive init-db && agent-hive start`).

### Path 3 — From source (dev)

```bash
git clone https://github.com/rajuferr-sketch/agent-hive.git
cd agent-hive
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e ".[dev]"
pytest -q                          # test suite (SQLite, mock mode)
agent-hive diagnose                # environment check
```

### First mission

```bash
agent-hive run "Design a small project management web application with a database, a REST API and unit tests" --mode C --json
```

or via the API:

```bash
curl -X POST http://127.0.0.1:8000/api/missions \
  -H "Content-Type: application/json" \
  -d '{"text": "Design a small project management web application with a database, a REST API and unit tests", "mode": "C"}'
```

## Configuration essentials (`.env`)

Full template: [.env.example](.env.example). Secrets live **only** in `.env` (git-ignored).

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/agent_hive.db` | PostgreSQL in production: `postgresql+asyncpg://user:pass@host:5432/agenthive` |
| `ALLOW_MOCK` | `true` | Permit the deterministic mock fallback. Mock output is **always tagged `[MOCK]`** |
| `LOG_LEVEL` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |
| `CONFIG_DIR` | `./configs` | Location of `system.yaml` + `agents/*.yaml` |
| `WORKSPACE_DIR` | `./workspace` | Sandbox root for agent file tools |
| `MAX_CONCURRENCY` | `8` | Max tasks executed concurrently by the scheduler |
| `DEFAULT_TASK_TIMEOUT` | `120` | Per-task timeout (seconds) |
| `DEFAULT_MAX_RETRIES` | `2` | Automatic retries per task |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | HTTP server bind |
| `ENABLE_FILE_TOOLS` | `false` | Global switch for the `file` tool family |
| `ENABLE_HTTP_TOOLS` | `false` | Global switch for the `http` tool family |
| `OPENAI_API_KEY` | — | Key for OpenAI-compatible endpoints (referenced by *name* in YAML) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for vLLM / LM Studio / LiteLLM / Groq… |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama runtime |

## CLI cheat sheet

| Command | What it does |
|---|---|
| `agent-hive init-db` | Create all database tables |
| `agent-hive start [--host H] [--port P]` | Start the FastAPI server (and the whole hive) |
| `agent-hive run "TEXT" [-m A\|C\|B] [--title T] [--json]` | One-shot mission; prints the deliverable |
| `agent-hive status` | Agent roster + task statistics |
| `agent-hive agents` | List agents, roles, capabilities, provider chains |
| `agent-hive recover` | Reset tasks orphaned by a crash/restart |
| `agent-hive diagnose` | Environment diagnostics (exit code 1 on core failure) |

## API quick examples

```bash
# Full mission (blocking — returns the complete report)
curl -X POST http://127.0.0.1:8000/api/missions \
  -H "Content-Type: application/json" \
  -d '{"text": "Write a fibonacci function with tests", "mode": "A"}'

# Agent roster
curl http://127.0.0.1:8000/api/agents

# Task list / memory / messages
curl "http://127.0.0.1:8000/api/tasks?status=completed"
curl "http://127.0.0.1:8000/api/memory/shared?q=mission"
curl "http://127.0.0.1:8000/api/messages?agent=programmer"

# Issue tracker (triage + agent assignment)
curl -X POST http://127.0.0.1:8000/api/issues \
  -H "Content-Type: application/json" \
  -d '{"title": "Login 500 on prod", "labels": ["bug", "api"], "priority": 2}'
curl -X POST http://127.0.0.1:8000/api/issues/1/assign \
  -H "Content-Type: application/json" -d '{}'

# Pull requests (review + guarded merge)
curl -X POST http://127.0.0.1:8000/api/pulls \
  -H "Content-Type: application/json" \
  -d '{"title": "Fix sqli", "source_branch": "fix/sqli"}'
curl -X POST http://127.0.0.1:8000/api/pulls/1/review \
  -H "Content-Type: application/json" -d '{"reviewer": "agent"}'
curl -X POST http://127.0.0.1:8000/api/pulls/1/merge \
  -H "Content-Type: application/json" -d '{"merged_by": "master"}'

# Agent management (register agent #21+, health, stats)
curl http://127.0.0.1:8000/api/agents/registry
curl -X POST http://127.0.0.1:8000/api/agents/programmer/health
curl http://127.0.0.1:8000/api/agents/programmer/stats

# Live events
# WebSocket: ws://127.0.0.1:8000/ws
```

Full reference: [docs/api.md](docs/api.md).

## The 20-agent roster

Loaded from `configs/agents/*.yaml`; role classes are auto-discovered from `src/agent_hive/agents/roles/`.

| # | Name | Title | Capabilities | Tools |
|---|---|---|---|---|
| 1 | `analyst` | Analysis Agent | analysis, decomposition, requirements | summarize, word_count |
| 2 | `api` | API Agent | api, contract_design, integration | json_validate, code_lint_py |
| 3 | `architect` | Architecture Agent | architecture, scalability, design | json_validate, summarize |
| 4 | `automation` | Automation Agent | automation, deployment, monitoring | code_lint_py, file_write |
| 5 | `database` | Database Agent | database, optimization, architecture | json_validate |
| 6 | `debugger` | Debugging Agent | debugging, profiling, evidence | code_lint_py, regex_extract |
| 7 | `designer` | Design Agent | design, ux, frontend | json_validate |
| 8 | `documenter` | Documentation Agent | documentation, synthesis, quality | summarize, word_count, file_write |
| 9 | `integration` | Integration Agent | integration, coordination, synthesis | json_validate, dedupe_lines |
| 10 | `optimizer` | Optimization Agent | optimization, performance, profiling | word_count, summarize, code_lint_py |
| 11 | `performance` | Performance Agent | performance, profiling, benchmarking | word_count, summarize, code_lint_py |
| 12 | `programmer` | Programming Agent | programming, refactoring, debugging | code_lint_py, file_read, file_write |
| 13 | `qa` | Quality Assurance Agent | quality, validation, review | code_lint_py, secret_scan, summarize, json_validate |
| 14 | `researcher` | Research Agent | research, analysis, synthesis | summarize, word_count, regex_extract |
| 15 | `reviewer` | Review Agent | review, quality, evidence | code_lint_py, secret_scan, summarize, json_validate |
| 16 | `security` | Security Agent | security, threat_modeling, compliance | secret_scan, regex_extract |
| 17 | `tester` | Testing Agent | testing, testing_design, quality | code_lint_py, file_read |
| 18 | `ui` | Frontend Agent | frontend, ux, design | file_write, json_validate |
| 19 | `validator` | Validation Agent | validation, final_check, evidence | code_lint_py, secret_scan, summarize, json_validate |
| 20 | `verifier` | Verification Agent | verification, evidence, consistency | code_lint_py, secret_scan, summarize, json_validate |

Every agent also has its own ordered provider chain (see `configs/agents/*.yaml`) and memory permissions (`individual` / `shared_access` / `shared_write`).

## Operating modes

| Mode | Name | Trigger (complexity 0..1) | Participants | Pipeline |
|---|---|---|---|---|
| **A** | Simple | `< 0.25` (`simple_threshold`) | 1 best-matched agent | single execution |
| **C** | Adaptive | `0.25 – 0.55` (`adaptive_threshold`) | 2–10 agents, one per workstream | workstreams → integration → QA → validation |
| **B** | Collective | `≥ 0.55` (or forced) | all 20 agents | workstreams + individual contributions → cross-review → integration → QA → validation |

Complexity is a heuristic combining request length, domain breadth and multi-part structure (`orchestrator/planner.py`). Thresholds are in `configs/system.yaml` (`simple_threshold: 0.25`, `adaptive_threshold: 0.55`, `complex_threshold: 0.75` is a reserved informational threshold — mode selection uses the first two). Force any mode with `--mode` / `"mode"` in the API.

## Memory tiers

| Tier | Scope | Writes | Behavior |
|---|---|---|---|
| **Individual** | one agent | always (if `memory.individual`) | upsert keyed by (agent, scope, key), versioned |
| **Shared** | whole project | only agents with `memory.shared_write` | versioned upsert; the **previous version is automatically archived to history** |
| **History** | append-only | system + agents | every important outcome recorded; retention pruning via `MemoryManager.prune()` |

Details, conflict strategy and access paths: [docs/memory.md](docs/memory.md).

## Mock mode (honest simulation)

AgentHive runs with `ALLOW_MOCK=true` by default so you can boot it offline, in CI, or before choosing a provider:

- When **all real providers in an agent's chain fail** (or none is configured), the deterministic `MockProvider` answers instead.
- Mock output is **always tagged `[MOCK]`** — in the JSON body (`"tag": "[MOCK]"`) and in the completion metadata (`mock: true`, provider `mock` or `mock(fallback)`). It never pretends to be real AI output.
- Mock responses are deterministic role-aware templates (hash-seeded per input), so memory writes, quality gates, integrations and the whole pipeline are exercised end-to-end.
- Set `ALLOW_MOCK=false` to make the system **fail hard** (`ProviderError`) when no real provider is reachable — recommended for production.
- You can toggle it at runtime: `POST /api/system/settings {"allow_mock": false}`.

## Security notes

- **No secrets in the repo.** API keys are referenced in YAML by *environment variable name* (`api_key_env: OPENAI_API_KEY`); the values live only in your `.env`.
- **Permission-controlled tools.** An agent can only invoke tools listed in its YAML; `file`/`http` tool families are additionally gated by `ENABLE_FILE_TOOLS` / `ENABLE_HTTP_TOOLS`.
- **Sandboxed file access.** `file_read` / `file_write` resolve strictly inside `WORKSPACE_DIR`; escaping paths raise `AgentError`.
- **Deliverables are scanned.** The quality gate rejects outputs containing hard-coded secrets before delivery; secret-scan previews are redacted.
- **Non-root Docker image.** The container runs as the unprivileged `hive` user (uid 1000).
- The Master Agent cannot modify fundamental configuration: `configs/system.yaml` is operator-owned and read-only at runtime (see `configs/master.yaml`).

## Project layout

```text
agent-hive/
├── configs/
│   ├── system.yaml          # orchestration thresholds + quality settings
│   ├── master.yaml          # Master Agent configuration & permissions
│   └── agents/              # 20 agent YAMLs (one per agent)
├── scripts/
│   ├── install.sh / install.ps1   # one-shot installation
│   ├── start.sh / start.ps1       # server launch
│   ├── diagnose.py                # standalone diagnostics
│   └── smoke_test.py              # mock-mode end-to-end check
├── src/agent_hive/
│   ├── hive.py              # composition root (one Hive per process)
│   ├── mcp/                 # MCP server: 18 tools, Streamable HTTP + STDIO
│   ├── gateway/             # Universal AI Gateway
│   ├── universal_memory/    # cross-client persistent shared memory
│   ├── connectors/          # OpenAI-compat, Ollama-compat, WS, generic
│   ├── security/            # tokens, RBAC, rate limit, sanitize, audit
│   ├── github_integration/  # mode-gated GitHub client + security scan
│   ├── selfheal/            # bounded auto-diagnostics loop
│   ├── cli.py               # typer CLI
│   ├── diagnostics.py       # shared environment checks
│   ├── api/                 # FastAPI app + schemas
│   ├── orchestrator/        # master.py, planner.py, quality.py
│   ├── agents/              # base.py, runtime.py, roles/ (20 role modules)
│   ├── tasks/               # manager.py (state machine), scheduler.py
│   ├── memory/              # 3-tier MemoryManager
│   ├── communication/       # persistent MessageBus
│   ├── providers/           # factory + openai_compat / ollama / mock
│   ├── tools/               # permission-checked registry + builtins
│   ├── config/              # settings (env) + YAML loader
│   ├── db/                  # SQLAlchemy 2 async models + engine
│   └── core/                # errors, events, ids, logging
├── data/                    # runtime database (git-ignored)
├── workspace/               # agent file sandbox (git-ignored)
├── docker-compose.yml       # postgres:16-alpine + app
├── Dockerfile               # python:3.12-slim, non-root
├── Makefile                 # install / test / lint / typecheck / docker-*
└── pyproject.toml
```

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Layered architecture, Master Agent walkthrough, task lifecycle, quality gate |
| [docs/api.md](docs/api.md) | Every REST endpoint + WebSocket event format |
| [docs/agents.md](docs/agents.md) | BaseAgent contract, all 20 roles, YAML schema, collaboration |
| [docs/memory.md](docs/memory.md) | Memory tiers, versioning, archival, pruning |
| [docs/providers.md](docs/providers.md) | Provider chains, circuit breaker, custom providers |
| [docs/extending.md](docs/extending.md) | Add agent #21, tools, providers; tuning & scaling |
| [docs/operations.md](docs/operations.md) | Install, PostgreSQL, diagnostics, recovery, troubleshooting |
| [docs/examples.md](docs/examples.md) | 3 end-to-end worked missions + Python SDK usage |

**Universal AI Platform:** [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md) · [`docs/CLAUDE_SETUP.md`](docs/CLAUDE_SETUP.md) · [`docs/CHATGPT_SETUP.md`](docs/CHATGPT_SETUP.md) · [`docs/GEMINI_SETUP.md`](docs/GEMINI_SETUP.md) · [`docs/ZAI_SETUP.md`](docs/ZAI_SETUP.md) · [`docs/OLLAMA_SETUP.md`](docs/OLLAMA_SETUP.md) · [`docs/LOCAL_MODELS.md`](docs/LOCAL_MODELS.md) · [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) · [`docs/SECURITY.md`](docs/SECURITY.md) · [`docs/DOCKER_SETUP.md`](docs/DOCKER_SETUP.md)


## Development

```bash
make install       # runtime install (Linux/macOS) — Windows: scripts\install.ps1
make dev-install   # venv + dev deps
make test          # pytest -q
make lint          # ruff check src tests
make typecheck     # mypy src
make docker-up     # docker compose up -d --build
```

## License

[MIT](LICENSE) © 2026 AgentHive Contributors.
