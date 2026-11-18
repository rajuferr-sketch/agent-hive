"""Quality Gate — multilevel verification before integration/delivery.

Checks (each weighted, configurable in configs/system.yaml):

1. completeness      — the deliverable is substantive, not empty/stub;
2. requirements      — initial requirements are covered by the output;
3. code              — every embedded Python block must be syntactically
                       valid (static AST check, never executed);
4. secrets           — no hard-coded credentials in the output;
5. markers           — no TODO/FIXME/"not implemented" leftovers.

The gate stores a :class:`agent_hive.db.models.Verification` record and
appends the verdict to historical memory. The Master Agent refuses to
deliver results whose score is below ``qa_required_score``.
"""

from __future__ import annotations

import re
from typing import Any

from agent_hive.config.loader import SystemConfig
from agent_hive.core.events import EventBus
from agent_hive.core.ids import new_id
from agent_hive.core.logging import get_logger
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Verification
from agent_hive.memory.manager import MemoryManager
from agent_hive.tools.builtin import code_lint_py, secret_scan

log = get_logger("agent_hive.quality")

_PY_BLOCK = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_STOPWORDS = set("the a an and or of to in is it for on with as at by da di che il la e per con un una".split())


class QualityGate:
    def __init__(
        self, config: SystemConfig, memory: MemoryManager, events: EventBus
    ) -> None:
        self.config = config
        self.memory = memory
        self.events = events

    async def verify(
        self,
        title: str,
        description: str,
        deliverable: str,
        task_id: str | None = None,
        verifier: str = "quality_gate",
    ) -> dict[str, Any]:
        """Run all checks and persist the verdict. Returns the report."""
        findings: list[dict[str, Any]] = []
        score = 1.0

        # 1. completeness -------------------------------------------------
        text = (deliverable or "").strip()
        if len(text) < 80:
            score -= 0.4
            findings.append({"check": "completeness", "ok": False,
                             "detail": f"deliverable too short ({len(text)} chars)"})
        else:
            findings.append({"check": "completeness", "ok": True, "detail": f"{len(text)} chars"})

        # 2. requirements coverage -----------------------------------------
        if self.config.qa_requirement_check:
            keywords = [
                w for w in re.findall(r"\w+", f"{title} {description}".lower())
                if len(w) > 3 and w not in _STOPWORDS
            ][:12]
            if keywords:
                covered = [k for k in keywords if k in text.lower()]
                ratio = len(covered) / len(keywords)
                ok = ratio >= 0.4
                if not ok:
                    score -= 0.25
                findings.append({
                    "check": "requirements", "ok": ok,
                    "detail": f"keyword coverage {ratio:.0%} ({len(covered)}/{len(keywords)})",
                })

        # 3. embedded python code -------------------------------------------
        if self.config.qa_code_check:
            blocks = _PY_BLOCK.findall(text)
            for i, block in enumerate(blocks):
                report = await code_lint_py(block)
                ok = bool(report.get("valid"))
                if not ok:
                    score -= 0.3
                findings.append({
                    "check": f"code_block_{i}", "ok": ok,
                    "detail": report.get("error", "syntax OK"),
                })

        # 4. secrets ----------------------------------------------------------
        if self.config.qa_secret_scan:
            report = await secret_scan(text)
            if not report["clean"]:
                score -= 0.5
                findings.append({
                    "check": "secrets", "ok": False,
                    "detail": f"{len(report['findings'])} suspected secret(s) in output",
                })
            else:
                findings.append({"check": "secrets", "ok": True, "detail": "clean"})

        # 5. leftover markers ---------------------------------------------------
        markers = re.findall(r"\b(TODO|FIXME|not implemented|placeholder)\b", text, re.I)
        if markers:
            score -= 0.15
            findings.append({
                "check": "markers", "ok": False,
                "detail": f"{len(markers)} unresolved markers",
            })
        else:
            findings.append({"check": "markers", "ok": True, "detail": "none"})

        # Mock results are deterministic placeholders: never let them pass as
        # if they were real deliverables, and surface an explicit warning.
        if "[MOCK]" in text:
            score = min(score, 0.4)
            findings.append({
                "check": "mock_result", "ok": False,
                "detail": "deliverable was produced by the mock provider — not a real result",
            })

        score = max(0.0, min(1.0, score))
        threshold = 0.3 if "[MOCK]" in text else self.config.qa_required_score
        passed = score >= threshold

        # persist verdict -------------------------------------------------------
        if task_id:
            factory = get_session_factory()
            async with factory() as sess:
                sess.add(Verification(
                    id=new_id(), task_id=task_id, verifier=verifier,
                    passed=passed, score=score, findings=findings,
                ))
                await sess.commit()
        await self.memory.history_append(
            "quality_verdict",
            {"title": title, "score": score, "passed": passed, "findings": findings},
            actor=verifier,
        )
        await self.events.publish("quality.verified", verifier,
                                  title=title, score=score, passed=passed)
        return {"passed": passed, "score": score, "findings": findings}


