"""MCP JSON-RPC 2.0 core — protocol logic shared by all transports.

Implements the MCP tool-server surface:

* ``initialize``      → protocol negotiation + server capabilities;
* ``notifications/initialized`` → acknowledged (no response);
* ``ping``            → ``{}`` (liveness from client);
* ``tools/list``      → the 18 tool manifests with JSON schemas;
* ``tools/call``      → validated, authorized execution with MCP error
  semantics (tool failures are results with ``isError: true``; protocol
  errors use JSON-RPC error codes).

Sessions: created at ``initialize`` and identified by an opaque id the
client echoes back (HTTP header ``Mcp-Session-Id``); STDIO sessions are
implicitly the process itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent_hive.core.ids import new_id
from agent_hive.core.logging import get_logger
from agent_hive.mcp.tools import ToolContext, ToolRegistry
from agent_hive.security.tokens import TokenIdentity

log = get_logger("agent_hive.mcp.server")

PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_VERSIONS = ("2025-03-26", "2025-06-18")
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


@dataclass(slots=True)
class MCPSession:
    session_id: str
    client_info: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION
    identity: TokenIdentity | None = None
    initialized: bool = False


class MCPServerCore:
    """Stateless-per-message protocol engine over the tool registry."""

    def __init__(
        self,
        registry: ToolRegistry,
        ctx_factory,
        server_name: str = "agent-hive",
        server_version: str = "1.0.0",
        instructions: str = (
            "AgentHive universal multi-agent platform. Use tools/list to "
            "discover capabilities, agent_execute for natural-language "
            "missions, agent_save_memory/agent_search_memory for cross-client "
            "persistent shared memory."
        ),
        max_sessions: int = 256,
    ) -> None:
        self.registry = registry
        self._ctx_factory = ctx_factory  # async () -> ToolContext
        self.server_name = server_name
        self.server_version = server_version
        self.instructions = instructions
        self.max_sessions = max_sessions
        self.sessions: dict[str, MCPSession] = {}

    # -------------------------------------------------------------- sessions
    def create_session(self, identity: TokenIdentity | None = None) -> MCPSession:
        if len(self.sessions) >= self.max_sessions:
            # evict the oldest session to bound memory
            oldest = next(iter(self.sessions))
            self.sessions.pop(oldest, None)
        session = MCPSession(session_id=new_id(), identity=identity)
        self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str | None) -> MCPSession | None:
        return self.sessions.get(session_id or "")

    def end_session(self, session_id: str | None) -> None:
        self.sessions.pop(session_id or "", None)

    # ------------------------------------------------------------ entry point
    async def handle_message(
        self,
        raw: str | bytes,
        session: MCPSession,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Process one JSON-RPC message (or batch). ``None`` = notification."""
        try:
            message = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return _error_response(None, JSONRPC_PARSE_ERROR, f"parse error: {exc}")

        if isinstance(message, list):
            responses = []
            for item in message:
                resp = await self._handle_one(item, session)
                if resp is not None:
                    responses.append(resp)
            return responses or None
        return await self._handle_one(message, session)

    async def _handle_one(
        self, message: dict[str, Any], session: MCPSession
    ) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error_response(None, JSONRPC_INVALID_REQUEST, "not an object")
        method = message.get("method")
        msg_id = message.get("id")
        is_request = "id" in message and msg_id is not None

        if method is None:
            return _error_response(
                msg_id, JSONRPC_INVALID_REQUEST, "missing 'method'"
            )
        if is_request and message.get("jsonrpc") != "2.0" and message.get("jsonrpc") is not None:
            return _error_response(
                msg_id, JSONRPC_INVALID_REQUEST, "jsonrpc must be '2.0'"
            )

        handler = getattr(self, f"_rpc_{str(method).replace('/', '_').replace('-', '_')}", None)
        if handler is None:
            if is_request:
                return _error_response(
                    msg_id, JSONRPC_METHOD_NOT_FOUND, f"method '{method}' not found"
                )
            return None  # unknown notification — ignored per spec

        try:
            result = await handler(message.get("params") or {}, session)
        except Exception as exc:  # noqa: BLE001 — map to JSON-RPC error
            log.exception("handler crash for %s", method)
            if is_request:
                return _error_response(msg_id, JSONRPC_INTERNAL_ERROR, str(exc)[:300])
            return None
        if not is_request:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    # ------------------------------------------------------------- handlers
    async def _rpc_initialize(
        self, params: dict[str, Any], session: MCPSession
    ) -> dict[str, Any]:
        requested = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        negotiated = requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        session.protocol_version = negotiated
        session.client_info = params.get("clientInfo") or {}
        session.initialized = True
        return {
            "protocolVersion": negotiated,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "instructions": self.instructions,
        }

    async def _rpc_notifications_initialized(
        self, _params: dict[str, Any], _session: MCPSession
    ) -> None:
        return None

    async def _rpc_ping(
        self, _params: dict[str, Any], _session: MCPSession
    ) -> dict[str, Any]:
        return {}

    async def _rpc_tools_list(
        self, _params: dict[str, Any], _session: MCPSession
    ) -> dict[str, Any]:
        return {"tools": self.registry.manifest()}

    async def _rpc_tools_call(
        self, params: dict[str, Any], session: MCPSession
    ) -> dict[str, Any]:
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        ctx: ToolContext = await self._ctx_factory(session)
        result = await self.registry.call(
            name, args,
            ctx=ctx,
            identity=session.identity,
            client=f"mcp:{session.client_info.get('name', 'unknown')}",
        )
        text = json.dumps(result, ensure_ascii=False, default=str)
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": not result.get("ok", False),
            "structuredContent": result,
        }
        return payload


def _error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def default_ctx_factory(hive, umemory, registry: ToolRegistry):  # noqa: ANN001
    """Build the async context factory used by server transports."""
    async def factory(session: MCPSession) -> ToolContext:
        return ToolContext(
            hive=hive, umemory=umemory, identity=session.identity, client="mcp"
        )
    return factory
