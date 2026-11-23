"""Connector tests — OpenAI-compatible, Ollama-native, WS universal, REST.

Drives the real FastAPI app (lifespan included) through Starlette's
TestClient so auth middleware, routers and Hive wiring all execute.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent_hive.api.app import create_app, get_security


@pytest.fixture
def client() -> TestClient:
    """App with the full lifespan (Hive startup/shutdown)."""
    app = create_app()
    with TestClient(app) as test_client:  # runs lifespan
        # deterministic local-trust for the whole test module
        get_security().invalidate_cache()
        yield test_client


# ------------------------------------------------------------ OpenAI-compat


def test_v1_models_lists_master_and_agents(client: TestClient) -> None:
    data = client.get("/v1/models").json()
    ids = [m["id"] for m in data["data"]]
    assert "agent-hive/master" in ids
    assert len(ids) > 5


def test_chat_completions_plain_instruction(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={
        "model": "agent-hive/master",
        "messages": [{"role": "user",
                      "content": "Summarise the task of watering office plants"}],
        "session_id": "openai-conn-test",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"].strip()


def test_chat_completions_tool_invocation(client: TestClient) -> None:
    payload = json.dumps({
        "name": "agent_save_memory",
        "arguments": {"memory_type": "semantic", "key": "openai-conn",
                      "content": "memory written through OpenAI connector"},
    })
    response = client.post("/v1/chat/completions", json={
        "model": "agent-hive/master",
        "messages": [{"role": "user", "content": payload}],
    })
    assert response.status_code == 200
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assert parsed["ok"] is True
    assert parsed["data"]["key"] == "openai-conn"
    assert body["agent_hive"]["tool_result"]["key"] == "openai-conn"


def test_chat_completions_streaming(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "tiny mission"}],
        "stream": True,
    })
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "data: [DONE]" in response.text


def test_chat_completions_rejects_empty_messages(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400


def test_v1_responses_session_resume(client: TestClient) -> None:
    # seed a session context through the universal memory
    client.post("/api/universal/memory", json={
        "memory_type": "semantic", "key": "resume-note",
        "content": "favorite number is seven", "session_id": "openai-resume-1",
    })
    response = client.post("/v1/responses", json={
        "session_id": "openai-resume-1",
        "instruction": "continue from the stored note",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["deliverable"]


def test_v1_responses_requires_fields(client: TestClient) -> None:
    response = client.post("/v1/responses", json={"session_id": ""})
    assert "error" in response.json()


# ----------------------------------------------------------- Ollama-native


def test_ollama_tags(client: TestClient) -> None:
    models = client.get("/api/tags").json()["models"]
    names = [m["name"] for m in models]
    assert "agent-hive:master" in names


def test_ollama_chat(client: TestClient) -> None:
    response = client.post("/api/chat", json={
        "model": "agent-hive:master",
        "messages": [{"role": "user", "content": "plan a tiny sprint"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["done"] is True
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"].strip()


def test_ollama_generate_tool_call(client: TestClient) -> None:
    payload = json.dumps({
        "name": "agent_get_capabilities", "arguments": {},
    })
    response = client.post("/api/generate", json={"prompt": payload})
    assert response.status_code == 200
    body = response.json()
    parsed = json.loads(body["response"])
    assert parsed["ok"] is True
    assert parsed["data"]["tools"]


# ---------------------------------------------------------- universal REST


def test_universal_tools_manifest(client: TestClient) -> None:
    body = client.get("/api/universal/tools").json()
    assert body["count"] == 18
    names = {t["name"] for t in body["tools"]}
    assert "agent_execute" in names and "agent_search_memory" in names


def test_universal_request_and_memory_flow(client: TestClient) -> None:
    response = client.post("/api/universal/request", json={
        "instruction": "produce a two-word status line",
        "client_id": "rest-test", "session_id": "rest-conn-1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["deliverable"]

    ctx = client.get("/api/universal/session/rest-conn-1/context").json()
    assert any(r["memory_type"] == "task" for r in ctx)


def test_universal_memory_write_and_search(client: TestClient) -> None:
    write = client.post("/api/universal/memory", json={
        "memory_type": "semantic", "key": "rest-mem",
        "content": "quarkus migrations run via flyway",
        "session_id": "rest-mem-1",
    })
    assert write.status_code == 200
    assert write.json()["version"] == 1
    hits = client.get("/api/universal/memory", params={
        "q": "flyway quarkus", "session_id": "rest-mem-1"}).json()
    assert any(h["key"] == "rest-mem" for h in hits)


def test_universal_tool_endpoint_invalid(client: TestClient) -> None:
    response = client.post("/api/universal/tool", json={
        "name": "agent_save_memory", "arguments": {}})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_params"


# --------------------------------------------------------------- MCP HTTP


def test_mcp_http_initialize_and_list(client: TestClient) -> None:
    init = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "clientInfo": {"name": "t"}},
    })
    assert init.status_code == 200
    session_id = init.headers["mcp-session-id"]
    listing = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Mcp-Session-Id": session_id})
    tools = listing.json()["result"]["tools"]
    assert len(tools) == 18


def test_mcp_http_requires_session(client: TestClient) -> None:
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 404


# ---------------------------------------------------------- WebSocket


def test_ws_universal_ping_and_tool(client: TestClient) -> None:
    with client.websocket_connect("/ws/universal") as ws:
        ws.send_text(json.dumps({"id": "p1", "action": "ping"}))
        pong = json.loads(ws.receive_text())
        assert pong["ok"] is True and pong["data"]["pong"] is True

        ws.send_text(json.dumps({
            "id": "t1", "action": "tool.call",
            "payload": {"name": "agent_get_capabilities", "arguments": {}},
        }))
        out = json.loads(ws.receive_text())
        assert out["ok"] is True
        assert "mcp-streamable-http" in out["data"]["transports"]


def test_ws_universal_bad_frame_keeps_connection(client: TestClient) -> None:
    with client.websocket_connect("/ws/universal") as ws:
        ws.send_text("not-json")
        err = json.loads(ws.receive_text())
        assert err["ok"] is False
        assert err["error"]["code"] == "bad_frame"
        # connection still usable
        ws.send_text(json.dumps({"id": "p2", "action": "ping"}))
        assert json.loads(ws.receive_text())["ok"] is True


def test_ws_universal_unknown_action(client: TestClient) -> None:
    with client.websocket_connect("/ws/universal") as ws:
        ws.send_text(json.dumps({"id": "u1", "action": "teleport"}))
        out = json.loads(ws.receive_text())
        assert out["error"]["code"] == "unknown_action"


# ------------------------------------------------------------ self-heal API


def test_selfheal_run_endpoint(client: TestClient) -> None:
    response = client.post("/api/selfheal/run")
    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is True
    checks = {c["check"] for c in body["checks"]}
    assert {"database", "scheduler", "agents", "universal_memory"} <= checks


def test_system_status_includes_universal(client: TestClient) -> None:
    status = client.get("/system/status").json()
    assert "gateway" in status
    assert len(status["mcp_tools"]) == 18
