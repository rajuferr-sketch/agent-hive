"""Generic tool-calling connector — one manifest, every function-calling client.

Many clients cannot speak MCP but *can* declare JSON-schema tools:
Gemini function calling, Anthropic tool use, Qwen/DeepSeek function
calling, LangChain, LlamaIndex, n8n... This module exposes the 18
platform tools as a plain list of ``{name, description, parameters}``
objects (``GET /api/universal/tools``) and parses the two de-facto
invocation conventions from free text:

1. explicit JSON: ``{"name": "...", "arguments": {...}}`` or
   ``{"tool": "...", "args": {...}}``;
2. at-notation: ``@tool_name {"key": value}``.

A client that supports neither can still use the REST endpoints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from agent_hive.mcp.tools import ToolRegistry

# Regex used only to locate a JSON object after '@tool_name'.
_AT_JSON = re.compile(r"^@(?P<name>[a-z_]+)\s*(?P<args>\{.*\})\s*$", re.DOTALL)
_EXPLICIT_JSON = re.compile(r"^\s*\{.*\}\s*$", re.DOTALL)


def tool_manifest(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Generic function-calling manifest (OpenAI-style ``parameters``)."""
    out: list[dict[str, Any]] = []
    for entry in registry.manifest():
        out.append({
            "name": entry["name"],
            "description": entry["description"],
            "parameters": entry["inputSchema"],
        })
    return out


def parse_tool_invocation(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract ``(tool_name, arguments)`` from a message, or ``None``."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("@"):
        match = _AT_JSON.match(candidate)
        if match:
            try:
                args = json.loads(match.group("args")) if match.group("args") else {}
                return match.group("name"), args if isinstance(args, dict) else {}
            except ValueError:
                return match.group("name"), {}
        return None
    if _EXPLICIT_JSON.match(candidate):
        try:
            payload = json.loads(candidate)
        except ValueError:
            return None
        if isinstance(payload, dict):
            name = payload.get("name") or payload.get("tool")
            args = payload.get("arguments") or payload.get("args") or {}
            if isinstance(name, str) and isinstance(args, dict):
                return name, args
    return None


async def execute_via_gateway(
    gateway,  # UniversalGateway
    name: str,
    args: dict[str, Any],
    identity=None,  # TokenIdentity
    client: str = "generic",
) -> dict[str, Any]:
    """Run a parsed invocation through the universal gateway."""
    return await gateway.tool_call(name, args, identity=identity, client=client)


# Manifest builder bound at app wiring time (avoids import cycles).
_MANIFEST_BUILDER: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None


def set_manifest_builder(builder: Callable[[], Awaitable[list[dict[str, Any]]]]) -> None:
    global _MANIFEST_BUILDER
    _MANIFEST_BUILDER = builder


async def current_manifest() -> list[dict[str, Any]]:
    if _MANIFEST_BUILDER is None:
        return []
    return await _MANIFEST_BUILDER()


GENERIC_TOOLS_MANIFEST = tool_manifest  # alias for discoverability
