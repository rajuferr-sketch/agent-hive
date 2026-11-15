"""Verifier Agent — cross-checks claims against upstream results."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class VerifierAgent(BaseAgent):
    """Cross-checks claims for consistency, contradictions and evidence."""

    ROLE = "verifier"
    CAPABILITIES = ["verification", "evidence", "consistency"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Verifier you must:\n"
            '- return "claims": the list of claims you are checking;\n'
            '- return "verdict": one of "confirmed", "refuted", "unclear";\n'
            "- point out every contradiction between the inputs explicitly;\n"
            "- cite the evidence you relied on for each verdict.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        results = task.payload.get("results")
        if isinstance(parsed, dict) and isinstance(results, dict):
            claims = [str(c) for c in parsed.get("claims", []) if c]
            unmatched = [
                claim[:80]
                for claim in claims
                if not any(str(key) in claim for key in results)
            ]
            parsed["cross_check"] = {
                "result_keys": sorted(str(key) for key in results)[:20],
                "unmatched_claims": unmatched[:20],
            }
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("verdict"):
            check["notes"].append("verification missing 'verdict' key")
            check["passed"] = False
        return check
