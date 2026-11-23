# MCP Setup — AgentHive as a Model Context Protocol server

AgentHive implements the MCP tool-server surface **without any third-party
SDK**: JSON-RPC 2.0 over two transports — **Streamable HTTP** (remote) and
**STDIO** (local). It exposes exactly **18 tools**, the same set every other
connector exposes.

Verified in this repository by the test suite (`tests/test_mcp_server.py`,
224 tests green on Python 3.10/3.11/3.12), including the mandatory
**UNIVERSAL MCP TOOL EXECUTION TEST**: initialize → tools/list → read schema →
execute → structured result → error handling → ping → clean session close.

## Protocol facts (what a client can rely on)

| Item | Value |
| --- | --- |
| Protocol version negotiated | `2025-03-26` (falls back from unsupported requests) |
| Transports | Streamable HTTP at `POST /mcp`, STDIO via `agent-hive mcp` |
| Session handling | `Mcp-Session-Id` response header on `initialize`, echoed by the client; `DELETE /mcp` ends the session |
| Notifications | answered with `202 Accepted`, no body |
| SSE | honored when the client sends `Accept: text/event-stream` only |
| Tool errors | returned as results with `isError: true` + `structuredContent` |
| Protocol errors | JSON-RPC `-32601` (method not found), `-32602` (invalid params), `-32700` (parse), `-32600`, `-32603` |
| Batch messages | supported (single or list) |

## The 18 tools

`agent_list`, `agent_status`, `agent_execute`, `agent_create_task`,
`agent_assign_task`, `agent_cancel_task`, `agent_monitor_task`,
`agent_get_result`, `agent_get_history`, `agent_search_memory`,
`agent_save_memory`, `agent_update_memory`, `agent_get_system_status`,
`agent_run_diagnostics`, `agent_run_tests`, `agent_generate_report`,
`agent_manage_workflow`, `agent_get_capabilities`.

Every tool declares: unique name, precise description, JSON-schema input
validation, a required permission scope, a configurable timeout
(`MCP_TOOL_TIMEOUT`, per-call override where meaningful), structured
`{ok, data|error}` responses, logging and audit records.

### Quick reference

| Tool | Scope | What it does |
| --- | --- | --- |
| `agent_execute` | `agents:execute` | Natural-language mission: Master Agent plans → delegates → parallel execution → QA gate → deliverable |
| `agent_save_memory` / `agent_search_memory` / `agent_update_memory` | `memory:write` / `memory:read` | Cross-client persistent shared memory (5 memory types, full-text + vector search, TTL, dedup, versioning) |
| `agent_create_task`, `agent_assign_task`, `agent_cancel_task` | `tasks:*` | Direct task management without the Master |
| `agent_monitor_task`, `agent_get_result`, `agent_get_history` | `tasks:read` | Observe task/mission state |
| `agent_list`, `agent_status`, `agent_get_capabilities` | `agents:read` / `system:read` | Roster, health, discovery |
| `agent_get_system_status`, `agent_run_diagnostics` | `system:read` / `system:diagnose` | System + subsystem health (DB, scheduler, memory, providers) |
| `agent_run_tests` | `system:tests` | Runs pytest in a bounded subprocess |
| `agent_generate_report` | `reports:read` | Markdown report (system or per-mission) |
| `agent_manage_workflow` | `workflows:manage` | Create/status/cancel a task DAG |

## Streamable HTTP (remote clients)

```bash
# start the API server (MCP is mounted at /mcp)
agent-hive start           # or: docker compose up -d

# 1) initialize — the response carries Mcp-Session-Id
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H "Authorization: Bearer $AGENT_HIVE_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-03-26","clientInfo":{"name":"my-client","version":"0"}}}'

# 2) use the session id from the response header
curl -s -X POST http://localhost:8000/mcp \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 3) call a tool
curl -s -X POST http://localhost:8000/mcp \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"agent_save_memory","arguments":{
          "memory_type":"task","key":"kickoff","content":"project started"}}}'
```

Authentication: send `Authorization: Bearer <token>`; the identity is bound
to the MCP session at `initialize` time and enforced per tool call. In
**local-trust mode** (no `API_MASTER_TOKEN`, no issued tokens) the session
gets full scopes — see `docs/SECURITY.md` for the trust model.

## STDIO (local clients)

```bash
agent-hive mcp        # JSON-RPC lines on stdin → stdout; logs on stderr
```

STDIO sessions are locally trusted (the client spawned the process on your
machine) and get full scopes. EOF on stdin ends the server cleanly.

## Claude Desktop (STDIO)

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agent-hive": {
      "command": "agent-hive",
      "args": ["mcp"]
    }
  }
}
```

If you installed from source instead of pip, use the venv python:

```json
{
  "mcpServers": {
    "agent-hive": {
      "command": "/path/to/agent-hive/.venv/bin/python",
      "args": ["-m", "agent_hive", "mcp"],
      "cwd": "/path/to/agent-hive"
    }
  }
}
```

Restart Claude Desktop → the `agent-hive` server appears with 18 tools.
> Claim discipline: this configuration follows the documented Claude Desktop
> connector format; it was validated locally by driving the same STDIO
> protocol with an automated client (`test_stdio_transport_end_to_end`), not
> by hand-testing inside the Claude Desktop app.

## Remote MCP clients (HTTP)

Point any MCP-over-HTTP client at `http://<host>:8000/mcp` with a Bearer
token. Claude Desktop's remote-connector option, LibreChat MCP config and
generic MCP bridges all speak this wire format.

## Verifying your installation

```bash
curl -s http://localhost:8000/api/universal/tools | python -m json.tool
# → {"tools": [...18 entries...], "count": 18, "transports": [...]}
```

or run the repo test suite: `pytest tests/test_mcp_server.py -q`.
