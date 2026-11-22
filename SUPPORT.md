# Support

## Where to start

| Need | Read |
|---|---|
| Overview, quick start, configuration, CLI/API examples | [README.md](README.md) |
| You are an AI assistant/agent working on this repo | [AGENTS.md](AGENTS.md) → [TASKS.md](TASKS.md) → [AI_CONTEXT.md](AI_CONTEXT.md) |
| Full operational package (providers, deployment, CI, per-AI rules) | [AI_CONTEXT.md](AI_CONTEXT.md) |
| Provider configuration (local and cloud) | [docs/providers.md](docs/providers.md) |
| Docker and production hardening | [docs/deployment.md](docs/deployment.md) |
| Something is broken | [docs/troubleshooting.md](docs/troubleshooting.md) + `python scripts/diagnose.py` |
| Windows setup | [docs/windows.md](docs/windows.md) |

## How to get help

1. **Search the documentation first** — the table above covers most questions; `docs/operations.md` has detailed install/recovery procedures.
2. **Run diagnostics**: `python scripts/diagnose.py` (or `agent-hive diagnose`). Attach the output to your report.
3. **Open an issue** using one of the templates:
   - **Bug report** — something does not work as documented;
   - **Feature request** — proposal for a new capability;
   - **AI task / compito per chat IA** — assign work to an AI chat/agent.
4. **Do not open a public issue for security vulnerabilities** — follow [SECURITY.md](SECURITY.md) instead.

## Scope

AgentHive is an open-source project maintained on a best-effort basis. Issues and pull requests are handled by the maintainer; AI-assisted contributions are welcome when they follow [AGENTS.md](AGENTS.md) and the repository guardrails.
