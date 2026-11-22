# Changelog

## [Unreleased] - 2026-11-23
### Added
- **AI documentation package** ("Parte completa per IA cloud e locale"): `AI_CONTEXT.md` (universal quick start, minimal offline configuration, CLI commands, universal AI rules, preserved structure, package application status, ready-made AI prompt, target end state, ready-to-apply CI spec), `docs/providers.md` extended with local providers (Ollama, LM Studio, vLLM, LiteLLM), cloud providers (OpenAI, Z.AI/GLM, Azure OpenAI, Anthropic, Google Gemini) and the full provider contract, `docs/deployment.md` (Docker workflow + mandatory security checklist), `docs/migrations.md` (PostgreSQL/Alembic plan), `docs/compatibility.md` (per-AI instructions for Claude, ChatGPT/Codex, Z.AI/GLM), `docs/windows.md`, `docs/troubleshooting.md`, `docs/ai-workflow.md` (GitHub methodology, correct modification order).
- Machine-readable entry points for LLMs: `llms-full.txt` (full text of the AI entry documents) and extended `llms.txt` index.
- Community files: `SUPPORT.md`, `.github/CODEOWNERS`, `.github/CODE_OF_CONDUCT.md`, `.github/PULL_REQUEST_TEMPLATE.md`, issue forms `bug_report.yml` and `feature_request.yml`.

### Changed
- `AGENTS.md`: documentation index extended with `AI_CONTEXT.md` and the new package docs; repository map updated; bootstrap step 3 points cloud/local AI chats to `AI_CONTEXT.md`.
- `TASKS.md`: T-001 recorded as completed; T-002 opened for the CI matrix application.

### Fixed
- **Python 3.10 compatibility in the scheduler:** `asyncio.wait_for` raises `asyncio.TimeoutError`, which coincides with the builtin `TimeoutError` only on Python 3.11+; on 3.10 the three `except TimeoutError` handlers in `src/agent_hive/tasks/scheduler.py` never matched, breaking the scheduler loop/stop paths and failing `tests/test_missions_e2e.py` (2 failed + 2 teardown errors, ~183 s run). The handlers now catch `asyncio.TimeoutError` (no behavior change on 3.11+). Found and verified by a local CI simulation on Python 3.10/3.11/3.12 (T-003 in `TASKS.md`).
- **Lint job red:** missing trailing newline (W292) in `tests/test_router.py` made `ruff check src tests` fail.

### Pending
- CI cross-platform matrix (ubuntu/windows/macos x Python 3.10/3.11/3.12) + `typecheck` (mypy) job: spec ready in `AI_CONTEXT.md` (section 12), to be applied manually to `.github/workflows/ci.yml` (the integration in use lacks the `workflows` permission) — tracked as T-002 in `TASKS.md`.

## [1.1.0] - 2026-11-19
### Added
- **Issues subsystem** (`agent_hive.issues`): GitHub-style issue tracker with sequential numbering, lifecycle state machine (`open → in_progress → blocked → resolved → closed` + reopen), labels, priorities, threaded comments, manual assignment or capability-based best-match assignment (`assign_best`), task linking, and status counters. REST endpoints under `/api/issues`.
- **Pull requests subsystem** (`agent_hive.pulls`): PR lifecycle (`open → changes_requested → approved → merged/closed` + reopen), per-agent review records with verdicts (`approve` / `request_changes` / `comment`), GitHub-style review aggregation, **guarded merge** (only approved PRs can land), and agent-driven review (`agent_review` delegates to the hive `reviewer` agent). REST endpoints under `/api/pulls`.
- **Agent management subsystem** (`agent_hive.agents.manager.AgentManager`): DB-backed registry view, disable/enable (hot unload/reload without restart), runtime registration of agent #21+ from a YAML spec (persisted to `configs/agents/`), provider-chain health probes, per-agent workload statistics. REST endpoints under `/api/agents/registry`, `/api/agents/{name}/enable|disable|health|stats`.
- New ORM models: `issues`, `issue_comments`, `pull_requests`, `pr_reviews` (schema auto-created by `create_all`).
- New API schemas: `IssueCreate`, `IssueCommentCreate`, `IssueAssign`, `IssueStatus`, `PullRequestCreate`, `PullRequestReviewCreate`, `PullRequestMerge`, `AgentRegister`.
- New tests: `test_issues.py`, `test_pulls.py`, `test_agents_manager.py` (+21 tests).
- Single source of truth for the version (`agent_hive/version.py` reused by the API and the Hive status).

### Changed
- `Hive` wires the three new managers (`hive.issues`, `hive.pulls`, `hive.agents_manager`).
- Route ordering: static `/api/agents/registry` endpoints are registered before the dynamic `/api/agents/{name}` routes to avoid path shadowing.

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
