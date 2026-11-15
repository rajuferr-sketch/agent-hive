"""UI Agent — frontend implementation with accessibility requirements."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_A11Y = re.compile(r"(aria-[\w-]+|alt\s*=|role\s*=|<label)", re.IGNORECASE)


class UIAgent(BaseAgent):
    """Implements accessible HTML/CSS/JS frontend components."""

    ROLE = "ui"
    CAPABILITIES = ["frontend", "ux", "design"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the UI agent you must:\n"
            "- emit complete HTML/CSS/JS snippets inside fenced code blocks;\n"
            "- use semantic HTML elements over generic containers;\n"
            "- provide accessible names for every control (labels, "
            "aria-* attributes, alt text);\n"
            "- keep styling consistent with the given design tokens.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            components = [
                {
                    "name": str(c.get("name", ""))[:120],
                    "purpose": str(c.get("purpose", ""))[:300],
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
        if not _A11Y.search(text):
            check["notes"].append(
                "no accessibility markers (aria-*, alt, role, label)"
            )
            check["passed"] = False
        return check
