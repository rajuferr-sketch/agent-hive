"""Permission-controlled tool registry.

An agent may only invoke tools explicitly granted in its YAML config.
Sensitive tool families (file access, HTTP) are additionally gated by
global environment switches. Tools are small, auditable, pure-ish async
functions — they never import agent or orchestration code.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import PermissionDenied

ToolFunc = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    family: str  # "text" | "code" | "file" | "http"
    func: ToolFunc


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, family: str, func: ToolFunc) -> None:
        self._tools[name] = Tool(name, description, family, func)

    def describe(self, allowed: list[str]) -> list[dict[str, str]]:
        return [
            {"name": t.name, "description": t.description, "family": t.family}
            for n in allowed
            if (t := self._tools.get(n))
        ]

    async def run(self, agent: str, allowed: list[str], name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in allowed:
            raise PermissionDenied(
                f"Agent '{agent}' is not authorized to use tool '{name}'"
            )
        tool = self._tools.get(name)
        if tool is None:
            raise PermissionDenied(f"Unknown tool '{name}'")
        if tool.family == "file" and not get_settings().enable_file_tools:
            raise PermissionDenied("File tools are disabled system-wide")
        if tool.family == "http" and not get_settings().enable_http_tools:
            raise PermissionDenied("HTTP tools are disabled system-wide")
        return await tool.func(**kwargs)


REGISTRY = ToolRegistry()
