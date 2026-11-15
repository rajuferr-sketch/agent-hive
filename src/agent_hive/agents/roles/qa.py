"""QA Agent — quality assurance with checklists and acceptance scores."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class QAAgent(BaseAgent):
    """Runs quality checklists and scores deliverables against criteria."""

    ROLE = "qa"
    CAPABILITIES = ["quality", "validation", "review"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the QA agent you must:\n"
            '- return "checklist": a list of {"item", "passed"} objects '
            "covering every acceptance criterion;\n"
            '- return "score": a numeric quality score between 0.0 and 1.0;\n'
            "- justify each failed item with what is missing and where;\n"
            "- apply the scoring rubric consistently across deliverables.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            checklist = [
                {
                    "item": str(c.get("item", ""))[:200],
                    "passed": bool(c.get("passed", False)),
                }
                for c in parsed.get("checklist", [])
                if isinstance(c, dict)
            ][:30]
            if checklist:
                parsed["checklist"] = checklist
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            score = parsed.get("score")
            if not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
                check["notes"].append("QA output missing numeric 'score' in [0, 1]")
                check["passed"] = False
        return check
