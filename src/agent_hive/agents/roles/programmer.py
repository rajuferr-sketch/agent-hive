"""Programmer Agent — produces production-quality Python code blocks."""

from __future__ import annotations

import re
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task

_CODE_BLOCK = re.compile(r"```python\s*\n")


class ProgrammerAgent(BaseAgent):
    """Implements solutions as runnable, lint-clean Python code."""

    ROLE = "programmer"
    CAPABILITIES = ["programming", "refactoring", "debugging"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Programmer you must:\n"
            "- emit every code artifact as a fenced ```python block;\n"
            "- write production-quality code: type hints, docstrings, "
            "no global mutable state;\n"
            "- keep functions small and single-purpose;\n"
            "- include a short usage example when the API is not obvious.\n"
        )

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        if not _CODE_BLOCK.search(text):
            check["notes"].append("no fenced ```python code block found")
            check["passed"] = False
        return check
