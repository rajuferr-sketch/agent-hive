# Copilot instructions

**Start from [`AGENTS.md`](../../AGENTS.md)** — it is the canonical guide for AI agents in this repository (bootstrap protocol, quick start, commands, conventions, guardrails). Then read [`TASKS.md`](../../TASKS.md) for the currently assigned task before writing any code.

Core rules:

- **AgentHive** = multi-agent orchestration (1 Master Agent + 20 specialized agents), Python 3.10+, FastAPI + SQLAlchemy 2 async, SQLite/PostgreSQL.
- Runs fully offline via a deterministic mock provider; mock output is always tagged `[MOCK]` — never remove the tag.
- After changes: `pytest -q` and `ruff check src tests` must pass.
- Never commit secrets; providers are referenced by environment-variable *name* (e.g. `OPENAI_API_KEY`) and values live only in `.env` (git-ignored).
- `configs/system.yaml` is operator-owned: do not edit it unless the task explicitly asks.
- Agent file tools resolve strictly inside `WORKSPACE_DIR` (`./workspace`); never write outside it.
