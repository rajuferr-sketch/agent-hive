"""Ollama-native *server* connector — AgentHive speaks the Ollama protocol.

Any Ollama-aware client (Open WebUI, LibreChat, custom scripts) can point
its ``OLLAMA_HOST`` at AgentHive and use the hive transparently:

* ``GET  /api/tags``      — model list (agent personas as pseudo-models);
* ``POST /api/chat``      — chat via the gateway (``message.content``);
* ``POST /api/generate``  — completion via the gateway (``response``).

Requests with an explicit tool invocation payload execute the tool;
plain instructions run as missions. Responses carry ``done: true`` and
the ``[MOCK]`` tag when mock mode produced the deliverable.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from agent_hive.connectors.generic import parse_tool_invocation
from agent_hive.core.logging import get_logger
from agent_hive.gateway.gateway import UniversalRequest

log = get_logger("agent_hive.connectors.ollama")


def build_ollama_router(app_state) -> APIRouter:  # noqa: ANN001
    router = APIRouter()

    @router.get("/api/tags")
    async def tags() -> dict[str, Any]:
        hive = app_state.hive()
        models = [{
            "name": "agent-hive:master",
            "model": "agent-hive:master",
            "modified_at": "2025-01-01T00:00:00Z",
            "size": 0,
            "digest": "agenthive",
            "details": {"family": "agent-hive", "parameter_size": "n/a",
                        "quantization_level": "n/a"},
        }]
        for name in sorted(hive.runtime.agents):
            models.append({
                "name": f"agent-hive:{name}",
                "model": f"agent-hive:{name}",
                "modified_at": "2025-01-01T00:00:00Z",
                "size": 0,
                "digest": "agenthive",
                "details": {"family": "agent-hive", "parameter_size": "n/a",
                            "quantization_level": "n/a"},
            })
        return {"models": models}

    @router.post("/api/chat", response_model=None)
    async def chat(request: Request) -> Response | dict[str, Any]:
        hive = app_state.hive()
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "invalid JSON body"})
        messages = payload.get("messages") or []
        if not isinstance(messages, list) or not messages:
            return JSONResponse(status_code=400, content={"error": "'messages' required"})
        last = str((messages[-1] or {}).get("content") or "")
        session_id = str(payload.get("session_id") or "global")[:64]
        client_id = str(request.headers.get("x-client-id") or "ollama-unknown")

        invocation = parse_tool_invocation(last)
        if invocation is not None:
            name, args = invocation
            outcome = await hive.gateway.tool_call(
                name, args, client=f"ollama:{client_id}"
            )
            content = json.dumps(outcome, ensure_ascii=False, default=str)
        else:
            response = await hive.gateway.handle(
                UniversalRequest(
                    instruction=last,
                    client_id=client_id,
                    client_kind="ollama",
                    session_id=session_id,
                )
            )
            content = (
                str(response.data.get("deliverable") or "")
                if response.ok
                else json.dumps(response.error or {}, ensure_ascii=False)
            )
        return {
            "model": payload.get("model") or "agent-hive:master",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": {"role": "assistant", "content": content},
            "done": True,
        }

    @router.post("/api/generate", response_model=None)
    async def generate(request: Request) -> Response | dict[str, Any]:
        hive = app_state.hive()
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "invalid JSON body"})
        prompt = str(payload.get("prompt") or "")
        if not prompt:
            return JSONResponse(status_code=400, content={"error": "'prompt' required"})
        session_id = str(payload.get("session_id") or "global")[:64]
        client_id = str(request.headers.get("x-client-id") or "ollama-unknown")

        invocation = parse_tool_invocation(prompt)
        if invocation is not None:
            name, args = invocation
            outcome = await hive.gateway.tool_call(
                name, args, client=f"ollama:{client_id}"
            )
            response_text = json.dumps(outcome, ensure_ascii=False, default=str)
        else:
            resp = await hive.gateway.handle(
                UniversalRequest(
                    instruction=prompt,
                    client_id=client_id,
                    client_kind="ollama",
                    session_id=session_id,
                )
            )
            response_text = (
                str(resp.data.get("deliverable") or "")
                if resp.ok else json.dumps(resp.error or {}, ensure_ascii=False)
            )
        return {
            "model": payload.get("model") or "agent-hive:master",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "response": response_text,
            "done": True,
        }

    return router
