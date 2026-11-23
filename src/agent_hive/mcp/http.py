"""Streamable HTTP transport for the MCP server (mounted at ``/mcp``).

Wire format (MCP ``2025-03-26`` streamable HTTP):

* ``POST /mcp`` with a JSON-RPC message (single or batch) and
  ``Accept: application/json, text/event-stream``;
* the server replies with JSON (this implementation) or SSE frames when
  the client accepts only ``text/event-stream``;
* ``initialize`` establishes a session: the response carries the
  ``Mcp-Session-Id`` header, echoed by the client afterwards;
* notifications (no ``id``) return ``202 Accepted`` with no body;
* ``GET /mcp`` and ``DELETE /mcp`` are supported for server→client
  streams and explicit session termination (DELETE answers 405 because
  this server does not stream unsolicited data, per spec's allowance).

Authentication: ``Authorization: Bearer <token>`` is resolved by the
shared FastAPI dependency when security is enabled; STDIO-equivalent
local trust can be configured via ``API_MASTER_TOKEN``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from agent_hive.core.logging import get_logger
from agent_hive.mcp.server import MCPServerCore

log = get_logger("agent_hive.mcp.http")

SESSION_HEADER = "mcp-session-id"


def build_mcp_router(core: MCPServerCore, identity_resolver=None) -> APIRouter:
    """Mount the MCP Streamable HTTP transport.

    ``identity_resolver`` is an async callable ``(request) -> TokenIdentity``
    wired by the API layer (Bearer-token based; ``None`` sessions run
    unauthenticated and tools will refuse scope-restricted calls).
    """
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        session_id = request.headers.get(SESSION_HEADER)
        session = core.get_session(session_id)
        body = await request.body()
        if not body:
            return JSONResponse(
                status_code=400,
                content={"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": "empty body"}},
            )
        try:
            parsed_probe = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return JSONResponse(
                content={"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": f"parse error: {exc}"}},
            )

        # initialize without a session → create one (identity from headers)
        if session is None:
            method = parsed_probe.get("method") if isinstance(parsed_probe, dict) else None
            if method == "initialize" or (
                isinstance(parsed_probe, list)
                and any(isinstance(m, dict) and m.get("method") == "initialize"
                        for m in parsed_probe)
            ):
                session = core.create_session()
                if identity_resolver is not None:
                    session.identity = await identity_resolver(request)
            else:
                return JSONResponse(
                    status_code=404,
                    content={"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32600,
                                       "message": "session expired or missing: "
                                                  "re-initialize first"}},
                )

        accept = request.headers.get("accept", "application/json")
        wants_sse = "text/event-stream" in accept and "application/json" not in accept

        response_payload = await core.handle_message(body, session)
        if response_payload is None:
            return Response(status_code=202)

        headers = {SESSION_HEADER: session.session_id}
        if wants_sse:
            events = response_payload if isinstance(response_payload, list) else [response_payload]
            sse_body = "".join(
                f"event: message\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
                for e in events
            )
            return Response(
                content=sse_body, media_type="text/event-stream", headers=headers
            )
        return JSONResponse(content=response_payload, headers=headers)

    @router.get("/mcp")
    async def mcp_get() -> Response:
        # No server-initiated streams: 405 lets clients fall back to POST-only.
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})

    @router.delete("/mcp")
    async def mcp_delete(request: Request) -> Response:
        session_id = request.headers.get(SESSION_HEADER)
        if not session_id or core.get_session(session_id) is None:
            return JSONResponse(status_code=404, content={"detail": "unknown session"})
        core.end_session(session_id)
        return Response(status_code=204)

    return router
