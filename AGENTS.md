# AGENTS.md — AgentHive

> **Nota per il proprietario (IT):** questo è il punto d'ingresso ufficiale per qualsiasi chat IA o agente di coding (Claude, ChatGPT, Gemini, Copilot, Cursor, Codex…). Flusso previsto: la chat legge questo file → legge `TASKS.md` → esegue il compito affidato. Per assegnare un compito: scrivilo in `TASKS.md` oppure apri una issue con il template "AI task". Il file è in inglese per coerenza con il resto della documentazione della repo; le chat IA lo leggono senza problemi.

This file is the canonical guide for **any AI assistant, chat or coding agent** working on this repository, following the [agents.md](https://agents.md) convention. It is referenced from `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md`, so it is the one file every AI tool reads first.

## 1. Bootstrap protocol — do this first, in order

1. **Read this file completely** before touching any code.
2. **Read [`TASKS.md`](TASKS.md)** — the official queue of assigned tasks. Take the first open task (highest priority first). If the queue is empty but the user gave you a task in the chat, treat the user's message as the task and append it to `TASKS.md` before starting work.
3. **Skim [`README.md`](README.md)** for the big picture. Open `docs/*.md` only for the area you are working on (index in section 10).
4. **Set up and verify the environment** (section 3): the system must run end-to-end in mock mode before you change anything. This proves your environment works and gives you a baseline.
5. **Execute the task** following the conventions (section 7) and guardrails (section 8).
6. **Close the loop**: run `pytest -q` and `ruff check src tests`, update the task status in `TASKS.md`, and report honestly what you did — including anything you did not finish.

## 2. What AgentHive is

AgentHive is a multi-agent orchestration system: **1 Master Agent + 20 specialized agents** that analyze a request, decompose it into a task DAG, collaborate through shared memory and a persistent message bus, and deliver a single quality-gated result.

Key facts an agent must know:

- **Language/stack:** Python 3.10+, FastAPI, SQLAlchemy 2 async, SQLite (default) or PostgreSQL, Pydantic settings, typer CLI.
- **Runs fully offline:** with no API key and no Ollama, a deterministic mock provider answers; its output is always tagged `[MOCK]` and never pretends to be real AI output.
- **Operating modes:** A (simple, 1 agent), C (adaptive, 2–10 agents), B (collective, all 20 agents); chosen by a complexity heuristic or forced with `--mode`.
- **Quality gate:** deliverables must score ≥ 0.7 (completeness, requirements coverage, static AST check of embedded Python, secret scan, leftover-marker detection); up to 2 revision rounds.
- **Database:** SQLite at `./data/agent_hive.db`, created automatically; PostgreSQL via `DATABASE_URL`.
- **No secrets in the repo:** providers are referenced by *environment variable name* in YAML (`api_key_env: OPENAI_API_KEY`); values live only in `.env` (git-ignored).

## 3. Quick start (30 seconds)

```bash
pip install -r requirements.txt   # once
python run.py "your request"      # runs a mission, prints a Markdown report
```

The database is created automatically. With no API key configured, results are deterministic mock output tagged `[MOCK]`.

## 4. Commands

```bash
python run.py "request"                  # run a mission (Markdown report)
python run.py --mode B "request"         # force collective mode (all 20 agents)
python run.py --chat "request"           # host provider mode: YOU answer the agent calls
python run.py demo logistica             # built-in demo (logistics plan)
python run.py demo codice                # built-in demo (Python + pytest)
python -m agent_hive.cli diagnose        # environment diagnostics
python -m agent_hive.cli recover         # reset tasks orphaned by a crash
agent-hive init-db                       # create all DB tables (server path)
agent-hive start                         # FastAPI server on http://127.0.0.1:8000
agent-hive status                        # agent roster + task statistics
agent-hive agents                        # list agents, roles, provider chains

make test        # pytest -q
make lint        # ruff check src tests
make typecheck   # mypy src
```

Full CLI and REST examples: [`README.md`](README.md) and [`docs/api.md`](docs/api.md).

## 5. Host-chat mode — when YOU are the LLM provider

If the user runs `python run.py --chat "request"` (or the `host` provider is selected), AgentHive delegates the actual LLM calls to the chat AI hosting it:

1. AgentHive writes one JSON request file per agent call into `./host_requests/`.
2. You read each request file, produce the answer, and write `./host_responses/<same-id>.json` containing:
   ```json
   {"text": "<the agent's full answer>"}
   ```
3. AgentHive polls for responses, consumes the files (deletes them after reading) and completes the mission, printing a Markdown report.

You can answer requests in any order. Full protocol: [`CHAT.md`](CHAT.md).

## 6. Repository map

```text
agent-hive/
├── AGENTS.md               # this file — AI entry point
├── TASKS.md                # queue of assigned tasks (READ IT FIRST)
├── CHAT.md                 # host-chat provider protocol
├── llms.txt                # machine-readable index for LLMs
├── README.md               # full documentation
├── run.py                  # one-command entry point
├── configs/
│   ├── system.yaml         # orchestration thresholds + quality settings (operator-owned)
│   ├── master.yaml         # Master Agent configuration & permissions
│   └── agents/*.yaml       # 20 agent definitions (YAML)
├── src/agent_hive/
│   ├── hive.py             # composition root (one Hive per process)
│   ├── cli.py              # typer CLI
│   ├── api/                # FastAPI app + schemas
│   ├── orchestrator/       # master.py, planner.py, quality.py
│   ├── agents/             # base.py, runtime.py, roles/ (20 role modules)
│   ├── tasks/              # manager.py (state machine), scheduler.py
│   ├── memory/             # 3-tier MemoryManager
│   ├── communication/      # persistent MessageBus
│   ├── providers/          # openai_compat / ollama / mock + factory
│   ├── tools/              # permission-checked registry + builtins
│   ├── config/             # settings (env) + YAML loader
│   ├── db/                 # SQLAlchemy 2 async models + engine
│   └── core/               # errors, events, ids, logging
├── docs/                   # reference documentation (see section 10)
├── scripts/                # install.sh, start.sh, diagnose.py, smoke_test.py
├── tests/                  # pytest suite (SQLite, mock mode)
├── data/                   # runtime DB (git-ignored)
└── workspace/              # agent file-tool sandbox (git-ignored)
```

## 7. Conventions

- **Python 3.10+** with type hints everywhere; async/await for I/O.
- **Lint:** ruff (`ruff check src tests` must pass). **Types:** mypy (`make typecheck`).
- **Tests:** pytest (`pytest -q`), SQLite + mock mode, no network needed.
- **Adding agents:** drop a YAML in `configs/agents/` and (optionally) a role class in `src/agent_hive/agents/roles/`; role classes are auto-discovered (see [`docs/extending.md`](docs/extending.md)).
- **Config ownership:** orchestration thresholds and quality settings live in `configs/system.yaml`; per-agent config in `configs/agents/*.yaml`.
- **Commits/PRs:** small and focused; describe *what* and *why*; update docs when behavior changes.

## 8. Guardrails — never do this

- **Never commit secrets**, `.env`, keys or tokens. Secrets are referenced by env-var *name* only; values live in `.env` (git-ignored).
- **Never edit `configs/system.yaml`** unless the task explicitly asks: it is operator-owned and read-only at runtime.
- **Never disable or bypass the quality gate**, the secret scan or the `[MOCK]` tagging.
- **Never present mock output as real AI output** — mock results are tagged `[MOCK]` by design; keep the tag.
- **Never write outside the sandbox:** agent file tools resolve strictly inside `WORKSPACE_DIR` (`./workspace` by default); escaping paths raise `AgentError`.
- **Never enable the `file`/`http` tool families** in configs unless the task explicitly requires it (`ENABLE_FILE_TOOLS` / `ENABLE_HTTP_TOOLS`).

## 9. Definition of done

A task is complete when **all** of these hold:

1. The acceptance criteria in the `TASKS.md` entry are met.
2. `pytest -q` passes and `ruff check src tests` is clean.
3. Documentation is updated if behavior or interfaces changed.
4. The task entry in `TASKS.md` is moved to "Compiti completati" with a short result summary.
5. Anything unfinished, skipped or assumed is stated explicitly in your final report.

## 10. Documentation index

| Document | Read it when... |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | You need the layered architecture, Master Agent walkthrough, task lifecycle or quality gate details |
| [`docs/api.md`](docs/api.md) | You work on REST/WebSocket endpoints or clients |
| [`docs/agents.md`](docs/agents.md) | You touch agent roles, YAML schema or collaboration |
| [`docs/memory.md`](docs/memory.md) | You work on the 3-tier memory, versioning or pruning |
| [`docs/providers.md`](docs/providers.md) | You touch provider chains, the circuit breaker, or add a provider |
| [`docs/extending.md`](docs/extending.md) | You add agent #21, tools or providers |
| [`docs/operations.md`](docs/operations.md) | Install problems, PostgreSQL, diagnostics, recovery |
| [`docs/examples.md`](docs/examples.md) | You need worked end-to-end missions or Python SDK usage |
