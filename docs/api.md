# API Reference

AgentHive exposes a FastAPI application (default `http://127.0.0.1:8000`) with REST endpoints and a WebSocket live-event feed. Interactive OpenAPI docs are served at `/docs` and `/redoc`.

All examples assume the server is running (`agent-hive start`).

## Endpoints overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/system/status` | Aggregate system status + task statistics |
| POST | `/api/system/settings` | Toggle runtime settings (mock mode) |
| POST | `/api/missions` | Delegate a full mission to the Master Agent |
| GET | `/api/missions/{mission_id}` | Mission summary (task list) |
| POST | `/api/tasks` | Enqueue a single task (bypasses the Master) |
| GET | `/api/tasks` | List tasks (filter by status/mission) |
| GET | `/api/tasks/{task_id}` | Task detail incl. result |
| POST | `/api/tasks/{task_id}/cancel` | Cancel a task |
| GET | `/api/agents` | Agent roster + capabilities |
| GET | `/api/agents/registry` | DB-backed agent registry (persistent) |
| POST | `/api/agents/registry` | Register agent #21+ at runtime (no restart) |
| POST | `/api/agents/{name}/enable` | (Re)load an agent into the runtime |
| POST | `/api/agents/{name}/disable` | Unload an agent from the runtime |
| GET | `/api/agents/{name}/health` | Provider-chain health probe |
| GET | `/api/agents/{name}/stats` | Per-agent workload counters |
| GET | `/api/messages` | Message history |
| GET | `/api/memory/{scope}` | Read/search memory |
| POST | `/api/memory/shared` | Write to shared memory |
| POST | `/api/issues` | Open an issue |
| GET | `/api/issues` | List/filter issues (status/assignee/label) |
| GET | `/api/issues/{id}` | Issue detail incl. comments (id or number) |
| POST | `/api/issues/{id}/comments` | Comment on an issue |
| POST | `/api/issues/{id}/assign` | Assign to an agent (or best-match) |
| POST | `/api/issues/{id}/status` | Transition the issue lifecycle |
| GET | `/api/issues/stats/summary` | Issue counters by status |
| POST | `/api/pulls` | Open a pull request |
| GET | `/api/pulls` | List/filter pull requests (status/author) |
| GET | `/api/pulls/{id}` | PR detail incl. reviews (id or number) |
| POST | `/api/pulls/{id}/review` | Record a review (`"reviewer": "agent"` delegates to the reviewer agent) |
| POST | `/api/pulls/{id}/merge` | Merge (only from `approved`) |
| GET | `/api/pulls/stats/summary` | PR counters by status |
| WS | `/ws` | Live event stream |

---

## System

### `GET /health`

```bash
curl http://127.0.0.1:8000/health
```

```json
{ "status": "ok" }
```

### `GET /system/status`

```bash
curl http://127.0.0.1:8000/system/status
```

```json
{
  "version": "1.0.0",
  "agents_loaded": 20,
  "agent_names": ["analyst", "api", "architect", "automation", "database", "debugger", "designer", "documenter", "integration", "optimizer", "performance", "programmer", "qa", "researcher", "reviewer", "security", "tester", "ui", "validator", "verifier"],
  "mock_allowed": true,
  "database": "postgresql",
  "config": {
    "simple_threshold": 0.25,
    "adaptive_threshold": 0.55,
    "complex_threshold": 0.75,
    "qa_required_score": 0.7
  },
  "task_stats": { "completed": 12, "queued": 2, "running": 1 }
}
```

### `POST /api/system/settings`

Toggle mock mode at runtime (no restart needed).

```bash
curl -X POST http://127.0.0.1:8000/api/system/settings \
  -H "Content-Type: application/json" \
  -d '{"allow_mock": false}'
```

```json
{ "allow_mock": false }
```

---

## Missions

### `POST /api/missions`

Delegates the request to the Master Agent and **blocks** until the mission is fully processed (planning → delegation → monitoring → integration → quality gate → optional revisions). Long missions can take minutes; poll `/api/missions/{id}` or watch `/ws` if you prefer.

Request body (`MissionRequest`):

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `text` | string | 5–20 000 chars | The user request (required) |
| `mode` | string? | `A` \| `C` \| `B` | Force the operating mode (optional) |
| `title` | string? | ≤ 200 chars | Mission title (optional; defaults to the first 70 chars of `text`) |

```bash
curl -X POST http://127.0.0.1:8000/api/missions \
  -H "Content-Type: application/json" \
  -d '{"text": "Write a fibonacci function with unit tests", "mode": "A", "title": "Fibonacci"}'
```

Response (trimmed):

