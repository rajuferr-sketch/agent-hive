"""OpenAI-compatible *server* connector — AgentHive as a chat-completions API.

Endpoints
---------
* ``GET  /v1/models``            — model list (one entry per agent persona);
* ``POST /v1/chat/completions``  — chat completion backed by the hive;
* ``POST /v1/responses``         — session continuity (resume a previous
  universal session by id, pulling cross-client context from shared memory).

Request handling
----------------
1. If the last user message is an explicit tool invocation (``{"name":...,
   "arguments":{...}}`` or ``@tool_name {...}``), the tool is executed
   through the universal gateway and its structured result is returned as
   the assistant message — this is how pure OpenAI-protocol clients use
   the 18 capabilities without MCP.
2. Otherwise the message is run as a mission (``agent_execute``) and the
   deliverable text is returned as the assistant message.
3. ``stream: true`` yields SSE ``chat.completion.chunk`` frames.

Authentication: the app-level token middleware covers ``/v1/*``; mock-mode
responses stay tagged ``[MOCK]`` exactly like the rest of the system.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent_hive.connectors.generic import parse_tool_invocation
from agent_hive.core.logging import get_logger
from agent_hive.gateway.gateway import UniversalRequest

log = get_logger("agent_hive.connectors.openai")


def build_openai_router(app_state) -> APIRouter:  # noqa: ANN001 — late-bound Hive holder
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        hive = app_state.hive()
        agents = sorted(hive.runtime.agents)
        data = [
            {"id": "agent-hive/master", "object": "model",
             "created": 0, "owned_by": "agent-hive"}
        ] + [
            {"id": f"agent-hive/{name}", "object": "model",
             "created": 0, "owned_by": "agent-hive"}
            for name in agents
        ]
        return {"object": "list", "data": data}

    @router.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> Response | dict[str, Any]:
        hive = app_state.hive()
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={
                "error": {"message": "invalid JSON body",
                          "type": "invalid_request_error"}})
        messages = payload.get("messages") or []
        if not isinstance(messages, list) or not messages:
            return JSONResponse(status_code=400, content={
                "error": {"message": "'messages' must be a non-empty list",
                          "type": "invalid_request_error"}})
        last_user = next(
            (m.get("content") or "" for m in reversed(messages)
             if m.get("role") == "user"),
            messages[-1].get("content") or "",
        )
        session_id = str(
            payload.get("session_id")
            or request.headers.get("x-session-id")
            or "global"
        )[:64]
        client_id = str(request.headers.get("x-client-id") or "openai-unknown")

        result_text, tool_payload = "", None
        invocation = parse_tool_invocation(str(last_user))
        if invocation is not None:
            name, args = invocation
            outcome = await hive.gateway.tool_call(
                name, args, client=f"openai:{client_id}"
            )
            if outcome.get("ok"):
                tool_payload = outcome.get("data")
            result_text = json.dumps(outcome, ensure_ascii=False, default=str)
        else:
            response = await hive.gateway.handle(
                UniversalRequest(
                    instruction=str(last_user),
                    client_id=client_id,
                    client_kind="openai",
                    session_id=session_id,
                )
            )
            if not response.ok:
                message = (response.error or {}).get("message", "gateway failure")
                return JSONResponse(status_code=502, content={
                    "error": {"message": message, "type": "gateway_error"}})
            result_text = str(response.data.get("deliverable") or "")

        created = int(time.time())
        model = str(payload.get("model") or "agent-hive/master")
        if payload.get("stream"):
            return StreamingResponse(
                _sse_stream(model, created, result_text),
                media_type="text/event-stream",
            )
        completion: dict[str, Any] = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": result_text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        if tool_payload is not None:
            completion["agent_hive"] = {"tool_result": tool_payload}
        return completion

    async def _sse_stream(model: str, created: int, text: str) -> AsyncIterator[str]:
        first = {
            "id": f"chatcmpl-{created}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0,
                         "delta": {"role": "assistant", "content": text},
                         "finish_reason": None}],
        }
        yield f"data: {json.dumps(first, ensure_ascii=False, default=str)}\n\n"
        done = {"id": first["id"], "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(done)}\n\n"
        yield "data: [DONE]\n\n"

    @router.post("/v1/responses")
    async def resume(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError:
            return {"error": "invalid JSON body"}
        session_id = str(payload.get("session_id") or "")
        instruction = str(payload.get("instruction") or "")
        if not session_id or not instruction:
            return {"error": "session_id and instruction are required"}
        hive = app_state.hive()
        response = await hive.gateway.resume(
            session_id, instruction,
            client_id=str(payload.get("client_id") or "openai-resume"),
            client_kind="openai",
        )
        out: dict[str, Any] = {"ok": response.ok, "id": response.request_id}
        if response.ok:
            out["deliverable"] = response.data.get("deliverable")
        else:
            out["error"] = response.error
        return out

    return router
