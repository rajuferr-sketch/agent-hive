"""Analyst Agent — decomposes requests into requirements and sub-problems."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class AnalystAgent(BaseAgent):
    """Analyzes user requests: requirements, constraints, decomposition."""

    ROLE = "analyst"
    CAPABILITIES = ["analysis", "decomposition", "requirements"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Analyst you must:\n"
            "- separate explicit goals from implicit constraints;\n"
            '- return "requirements": a list of short requirement strings;\n'
            '- return "subtasks": a list of {"title", "capability"} objects '
            "when decomposition helps;\n"
            "- keep each requirement testable and unambiguous.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            reqs = [str(r)[:200] for r in parsed.get("requirements", []) if r][:20]
            if reqs:
                parsed["requirements"] = reqs
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("requirements"):
            check["notes"].append("analysis missing 'requirements' list")
            check["passed"] = False
        return check
