# Changelog

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