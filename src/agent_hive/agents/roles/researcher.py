"""Researcher Agent — gathers information and compares options with sources."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class ResearcherAgent(BaseAgent):
    """Researches topics: evidence gathering, option comparison, sources."""

    ROLE = "researcher"
    CAPABILITIES = ["research", "analysis", "synthesis"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Researcher you must:\n"
            "- state explicitly what is known versus what is assumed;\n"
            '- return "findings": a list of {"claim", "confidence", "source"} '
            "objects with confidence between 0.0 and 1.0;\n"
            '- when several options exist, return "options" with one "pros" '
            'and one "cons" entry per option;\n'
            "- never present an unverified claim as established fact.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            findings: list[dict[str, Any]] = []
            for item in parsed.get("findings", []):
                if not isinstance(item, dict):
                    continue
                try:
                    confidence = round(float(item.get("confidence", 0.0)), 2)
                except (TypeError, ValueError):
                    confidence = 0.0
                findings.append(
                    {
                        "claim": str(item.get("claim", ""))[:200],
                        "confidence": confidence,
                        "source": str(item.get("source", ""))[:200],
                    }
                )
            if findings:
                parsed["findings"] = findings[:20]
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            unsourced = [
                str(f.get("claim", "?"))[:60]
                for f in parsed.get("findings", [])
                if isinstance(f, dict) and not f.get("source")
            ]
            if unsourced:
                check["notes"].append(
                    "findings without a source: " + ", ".join(unsourced)
                )
                check["passed"] = False
        return check