```json
{
  "mission_id": "9f2c1a7b8d4e4f60a1b2c3d4e5f60718",
  "title": "Fibonacci",
  "mode": "A",
  "complexity": 0.12,
  "domains": ["code"],
  "agents": ["programmer"],
  "tasks": [
    { "id": "b1e4...", "title": "Single-agent execution", "agent": "programmer", "status": "completed", "attempts": 1 }
  ],
  "outcome": { "completed": 1, "failed": 0, "cancelled": 0, "total": 1 },
  "deliverable": "…final deliverable text…",
  "deliverable_by": "programmer",
  "conflicts": [],
  "quality": {
    "passed": true,
    "score": 0.95,
    "findings": [
      { "check": "completeness", "ok": true, "detail": "1240 chars" },
      { "check": "requirements", "ok": true, "detail": "keyword coverage 100% (6/6)" },
      { "check": "code_block_0", "ok": true, "detail": "syntax OK" },
      { "check": "secrets", "ok": true, "detail": "clean" },
      { "check": "markers", "ok": true, "detail": "none" }
    ]
  },
  "revision_rounds": 0,
  "completed_at": "2026-11-15T10:24:31+00:00"
}
```

### `GET /api/missions/{mission_id}`

Poll a mission: returns the per-task status. Returns **404** before any task with that `mission_id` exists.

```bash
curl http://127.0.0.1:8000/api/missions/9f2c1a7b8d4e4f60a1b2c3d4e5f60718
```

```json
{
  "mission_id": "9f2c1a7b8d4e4f60a1b2c3d4e5f60718",
  "tasks": [
    { "id": "b1e4…", "title": "Single-agent execution", "agent": "programmer",
      "status": "completed", "attempts": 1, "error": null },
    { "id": "c7d2…", "title": "Integrate contributions", "agent": "integration",
      "status": "running", "attempts": 1, "error": null }
  ]
}
```

Typical polling loop (bash):

```bash
MISSION_ID=$(curl -s http://127.0.0.1:8000/api/missions/9f2c1a7b8d4e4f60a1b2c3d4e5f60718 | jq -r '.tasks | map(select(.status != "completed" and .status != "failed" and .status != "cancelled")) | length')
# repeat until every task is terminal
```

---

## Tasks

### `POST /api/tasks`

Enqueue a single task directly (bypasses the Master Agent). The scheduler picks it up within one poll interval and assigns the best-capability agent when `agent_name` is omitted.

```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Summarize the README",
    "description": "Produce a 5-sentence extractive summary",
    "payload": {"capabilities_hint": ["documentation"]},
    "priority": 3
  }'
```

```json
{ "id": "a3f9c2e1b7d84a2f9c3d1e5b7a9c0e21", "status": "queued" }
```

### `GET /api/tasks?status=&mission_id=&limit=`

```bash
curl "http://127.0.0.1:8000/api/tasks?status=completed&limit=50"
```

```json
[
  { "id": "b1e4…", "title": "Single-agent execution", "agent": "programmer",
    "status": "completed", "priority": 2, "attempts": 1,
    "mission_id": "9f2c…" }
]
```

### `GET /api/tasks/{task_id}`

Full detail including the stored result payload.

```json
{
  "id": "b1e4…",
  "title": "Single-agent execution",
  "description": "Complete the request independently with the best-matched agent.",
  "status": "completed",
  "agent": "programmer",
  "attempts": 1,
  "max_retries": 2,
  "result": {
    "agent": "programmer", "role": "programmer", "title": "Programming Agent",
    "text": "…completion text…",
    "data": {}, "self_check": {"passed": true, "notes": []},
    "provider": "openai_compatible", "model": "gpt-4o-mini", "mock": false
  },
  "error": null,
  "depends_on": [],
  "mission_id": "9f2c…"
}
```

### `POST /api/tasks/{task_id}/cancel`

```json
{ "id": "b1e4…", "status": "cancelled" }
```

Returns **409** when the task is already terminal (completed/failed/cancelled) or missing.

---

## Agents

### `GET /api/agents`

```bash
curl http://127.0.0.1:8000/api/agents | jq '.[0]'
```

```json
{
  "name": "programmer",
  "title": "Programming Agent",
  "role": "programmer",
  "description": "Implements production-quality Python solutions as runnable code blocks.",
  "capabilities": ["debugging", "programming", "refactoring"],
  "tools": ["code_lint_py", "file_read", "file_write"],
  "providers": [
    { "provider": "openai_compatible", "model": "gpt-4o-mini" },
    { "provider": "ollama", "model": "llama3.2" },
    { "provider": "mock", "model": "mock-1" }
  ],
  "busy": false,
  "memory": { "individual": true, "shared_access": true, "shared_write": true }
}
```

### `GET /api/agents/{name}`

Agent detail plus the 20 most recent individual memory entries:

```json
{
  "name": "analyst",
  "role": "analyst",
  "recent_memories": [
    { "key": "task:b1e4…", "version": 3, "updated_at": "2026-11-15 10:20:11.402+00:00" }
  ]
}
```

