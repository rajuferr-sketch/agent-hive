"""Reviewer Agent — disciplined code review with severity-ranked findings."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_SEVERITIES = {"blocker", "major", "minor"}


class ReviewerAgent(BaseAgent):
    """Reviews artifacts and reports severity-ranked, actionable findings."""

    ROLE = "reviewer"
    CAPABILITIES = ["review", "quality", "evidence"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Reviewer you must:\n"
            '- return "findings": a list of {"finding", "severity", '
            '"location"} objects with severity in {blocker, major, minor};\n'
            "- point at a precise location (file, function or line) for "
            "every finding;\n"
            "- separate blocking issues from nice-to-have improvements;\n"
            "- judge the artifact, never the author.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "findings" in parsed:
            findings: list[dict[str, Any]] = []
            for item in parsed.get("findings", []):
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity", "minor")).lower()
                if severity not in _SEVERITIES:
                    severity = "minor"
                findings.append(
                    {
                        "finding": str(item.get("finding", ""))[:300],
                        "severity": severity,
                        "location": str(item.get("location", ""))[:120],
                    }
                )
            parsed["findings"] = findings[:30]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            invalid = [
                str(f.get("severity"))
                for f in parsed.get("findings", [])
                if isinstance(f, dict)
                and str(f.get("severity", "")).lower() not in _SEVERITIES
            ]
            if invalid:
                check["notes"].append(
                    "findings with invalid severity: " + ", ".join(invalid)
                )
                check["passed"] = False
        return check
