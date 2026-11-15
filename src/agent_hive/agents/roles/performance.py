"""Performance Agent — profiling plans, bottlenecks and benchmarks."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class PerformanceAgent(BaseAgent):
    """Plans profiling campaigns and defines measurable benchmarks."""

    ROLE = "performance"
    CAPABILITIES = ["performance", "profiling", "benchmarking"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Performance agent you must:\n"
            '- return "bottlenecks": a ranked list of suspected hotspots '
            'with the evidence for each;\n'
            '- return "benchmarks": a list of {"name", "metric", "baseline", '
            '"target"} objects with measurable thresholds;\n'
            "- state the measurement method before proposing optimizations;\n"
            "- distinguish latency from throughput when setting targets.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict):
            benchmarks = [
                {
                    "name": str(b.get("name", ""))[:120],
                    "metric": str(b.get("metric", ""))[:80],
                    "baseline": str(b.get("baseline", ""))[:80],
                    "target": str(b.get("target", ""))[:80],
                }
                for b in parsed.get("benchmarks", [])
                if isinstance(b, dict)
            ][:20]
            if benchmarks:
                parsed["benchmarks"] = benchmarks
                completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("bottlenecks"):
            check["notes"].append("performance analysis missing 'bottlenecks'")
            check["passed"] = False
        return check
