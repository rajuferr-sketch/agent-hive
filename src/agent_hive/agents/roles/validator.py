"""Validator Agent — final acceptance validation against requirements."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_VERDICTS = {"accept", "reject"}


class ValidatorAgent(BaseAgent):
    """Performs final acceptance validation with an explicit verdict."""

    ROLE = "validator"
    CAPABILITIES = ["validation", "final_check", "evidence"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Validator you must:\n"
            '- return "verdict": exactly "accept" or "reject";\n'
            '- return "criteria": a list of {"requirement", "met"} objects '
            "checked against the original requirements;\n"
            "- reject when any mandatory requirement is unmet, no exceptions;\n"
            "- state the evidence supporting the verdict for each criterion.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            verdict = str(parsed.get("verdict", "")).strip().lower()
            if verdict in _VERDICTS:
                parsed["verdict"] = verdict
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            verdict = str(parsed.get("verdict", "")).strip().lower()
            if verdict not in _VERDICTS:
                check["notes"].append(
                    "validation missing explicit 'verdict' of 'accept' or 'reject'"
                )
                check["passed"] = False
        return check
