"""Designer Agent — UX/UI design specs, layout structure and design tokens."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class DesignerAgent(BaseAgent):
    """Specifies UX/UI layouts, components and design tokens."""

    ROLE = "designer"
    CAPABILITIES = ["design", "ux", "frontend"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Designer you must:\n"
            '- return "layout": an ordered description of the page regions;\n'
            '- return "tokens": a mapping of design tokens '
            "(colors, spacing, typography) to concrete values;\n"
            "- describe every interactive component with its states "
            "(default, hover, focus, disabled);\n"
            "- justify layout choices against the user's goals.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            tokens = parsed.get("tokens")
            if isinstance(tokens, dict):
                parsed["tokens"] = {
                    str(k): str(v) for k, v in tokens.items() if k
                }
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("layout"):
            check["notes"].append("design spec missing 'layout' description")
            check["passed"] = False
        return check
