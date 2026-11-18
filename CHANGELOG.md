# Changelog

## [1.0.1] - 2026-11-18
### Fixed
- Task retry accounting (no double increment of `attempts`).
- CLI `diagnose` exit code.
- Integration agent selection (no longer hijacked by `api`).
- Mock results capped in quality gate.
- Type annotations and lint warnings.

### Added
- `run.py` one-command entry point.
- `host` provider for chat-AI-driven missions.
- `AGENTS.md`, `CHAT.md`.
- Optional heavy dependencies (`asyncpg`, `uvicorn`).
- Python 3.10 compatibility.
- Quiet logs by default.
- Markdown output format and `demo` command.
- Code execution check in quality gate.
- `http_get` tool, file write limits, regex timeout.
- CORS and optional API key auth.