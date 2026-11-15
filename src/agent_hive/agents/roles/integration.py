"""Integration Agent — merges agent contributions into one coherent artifact."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class IntegrationAgent(BaseAgent):
    """Merges multi-agent contributions, resolving overlaps and conflicts."""

    ROLE = "integration"
    CAPABILITIES = ["integration", "coordination", "synthesis"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Integration agent you must:\n"
            "- merge every contribution into a single coherent artifact "
            "with one consistent terminology;\n"
            '- return "conflicts": a list of {"topic", "agents", '
            '"resolution"} objects for every disagreement you resolved;\n'
            "- remove duplicated content instead of concatenating it;\n"
            "- preserve each source agent's key decisions in the result.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "conflicts" in parsed:
            conflicts: list[dict[str, Any]] = []
            for item in parsed.get("conflicts", []):
                if not isinstance(item, dict):
                    continue
                agents = item.get("agents")
                if isinstance(agents, str):
                    agents = [a.strip() for a in agents.split(",") if a.strip()]
                conflicts.append(
                    {
                        "topic": str(item.get("topic", ""))[:200],
                        "agents": [str(a)[:60] for a in (agents or [])][:5],
                        "resolution": str(item.get("resolution", ""))[:300],
                    }
                )
            parsed["conflicts"] = conflicts[:20]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and "conflicts" not in parsed:
            check["notes"].append("integration report missing 'conflicts' key")
            check["passed"] = False
        return check
