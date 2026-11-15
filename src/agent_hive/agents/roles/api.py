"""API Agent — designs REST endpoints, contracts and conventions."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class APIAgent(BaseAgent):
    """Designs REST API contracts: endpoints, payloads and status codes."""

    ROLE = "api"
    CAPABILITIES = ["api", "contract_design", "integration"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the API agent you must:\n"
            '- return "endpoints": a list of {"method", "path", "request", '
            '"response", "status"} objects with standard HTTP methods;\n'
            "- use plural resource nouns and path parameters for identity;\n"
            "- define request and response schemas for every endpoint;\n"
            "- document error responses with their status codes.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "endpoints" in parsed:
            endpoints: list[dict[str, Any]] = []
            for item in parsed.get("endpoints", []):
                if not isinstance(item, dict):
                    continue
                method = str(item.get("method", "GET")).upper()
                if method not in _METHODS:
                    method = "GET"
                path = str(item.get("path", ""))
                if path and not path.startswith("/"):
                    path = "/" + path
                endpoints.append(
                    {
                        "method": method,
                        "path": path[:200],
                        "request": item.get("request", {}),
                        "response": item.get("response", {}),
                        "status": int(item.get("status", 200) or 200),
                    }
                )
            parsed["endpoints"] = endpoints[:30]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("endpoints"):
            check["notes"].append("API contract missing 'endpoints' list")
            check["passed"] = False
        return check
