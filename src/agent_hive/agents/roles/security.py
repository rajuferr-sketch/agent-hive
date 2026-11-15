"""Security Agent — threat modeling and security review checklists."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult

_SEVERITIES = {"low", "medium", "high", "critical"}


class SecurityAgent(BaseAgent):
    """Models threats and produces actionable security mitigations."""

    ROLE = "security"
    CAPABILITIES = ["security", "threat_modeling", "compliance"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Security agent you must:\n"
            '- return "threats": a list of {"threat", "severity", '
            '"mitigation"} objects with severity in '
            "{low, medium, high, critical};\n"
            "- cover at least authentication, injection and data exposure;\n"
            "- map every threat to a concrete mitigation, not advice alone;\n"
            "- never include real secrets, keys or tokens in the output.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "threats" in parsed:
            threats: list[dict[str, Any]] = []
            for item in parsed.get("threats", []):
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity", "medium")).lower()
                if severity not in _SEVERITIES:
                    severity = "medium"
                threats.append(
                    {
                        "threat": str(item.get("threat", ""))[:200],
                        "severity": severity,
                        "mitigation": str(item.get("mitigation", ""))[:300],
                    }
                )
            parsed["threats"] = threats[:20]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            unmitigated = [
                str(t.get("threat", "?"))[:60]
                for t in parsed.get("threats", [])
                if isinstance(t, dict) and not t.get("mitigation")
            ]
            if unmitigated:
                check["notes"].append(
                    "threats without a mitigation: " + ", ".join(unmitigated)
                )
                check["passed"] = False
        return check
