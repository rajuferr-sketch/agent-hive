"""Deterministic mock provider.

Used for tests, CI and offline development. It never pretends to have run
a real model: every completion is tagged with ``[MOCK]`` and is a
role-aware deterministic template, so downstream behaviour (memory
writes, quality gates, integrations, role self-checks) can be exercised
without any external API.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from agent_hive.providers.base import CompletionResult, LLMProvider

MOCK_TAG = "[MOCK]"

_PY_SAMPLE = (
    "```python\n"
    "def solve(items: list[int]) -> int:\n"
    "    \"\"\"Deterministic mock implementation.\"\"\"\n"
    "    return sum(items)\n"
    "```\n"
)

# Role-specific structured fields so role self-checks behave realistically
# in mock mode (the mock never claims to be a real model).
_ROLE_FIELDS: dict[str, dict[str, Any]] = {
    "analyst": {"requirements": ["clear scope", "testable acceptance criteria"],
                 "subtasks": [{"title": "draft plan", "capability": "analysis"}]},
    "researcher": {"findings": [{"claim": "option A viable", "confidence": 0.8,
                                  "source": "mock corpus"}]},
    "programmer": {"output": MOCK_TAG + " implementation\n" + _PY_SAMPLE},
    "documenter": {"sections": [{"heading": "Overview", "body": MOCK_TAG + " overview"}]},
    "verifier": {"verdict": "accept", "claims_checked": 2},
    "optimizer": {"optimizations": [{"suggestion": "replace nested scan",
                                      "complexity": "O(n^2) -> O(n log n)",
                                      "impact": "30% faster"}]},
    "security": {"threats": [{"threat": "injection", "severity": "medium",
                               "mitigation": "validate inputs"}]},
    "tester": {"test_cases": [{"name": "happy path", "expected": "pass"}],
                "output": MOCK_TAG + " test suite\n" + _PY_SAMPLE},
    "designer": {"layout": "single-column with sidebar", "tokens": {"color": "#333"}},
    "debugger": {"hypotheses": [{"hypothesis": "off-by-one", "confidence": 0.7}]},
    "architect": {"components": ["api", "db", "workers"], "data_flow": "client -> api -> db"},
    "database": {"tables": [{"name": "users", "columns": ["id", "email"],
                              "indexes": ["email"]}]},
    "ui": {"components": ["header", "list"], "markup": "<button aria-label='submit'>go</button>"},
    "api": {"endpoints": [{"method": "GET", "path": "/items", "status": 200}]},
    "automation": {"stages": [{"stage": "build", "action": "pip install"}]},
    "performance": {"benchmarks": [{"name": "latency", "value": "120ms"}],
                     "bottlenecks": ["unindexed lookup"]},
    "qa": {"score": 0.9, "checklist": [{"item": "requirements covered", "passed": True}]},
    "integration": {"conflicts": [], "coherence": "all sections aligned"},
    "reviewer": {"findings": [{"finding": "minor naming issue", "severity": "minor"}]},
    "validator": {"verdict": "accept", "evidence": "all checks passed"},
}


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-1", params: dict[str, Any] | None = None) -> None:
        self.model = model
        self.params = params or {}

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        text = self._compose(system, user)
        return CompletionResult(
            text=text, provider=self.name, model=self.model, mock=True,
            usage={"mock_tokens": len(text.split())},
        )

    # -- deterministic template -----------------------------------------
    def _compose(self, system: str, user: str) -> str:
        digest = hashlib.sha256(f"{system}|{user}".encode()).hexdigest()[:8]
        role_line = system.strip().splitlines()[0] if system.strip() else "assistant"
        role_match = re.search(r"the (\w+) agent of AgentHive", system)
        role_fields = _ROLE_FIELDS.get(role_match.group(1), {}) if role_match else {}
        payload: dict[str, Any] = {
            "tag": MOCK_TAG,
            "run": digest,
            "role": role_line[:120],
            "input_excerpt": user[:400],
            "analysis": (
                "Deterministic mock analysis of the received task. "
                "Key points extracted from the input, structured as "
                "requirements, risks and suggested next steps."
            ),
            "output": (
                f"{MOCK_TAG} Structured draft deliverable for: "
                f"{user[:200] or '(empty input)'}"
            ),
            "checklist": [
                "requirements understood",
                "constraints respected",
                "output formatted",
            ],
        }
        payload.update(role_fields)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # Code-fence roles: append the fenced block OUTSIDE the JSON so the
        # literal newline survives JSON escaping and role self-checks see it.
        if role_match and role_match.group(1) in ("programmer", "tester"):
            text += "\n" + _PY_SAMPLE
        elif role_match and role_match.group(1) == "documenter":
            text += "\n\n# " + MOCK_TAG + " Documentation\n\nDeterministic mock section.\n"
        return text