**404** if the agent name is unknown.

### `POST /api/agents/{name}/message`

Inject a message into an agent's inbox (it will be included in the next task's context). Use `*` as the target name to broadcast to every registered mailbox.

```bash
curl -X POST http://127.0.0.1:8000/api/agents/programmer/message \
  -H "Content-Type: application/json" \
  -d '{"from_agent": "master", "kind": "request", "content": {"subject": "Style guide", "detail": "Prefer dataclasses over dicts"}, "priority": 2}'
```

```json
{ "id": "m9c2…", "to": "programmer", "kind": "request" }
```

`kind` must be one of `info | request | response | assistance | problem | proposal | challenge | review`.

---

## Messages

### `GET /api/messages?agent=&task_id=&limit=`

Persistent message-bus history.

```bash
curl "http://127.0.0.1:8000/api/messages?agent=programmer&limit=5"
```

```json
[
  { "id": "m1…", "from": "master", "to": "*",
    "kind": "info",
    "content": {"subject": "Mission 9f2c… started", "detail": "Fibonacci", "agents": ["programmer"]},
    "created_at": "2026-11-15 10:20:08.112+00:00" }
]
```

---

## Memory

### `GET /api/memory/{scope}?q=&agent=&limit=`

`scope` must be `individual` | `shared` | `history` (otherwise **422**). `q` performs a substring search over keys and JSON values; `agent` filters individual memory.

```bash
curl "http://127.0.0.1:8000/api/memory/shared?q=mission"
curl "http://127.0.0.1:8000/api/memory/individual?agent=programmer"
curl "http://127.0.0.1:8000/api/memory/history?limit=20"
```

```json
[
  { "key": "mission:9f2c…",
    "value": {"title": "Fibonacci", "mode": "A", "requirements": ["fibonacci", "function", "tests"]},
    "version": 1, "agent": null, "scope": "shared",
    "updated_at": "2026-11-15 10:20:08.100+00:00" }
]
```

### `POST /api/memory/shared`

Write (or version-bump) a shared-memory entry. If the key exists, the previous value is automatically archived to history and `version` increments.

```bash
curl -X POST http://127.0.0.1:8000/api/memory/shared \
  -H "Content-Type: application/json" \
  -d '{"key": "style:python", "value": {"rule": "prefer dataclasses"}, "author": "master", "tags": ["style"]}'
```

```json
{ "key": "style:python", "version": 2 }
```

---

## Issues

GitHub-style issue tracker integrated with the hive: issues can be commented on and assigned to agents (manually or by capability matching against labels).

### `POST /api/issues`

```bash
curl -X POST http://127.0.0.1:8000/api/issues \
  -H "Content-Type: application/json" \
  -d '{"title": "Login endpoint returns 500", "description": "Stack trace in logs", "labels": ["bug", "api"], "priority": 2}'
```

```json
{ "id": "3f6c…", "number": 1, "title": "Login endpoint returns 500", "status": "open", "priority": 2, "labels": ["bug", "api"], "assignee": null, … }
```

### Issue lifecycle

`open → in_progress → blocked → resolved → closed` (reopen allowed from `closed`/`resolved`). Illegal transitions return HTTP 409.

### `POST /api/issues/{id}/assign`

```bash
# manual assignment
curl -X POST http://127.0.0.1:8000/api/issues/{id}/assign \
  -H "Content-Type: application/json" -d '{"agent_name": "security"}'

# capability-based triage: labels are mapped to capabilities (bug→debugging,
# security→security, performance→performance, …) and the best agent is picked
curl -X POST http://127.0.0.1:8000/api/issues/{id}/assign \
  -H "Content-Type: application/json" -d '{}'
```

Assignment moves an `open` issue to `in_progress`.

### Other issue endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/issues?status=open&assignee=&label=` | List/filter (`status=open` means any non-terminal state) |
| GET | `/api/issues/{id}` | Detail with comments — accepts the UUID **or** the sequential number |
| POST | `/api/issues/{id}/comments` | `{"body": "reproduced on main", "author": "tester"}` |
| POST | `/api/issues/{id}/status` | `{"status": "resolved"}` |
| GET | `/api/issues/stats/summary` | Counters by status + `open_total` |

---

## Pull requests

PR lifecycle with agent reviews and a guarded merge. Statuses: `open → changes_requested → approved → merged` (or `closed`, reopenable if not merged).

### `POST /api/pulls`

```bash
curl -X POST http://127.0.0.1:8000/api/pulls \
  -H "Content-Type: application/json" \
  -d '{"title": "Fix SQL injection in search", "source_branch": "fix/sqli", "files_changed": ["src/search.py"], "related_issue_ids": ["3f6c…"]}'
```

