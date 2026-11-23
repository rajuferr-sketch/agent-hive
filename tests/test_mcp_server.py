"""MCP server tests — protocol, schema validation, transports and errors.

Covers:
* JSON-schema subset validator behaviour;
* JSON-RPC core: initialize negotiation, tools/list, tools/call, ping,
  notification handling, protocol errors;
* HTTP (Streamable) transport over ASGI incl. session headers;
* real STDIO transport via a subprocess running ``python -m agent_hive mcp``;
* the mandatory **UNIVERSAL MCP TOOL EXECUTION TEST** (end-to-end session).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from agent_hive.mcp.schema import SchemaError, validate_schema
from agent_hive.mcp.server import MCPServerCore
from agent_hive.mcp.tools import MANIFEST_NAMES, get_registry
from agent_hive.security.tokens import TokenIdentity

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _admin() -> TokenIdentity:
    return TokenIdentity(token_id="t", subject="test", role="admin", scopes=["*"])


# ------------------------------------------------------------- schema tests


def test_schema_validates_objects() -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 1, "maximum": 9},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    validate_schema({"name": "x", "count": 3, "tags": ["a"]}, schema)
    with pytest.raises(SchemaError):
        validate_schema({}, schema)  # missing required
    with pytest.raises(SchemaError):
        validate_schema({"name": "x", "count": 0}, schema)  # below minimum
    with pytest.raises(SchemaError):
        validate_schema({"name": "x", "extra": 1}, {"type": "object",
                        "properties": {"name": {"type": "string"}},
                        "additionalProperties": False})


def test_schema_rejects_wrong_types() -> None:
    with pytest.raises(SchemaError):
        validate_schema("not-an-int", {"type": "integer"})
    with pytest.raises(SchemaError):
        validate_schema(True, {"type": "string"})
    validate_schema(3, {"type": ["string", "integer"]})  # union types allowed


# ------------------------------------------------------------ protocol tests


@pytest.fixture
def core() -> MCPServerCore:
    from agent_hive.hive import Hive
    from agent_hive.mcp.tools import ToolContext

    hive = Hive()

    async def factory(session):  # noqa: ANN001
        return ToolContext(hive=hive, umemory=hive.umemory, identity=_admin(),
                           client="test")

    return MCPServerCore(
        registry=get_registry(),
        ctx_factory=factory,
        server_version="test",
    )


async def test_initialize_negotiates_protocol(core: MCPServerCore) -> None:
    session = core.create_session()
    response = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26",
                       "clientInfo": {"name": "test-client", "version": "0"}},
        }),
        session,
    )
    assert response["result"]["protocolVersion"] == "2025-03-26"
    assert response["result"]["serverInfo"]["name"] == "agent-hive"
    assert "tools" in response["result"]["capabilities"]


async def test_unsupported_version_falls_back(core: MCPServerCore) -> None:
    session = core.create_session()
    response = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "1999-01-01"}}),
        session,
    )
    assert response["result"]["protocolVersion"] == "2025-03-26"


async def test_tools_list_exposes_18_unique_tools(core: MCPServerCore) -> None:
    session = core.create_session()
    response = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), session
    )
    tools = response["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)) == 18
    assert set(names) == set(MANIFEST_NAMES)
    for tool in tools:
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"


async def test_tools_call_invalid_params_is_error_result(core: MCPServerCore) -> None:
    session = core.create_session()
    session.identity = _admin()
    response = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "agent_save_memory", "arguments": {"key": ""}},
        }),
        session,
    )
    result = response["result"]
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["error"]["code"] == "invalid_params"


async def test_tools_call_unknown_tool(core: MCPServerCore) -> None:
    session = core.create_session()
    session.identity = _admin()
    response = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        }),
        session,
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "unknown_tool"
    assert response["result"]["isError"] is True


async def test_unknown_method_returns_method_not_found(core: MCPServerCore) -> None:
    session = core.create_session()
    response = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "resources/list"}), session
    )
    assert response["error"]["code"] == -32601


async def test_notification_returns_none_and_ping(core: MCPServerCore) -> None:
    session = core.create_session()
    notification = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        session,
    )
    assert notification is None
    ping = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": 6, "method": "ping"}), session
    )
    assert ping["result"] == {}


async def test_tool_timeout_is_bounded() -> None:
    """A slow handler is cut by the registry timeout, never hangs the session."""
    import asyncio as aio

    from agent_hive.mcp.tools import ToolSpec, build_registry

    async def _slow(_ctx, _args):  # noqa: ANN001, ANN202
        await aio.sleep(5)

    local_registry = build_registry()
    local_registry.register(ToolSpec(
        name="_test_slow_tool", description="slow", schema={"type": "object"},
        scope="system:read", timeout_s=1, handler=_slow,
    ))

    async def _factory(_session):  # noqa: ANN001, ANN202
        from agent_hive.mcp.tools import ToolContext

        return ToolContext(hive=None, umemory=None, identity=_admin(), client="t")

    core = MCPServerCore(registry=local_registry, ctx_factory=_factory,
                         server_version="t")
    session = core.create_session()
    session.identity = _admin()
    response = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "_test_slow_tool", "arguments": {}},
        }),
        session,
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "timeout"


async def test_scope_denied_without_permission(core: MCPServerCore) -> None:
    session = core.create_session()
    session.identity = TokenIdentity(
        token_id="ro", subject="reader", role="readonly", scopes=["system:read"]
    )
    response = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "agent_save_memory",
                       "arguments": {"memory_type": "semantic", "key": "k",
                                     "content": "c"}},
        }),
        session,
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "permission_denied"


# ----------------------------------------------------------- HTTP transport


@pytest.fixture
async def http_client(hive):  # noqa: ANN201
    """ASGI client bound to a real Hive-driven app (no server process)."""
    from fastapi import FastAPI

    from agent_hive.mcp.http import build_mcp_router
    from agent_hive.mcp.tools import ToolContext

    async def _ctx_factory_http(session):  # noqa: ANN001
        return ToolContext(
            hive=hive, umemory=hive.umemory,
            identity=session.identity, client="mcp-http",
        )

    async def _resolver(_request):  # noqa: ANN001, ANN202
        return _admin()

    probe_app = FastAPI()
    core = MCPServerCore(
        registry=get_registry(), ctx_factory=_ctx_factory_http, server_version="test"
    )
    probe_app.include_router(build_mcp_router(core, _resolver))
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=probe_app)
    yield AsyncClient(transport=transport, base_url="http://test")


async def test_http_transport_full_session(http_client) -> None:  # noqa: ANN001
    """Streamable HTTP: initialize → session header → tools → call → delete."""
    init = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "clientInfo": {"name": "http"}}},
        headers={"Accept": "application/json"})
    assert init.status_code == 200
    session_id = init.headers["mcp-session-id"]
    assert init.json()["result"]["serverInfo"]["name"] == "agent-hive"

    # notification → 202, no body
    notif = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Mcp-Session-Id": session_id})
    assert notif.status_code == 202

    # request without session → 404 (must re-initialize)
    ghost = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert ghost.status_code == 404

    listing = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Mcp-Session-Id": session_id})
    assert len(listing.json()["result"]["tools"]) == 18

    # a real execution over HTTP: system status
    call = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "agent_get_system_status", "arguments": {}}},
        headers={"Mcp-Session-Id": session_id})
    payload = json.loads(call.json()["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["data"]["agents_loaded"] > 0

    # SSE-only client gets an event-stream response
    sse = await http_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 4, "method": "ping"},
        headers={"Mcp-Session-Id": session_id, "Accept": "text/event-stream"})
    assert sse.status_code == 200
    assert sse.headers["content-type"].startswith("text/event-stream")
    assert "data:" in sse.text

    # explicit termination
    deleted = await http_client.delete("/mcp", headers={"Mcp-Session-Id": session_id})
    assert deleted.status_code == 204


# --------------------------------------------------------- STDIO transport


def test_stdio_transport_end_to_end(tmp_path) -> None:  # noqa: ANN001
    """Spawn ``python -m agent_hive mcp`` and drive a full MCP session."""
    import subprocess
    import sys as _sys

    python = _sys.executable
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    proc = subprocess.Popen(
        [python, "-m", "agent_hive", "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, cwd=str(PROJECT_ROOT), text=True, bufsize=1,
    )
    try:
        def send(obj) -> None:  # noqa: ANN001
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

        def recv() -> dict:
            line = proc.stdout.readline()
            assert line.strip(), "server closed stdout unexpectedly"
            return json.loads(line)

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26",
                         "clientInfo": {"name": "stdio-test"}}})
        init = recv()
        assert init["result"]["protocolVersion"] == "2025-03-26"

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = recv()["result"]["tools"]
        assert {t["name"] for t in tools} == set(MANIFEST_NAMES)

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "agent_get_system_status", "arguments": {}}})
        payload = json.loads(recv()["result"]["content"][0]["text"])
        assert payload["ok"] is True
        assert payload["data"]["version"]

        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "agent_save_memory",
                         "arguments": {"memory_type": "semantic", "key": "stdio-note",
                                       "content": "written via stdio MCP"}}})
        payload = json.loads(recv()["result"]["content"][0]["text"])
        assert payload["ok"] is True, payload
        assert payload["data"]["key"] == "stdio-note"

        send({"jsonrpc": "2.0", "id": 5, "method": "ping"})
        assert recv()["result"] == {}
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.wait(timeout=30)


# ==================================================================== mandatory platform test =====


async def test_UNIVERSAL_MCP_TOOL_EXECUTION_TEST(hive) -> None:
    """Mandatory end-to-end MCP tool execution verification.

    Connect (initialize) → discover tools → read one tool's schema →
    execute a tool → get structured result → handle an error → ping →
    close the session correctly.
    """
    from agent_hive.mcp.tools import ToolContext

    async def _factory(session):  # noqa: ANN001
        return ToolContext(hive=hive, umemory=hive.umemory,
                           identity=_admin(), client="mcp")

    core = MCPServerCore(registry=get_registry(), ctx_factory=_factory)

    # 1. connect
    session = core.create_session()
    init = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": "i1", "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26",
                               "clientInfo": {"name": "cross-test"}}}),
        session,
    )
    assert init["result"]["serverInfo"]["name"] == "agent-hive"
    await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        session,
    )

    # 2. discover the tools
    listed = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": "i2", "method": "tools/list"}), session
    )
    tools = {t["name"]: t for t in listed["result"]["tools"]}
    assert set(tools) == set(MANIFEST_NAMES)

    # 3. read the schema of agent_save_memory before calling
    schema = tools["agent_save_memory"]["inputSchema"]
    assert schema["required"] == ["memory_type", "key", "content"]
    assert schema["properties"]["memory_type"]["enum"] == [
        "episodic", "semantic", "operational", "task", "decision"
    ]

    # 4. execute the tool (write shared memory)
    written = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": "i3", "method": "tools/call",
            "params": {"name": "agent_save_memory", "arguments": {
                "memory_type": "task",
                "key": "mcp-exec-test",
                "content": "task created through MCP execution test",
                "session_id": "mcp-exec-session",
            }},
        }),
        session,
    )
    assert written["result"]["isError"] is False
    data = json.loads(written["result"]["content"][0]["text"])
    assert data["ok"] is True and data["data"]["version"] == 1

    # 5. read it back through search (round trip)
    found = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": "i4", "method": "tools/call",
            "params": {"name": "agent_search_memory", "arguments": {
                "query": "mcp execution test", "session_id": "mcp-exec-session"}},
        }),
        session,
    )
    data = json.loads(found["result"]["content"][0]["text"])
    assert data["ok"] is True
    assert any(r["key"] == "mcp-exec-test" for r in data["data"]["results"])

    # 6. structured error handling (invalid params → isError result, no crash)
    bad = await core.handle_message(
        json.dumps({
            "jsonrpc": "2.0", "id": "i5", "method": "tools/call",
            "params": {"name": "agent_save_memory",
                       "arguments": {"memory_type": "bogus-type", "key": "k",
                                     "content": "c"}},
        }),
        session,
    )
    assert bad["result"]["isError"] is True
    payload = json.loads(bad["result"]["content"][0]["text"])
    assert payload["ok"] is False

    # 7. liveness ping
    pong = await core.handle_message(
        json.dumps({"jsonrpc": "2.0", "id": "i6", "method": "ping"}), session
    )
    assert pong["result"] == {}

    # 8. correct session teardown
    core.end_session(session.session_id)
    assert core.get_session(session.session_id) is None


def test_batch_messages_are_supported() -> None:
    """JSON-RPC batches: mixed requests+notifications answered collectively."""

    core = MCPServerCore(registry=get_registry(), ctx_factory=None, server_version="t")
    session = core.create_session()
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    result = asyncio.run(core.handle_message(json.dumps(batch), session))
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_module_imports_clean() -> None:
    import agent_hive.mcp as mcp_pkg

    assert mcp_pkg.validate_schema is not None
    assert httpx is not None  # keep httpx import meaningful
