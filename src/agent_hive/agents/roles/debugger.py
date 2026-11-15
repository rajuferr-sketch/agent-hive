"""Debugger Agent — root-cause analysis with ranked hypotheses."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


def _confidence(item: dict[str, Any]) -> float:
    try:
        return float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0


class DebuggerAgent(BaseAgent):
    """Performs root-cause analysis with ranked, testable hypotheses."""

    ROLE = "debugger"
    CAPABILITIES = ["debugging", "profiling", "evidence"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Debugger you must:\n"
            '- return "hypotheses": a list of {"cause", "confidence", '
            '"test"} objects ranked from most to least likely;\n'
            "- name the evidence that supports or rules out each hypothesis;\n"
            '- mark the single most likely "root_cause" explicitly;\n'
            "- propose the minimal reproduction steps before any fix.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            hypotheses = [
                h for h in parsed.get("hypotheses", []) if isinstance(h, dict)
            ]
            if hypotheses:
                hypotheses.sort(key=_confidence, reverse=True)
                ordered = []
                for rank, hypothesis in enumerate(hypotheses[:10], start=1):
                    ordered.append(
                        {
                            "rank": rank,
                            "cause": str(hypothesis.get("cause", ""))[:200],
                            "confidence": _confidence(hypothesis),
                            "test": str(hypothesis.get("test", ""))[:200],
                        }
                    )
                parsed["hypotheses"] = ordered
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("hypotheses"):
            check["notes"].append("debugging output missing 'hypotheses' list")
            check["passed"] = False
        return check
