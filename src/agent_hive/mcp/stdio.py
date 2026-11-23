"""STDIO transport — run AgentHive as a local MCP server.

Used by local clients (Claude Desktop, LM Studio connectors, IDE agents)
that spawn the server and speak newline-delimited JSON-RPC on stdin/stdout.
Logs go to stderr only; stdout carries protocol frames exclusively.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from agent_hive.core.logging import get_logger
from agent_hive.mcp.server import MCPServerCore

log = get_logger("agent_hive.mcp.stdio")


async def serve_stdio(core: MCPServerCore) -> int:
    """Blocking loop: read JSON-RPC lines from stdin, write responses to stdout.

    The STDIO session is locally trusted (the client spawned this process
    on the operator's machine), so it carries the full scope set. Logs go
    to stderr only; stdout carries protocol frames exclusively.
    Returns a process exit code. EOF terminates cleanly.
    """
    from agent_hive.security.tokens import TokenIdentity

    session = core.create_session()
    session.identity = TokenIdentity(
        token_id="stdio", subject="local", role="admin", scopes=["*"]
    )
    loop = _loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break  # EOF — clean shutdown
            line = line.strip()
            if not line:
                continue
            response = await core.handle_message(line, session)
            if response is not None:
                sys.stdout.write(
                    json.dumps(response, ensure_ascii=False, default=str) + "\n"
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        log.info("stdio server interrupted — shutting down")
        return 0
    finally:
        core.end_session(session.session_id)
    return 0


def _loop():
    import asyncio

    return asyncio.get_running_loop()


def run_stdio(hive: Any, umemory: Any) -> int:
    """Bootstrap a Hive (if needed) and run the STDIO server.

    STDIO sessions are locally trusted: the client (e.g. Claude Desktop)
    spawned this process on the operator's machine, so the session gets
    the full scope set. Remote access must use the HTTP transport with
    issued tokens instead.
    """
    import asyncio

    from agent_hive.mcp.server import default_ctx_factory
    from agent_hive.mcp.tools import get_registry
    from agent_hive.version import __version__

    async def _main() -> int:
        started_here = False
        if not hive._started:
            await hive.startup()
            started_here = True
        registry = get_registry()
        core = MCPServerCore(
            registry=registry,
            ctx_factory=default_ctx_factory(hive, umemory, registry),
            server_version=__version__,
        )
        try:
            return await serve_stdio(core)
        finally:
            if started_here:
                await hive.shutdown()

    return asyncio.run(_main())


_REGISTRY: Any = None


def registry_singleton(hive: Any, umemory: Any) -> Any:
    """One tool registry per process."""
    global _REGISTRY
    if _REGISTRY is None:
        from agent_hive.mcp.tools import build_registry

        _REGISTRY = build_registry()
    return _REGISTRY