### Reviews and aggregation

```bash
curl -X POST http://127.0.0.1:8000/api/pulls/{id}/review \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "reviewer", "verdict": "approve", "score": 0.9, "summary": "Clean fix, tests included"}'
```

Aggregation follows GitHub semantics: any `request_changes` verdict ⇒ `changes_requested`; at least one `approve` with none ⇒ `approved`; comment-only reviews do not change the status.

**Agent-driven review** — let the hive's `reviewer` agent produce the verdict:

```bash
curl -X POST http://127.0.0.1:8000/api/pulls/{id}/review \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "agent"}'
```

### Guarded merge

```bash
curl -X POST http://127.0.0.1:8000/api/pulls/{id}/merge \
  -H "Content-Type: application/json" -d '{"merged_by": "master"}'
```

Merging is only allowed from `approved` — any other state returns HTTP 409, so an un-reviewed or rejected PR can never land. A merged PR is terminal (cannot be closed or re-reviewed).

### Other PR endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/pulls?status=open&author=` | List/filter (`status=open` means not merged/closed yet) |
| GET | `/api/pulls/{id}` | Detail with reviews — accepts the UUID **or** the sequential number |
| POST | `/api/pulls/{id}/close` | Close the PR (refused if already merged) |
| POST | `/api/pulls/{id}/reopen` | Reopen a closed PR (reviews are preserved) |
| GET | `/api/pulls/stats/summary` | Counters by status |

---

## Agent management

Operator surface over the agent runtime: persistent registry, hot enable/disable, runtime registration of new agents (agent #21+), provider health probes and workload stats.

### `GET /api/agents/registry`

DB-backed view (the `agents` table, upserted at every heartbeat):

```json
{ "name": "programmer", "role": "programmer", "status": "idle", "capabilities": ["programming", "refactoring", "debugging"], "provider_chain": [{"provider": "openai_compatible", "model": "gpt-4o-mini"}, …], "last_heartbeat": "…", "in_runtime": true }
```

### `POST /api/agents/registry` — register agent #21+ at runtime

```bash
curl -X POST http://127.0.0.1:8000/api/agents/registry \
  -H "Content-Type: application/json" \
  -d '{
    "name": "botanist", "title": "Botany Agent", "role": "researcher",
    "description": "Domain expert for plant-related questions",
    "capabilities": ["botany", "analysis"], "tools": ["summarize", "word_count"],
    "providers": [{"type": "openai_compatible", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}, {"type": "mock"}],
    "memory": {"individual": true, "shared_access": true, "shared_write": false}
  }'
```

The spec is validated (role must exist, providers required), persisted to `configs/agents/<name>.yaml` and immediately loaded into the runtime — no restart needed. The new agent can be used by missions right away.

### Enable / disable / health / stats

```bash
curl -X POST http://127.0.0.1:8000/api/agents/optimizer/disable   # unload (YAML kept)
curl -X POST http://127.0.0.1:8000/api/agents/optimizer/enable    # hot reload
curl http://127.0.0.1:8000/api/agents/programmer/health           # probe every provider in the chain
curl http://127.0.0.1:8000/api/agents/programmer/stats            # task counters per status
```

---

## WebSocket `/ws`

Live stream of every `EventBus` event as JSON text frames:

```json
{
  "kind": "task.completed",
  "actor": "programmer",
  "ts": "2026-11-15T10:20:31.881000+00:00",
  "data": { "task_id": "b1e4…" }
}
```

Event kinds you will observe include `hive.started`, `mission.started`, `mission.completed`, `task.created`, `task.status`, `task.running`, `task.completed`, `task.failed`, `tasks.recovered`, `agent.task_done`, `runtime.started`, `runtime.stopped`, and `quality.verified`.

Quick client check (Python):

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        async for raw in ws:
            event = json.loads(raw)
            print(event["kind"], event["actor"], event["data"])

asyncio.run(main())
```

---

## Error codes

| Status | When | Example body |
|---|---|---|
| **403** | A `PermissionDenied` occurs (e.g. a tool invocation outside an agent's permissions reaches the API surface) | `{"detail": "Agent 'analyst' is not authorized to use tool 'file_write'"}` |
| **404** | Unknown mission, task or agent | `{"detail": "Task not found"}` |
| **409** | Task not cancellable (already terminal) | `{"detail": "Task not cancellable"}` |
| **422** | Request validation failure (FastAPI/pydantic, invalid `mode`, empty/too-short mission text, bad memory scope) | `{"detail": "scope must be individual\|shared\|history"}` |
| **500** | Internal `AgentError` during mission execution | `{"detail": "ProviderError: All providers failed: …"}` |

Validation errors from pydantic follow the standard FastAPI shape (`{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`), e.g. submitting `"mode": "D"` or a `text` shorter than 5 characters.
