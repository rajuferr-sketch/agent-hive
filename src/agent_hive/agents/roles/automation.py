"""Automation Agent — CI/CD pipelines, scripting and DevOps workflows."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class AutomationAgent(BaseAgent):
    """Builds CI/CD pipelines and idempotent automation scripts."""

    ROLE = "automation"
    CAPABILITIES = ["automation", "deployment", "monitoring"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Automation agent you must:\n"
            '- return "stages": an ordered list of pipeline stage names;\n'
            "- write idempotent scripts that are safe to re-run;\n"
            "- pin tool and action versions instead of using floating tags;\n"
            "- define what each stage gates on and how failures are reported.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "stages" in parsed:
            stages: list[dict[str, Any]] = []
            for item in parsed.get("stages", []):
                if isinstance(item, dict):
                    stages.append(
                        {
                            "name": str(item.get("name", ""))[:120],
                            "script": str(item.get("script", ""))[:2000],
                        }
                    )
                elif item:
                    stages.append({"name": str(item)[:120], "script": ""})
            parsed["stages"] = stages[:30]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("stages"):
            check["notes"].append("pipeline missing 'stages' list")
            check["passed"] = False
        return check
