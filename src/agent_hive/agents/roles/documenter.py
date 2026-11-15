"""Documenter Agent — writes structured user and technical documentation."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_HEADING = re.compile(r"^#{1,3} ", re.MULTILINE)


class DocumenterAgent(BaseAgent):
    """Produces clear markdown documentation with a predictable structure."""

    ROLE = "documenter"
    CAPABILITIES = ["documentation", "synthesis", "quality"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Documenter you must:\n"
            "- structure output as markdown with at least one heading;\n"
            '- return "sections": a list of {"title", "body"} objects;\n'
            "- prefer examples and step-by-step instructions over prose;\n"
            "- document parameters, return values and error cases.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            sections = [
                {
                    "title": str(s.get("title", ""))[:120],
                    "body": str(s.get("body", ""))[:4000],
                }
                for s in parsed.get("sections", [])
                if isinstance(s, dict)
            ][:30]
            if sections:
                parsed["sections"] = sections
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        if not _HEADING.search(text):
            check["notes"].append("documentation has no markdown heading")
            check["passed"] = False
        return check
