"""Architect Agent — system architecture, components and data flow."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class ArchitectAgent(BaseAgent):
    """Designs system architecture with components, data flow and trade-offs."""

    ROLE = "architect"
    CAPABILITIES = ["architecture", "scalability", "design"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Architect you must:\n"
            '- return "components": a list of {"name", "responsibility"} '
            "objects with single, clear responsibilities;\n"
            '- return "data_flow": how information moves between components;\n'
            "- state the trade-offs of the chosen approach versus one "
            "credible alternative;\n"
            "- call out scaling limits and single points of failure.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            components = [
                {
                    "name": str(c.get("name", ""))[:120],
                    "responsibility": str(c.get("responsibility", ""))[:300],
                }
                for c in parsed.get("components", [])
                if isinstance(c, dict)
            ][:20]
            if components:
                parsed["components"] = components
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not (
            parsed.get("components") or parsed.get("data_flow")
        ):
            check["notes"].append(
                "architecture missing 'components' or 'data_flow'"
            )
            check["passed"] = False
        return check
