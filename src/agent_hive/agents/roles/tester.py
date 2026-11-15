"""Tester Agent — designs test plans and pytest test code."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_CODE_BLOCK = re.compile(r"```python\s*\n")


class TesterAgent(BaseAgent):
    """Designs test plans and executable pytest test suites."""

    ROLE = "tester"
    CAPABILITIES = ["testing", "testing_design", "quality"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Tester you must:\n"
            '- return "test_cases": a list of {"name", "scenario", '
            '"expected"} objects covering happy path and edge cases;\n'
            "- emit runnable pytest code in a fenced ```python block;\n"
            "- use descriptive test names that state the expected behavior;\n"
            "- include at least one negative test for every validation rule.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            cases = [
                {
                    "name": str(c.get("name", ""))[:120],
                    "scenario": str(c.get("scenario", ""))[:300],
                    "expected": str(c.get("expected", ""))[:300],
                }
                for c in parsed.get("test_cases", [])
                if isinstance(c, dict)
            ][:30]
            if cases:
                parsed["test_cases"] = cases
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        if not _CODE_BLOCK.search(text):
            check["notes"].append("test output has no fenced ```python block")
            check["passed"] = False
        return check
