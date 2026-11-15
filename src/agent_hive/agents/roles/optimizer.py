"""Optimizer Agent — suggests algorithmic and resource optimizations."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_BIG_O = re.compile(r"\bO\([^)]+\)")


class OptimizerAgent(BaseAgent):
    """Improves algorithms and resource usage with complexity estimates."""

    ROLE = "optimizer"
    CAPABILITIES = ["optimization", "performance", "profiling"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Optimizer you must:\n"
            '- return "optimizations": a list of {"suggestion", "complexity", '
            '"impact"} objects;\n'
            "- state the current and proposed complexity in Big-O notation;\n"
            "- quantify the expected impact before recommending a change;\n"
            "- never trade correctness or readability for micro-gains.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            optimizations = [
                {
                    "suggestion": str(o.get("suggestion", ""))[:300],
                    "complexity": str(o.get("complexity", ""))[:60],
                    "impact": str(o.get("impact", ""))[:120],
                }
                for o in parsed.get("optimizations", [])
                if isinstance(o, dict)
            ][:20]
            if optimizations:
                parsed["optimizations"] = optimizations
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        if not _BIG_O.search(text):
            check["notes"].append("no complexity estimate in Big-O notation")
            check["passed"] = False
        return check
