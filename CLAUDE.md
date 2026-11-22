# CLAUDE.md

**Claude, start here.** The canonical AI guide for this repository is [`AGENTS.md`](AGENTS.md) — read it first (bootstrap protocol, quick start, commands, conventions, guardrails). Then read [`TASKS.md`](TASKS.md) for the currently assigned task. Never skip `TASKS.md`.

TL;DR:

- **AgentHive** = multi-agent orchestration (1 Master Agent + 20 specialized agents), Python 3.10+, FastAPI + SQLAlchemy 2 async, SQLite/PostgreSQL, typer CLI.
- Works fully offline: the deterministic mock provider answers, and its output is always tagged `[MOCK]`.
- Setup & run: `pip install -r requirements.txt && python run.py "request"`.
- Host-chat mode (you are the provider): run with `--chat`, answer JSON files from `./host_requests/` into `./host_responses/` — see [`CHAT.md`](CHAT.md).
- Verify before delivering: `pytest -q` and `ruff check src tests`.
- Secrets only via `.env` (never commit them); agent file tools are sandboxed to `WORKSPACE_DIR` (`./workspace`).
