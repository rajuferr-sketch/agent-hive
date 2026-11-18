"""Master Agent — the orchestrator of the entire system.

Responsibilities (per the system specification):

1. receive & understand any user request;
2. analyze its complexity;
3. split it into subtasks when necessary;
4. pick the most suitable agents;
5. assign tasks;
6. monitor progress continuously;
7. detect errors, conflicts and insufficient results;
8. request revisions/deepening from agents;
9. integrate contributions;
10. verify the final result before delivery.

The Master Agent privileges *intelligent delegation*: it executes work
itself only when no specialized agent can (integration synthesis uses
the integration agent's provider, not the master's).

Operating modes:
* A — simple: 1 agent, independent execution.
* C — adaptive: 2-10 agents, one per workstream.
* B — collective: all 20 agents on the same mission, with cross-review,
  conflict detection, integration and final validation.
"""

from __future__ import annotations

from typing import Any

from agent_hive.communication.bus import MessageBus
from agent_hive.config.loader import SystemConfig
from agent_hive.core.events import EventBus
from agent_hive.core.ids import new_id, now_iso
from agent_hive.core.logging import get_logger
from agent_hive.db.models import Task
from agent_hive.memory.manager import MemoryManager
from agent_hive.orchestrator.planner import (
    MODE_A,
    MODE_B,
    MODE_C,
    Analysis,
    Workstream,
    analyze,
    choose_mode,
    plan_workstreams,
)
from agent_hive.orchestrator.quality import QualityGate
from agent_hive.tasks.manager import TaskManager
from agent_hive.tasks.scheduler import Scheduler

log = get_logger("agent_hive.master")

MAX_REVISION_ROUNDS = 2


class MasterAgent:
    """Autonomous orchestrator built on the task manager and the runtime."""

    name = "master"

    def __init__(
        self,
        runtime: Any,
        tasks: TaskManager,
        scheduler: Scheduler,
        memory: MemoryManager,
        bus: MessageBus,
        events: EventBus,
        config: SystemConfig,
    ) -> None:
        self.runtime = runtime
        self.tasks = tasks
        self.scheduler = scheduler
        self.memory = memory
        self.bus = bus
        self.events = events
        self.config = config
        self.quality = QualityGate(config, memory, events)

    # ------------------------------------------------------------ entry point
    async def handle_mission(
        self,
        text: str,
        mode: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Full mission lifecycle: analyze → delegate → monitor → integrate
        → verify → deliver."""
        if not (text or "").strip():
            raise ValueError("Mission text must not be empty")

        analysis = analyze(text, self.config)
        selected_mode = choose_mode(analysis, self.config, forced=mode)
        title = title or (text.strip()[:70] + ("…" if len(text.strip()) > 70 else ""))
        mission_id = new_id()

        await self.events.publish(
            "mission.started", self.name,
            mission_id=mission_id, mode=selected_mode,
            complexity=analysis.complexity, domains=analysis.domains,
        )
        log.info("Mission %s started (mode=%s, complexity=%.2f, domains=%s)",
                 mission_id, selected_mode, analysis.complexity, analysis.domains)

        # Shared mission context — every authorized agent reads this.
        await self.memory.share(
            f"mission:{mission_id}",
            {
                "title": title,
                "request": text[:4000],
                "keywords": analysis.keywords,
                "mode": selected_mode,
                "started_at": now_iso(),
            },
            author=self.name,
        )
        # Kickoff broadcast: real coordination, not simulated.
        involved = self._select_agents(analysis, selected_mode)
        await self.bus.broadcast(
            self.name, "info",
            {"subject": f"Mission {mission_id} started",
             "detail": title, "agents": involved},
        )

        # 1) planning & delegation --------------------------------------
        await self._delegate(mission_id, title, text, analysis, involved)

        # 2) monitoring ---------------------------------------------------
        try:
            outcome = await self.scheduler.wait_for_mission(
                mission_id, max_wait_s=1800.0
            )
        except Exception as exc:  # noqa: BLE001 — deliver partial results
            log.error("Mission monitoring interrupted: %s", exc)
            outcome = {"error": str(exc)}

        # 3) integration ---------------------------------------------------
        deliverable = await self._integrate(mission_id, selected_mode, analysis)

        # 4) verification & revision loop ---------------------------------
        gate = await self.quality.verify(title, text, deliverable["text"],
                                         task_id=deliverable.get("task_id"))
        rounds = 0
        while not gate["passed"] and rounds < MAX_REVISION_ROUNDS:
            rounds += 1
            log.warning("Quality gate failed (score %.2f) — revision round %d",
                        gate["score"], rounds)
            deliverable = await self._revise(mission_id, deliverable, gate, analysis)
            gate = await self.quality.verify(title, text, deliverable["text"],
                                             task_id=deliverable.get("task_id"))

        # 5) delivery ---------------------------------------------------------
        tasks = await self.tasks.list(mission_id=mission_id, limit=200)
        report = {
            "mission_id": mission_id,
            "title": title,
            "mode": selected_mode,
            "complexity": analysis.complexity,
            "domains": analysis.domains,
            "agents": involved,
            "tasks": [
                {"id": t.id, "title": t.title, "agent": t.agent_name,
                 "status": t.status, "attempts": t.attempts}
                for t in tasks
            ],
            "outcome": outcome,
            "deliverable": deliverable["text"],
            "deliverable_by": deliverable.get("by", self.name),
            "conflicts": deliverable.get("conflicts", []),
            "quality": gate,
            "revision_rounds": rounds,
            "completed_at": now_iso(),
        }
        await self.memory.history_append(
            "mission_final",
            {"mission_id": mission_id, "title": title, "mode": selected_mode,
             "quality_score": gate["score"], "passed": gate["passed"]},
            actor=self.name,
        )
        await self.events.publish(
            "mission.completed", self.name,
            mission_id=mission_id, passed=gate["passed"], score=gate["score"],
        )
        return report

    # ------------------------------------------------------------- delegation
    def _select_agents(self, analysis: Analysis, mode: str) -> list[str]:
        """Choose participants: 1 for A, workstream owners for C, all 20 for B."""
        all_agents = list(self.runtime.agents)
        if mode == MODE_A:
            pick = self._agent_for_capability(analysis.domains[0] if analysis.domains else "analysis")
            return [pick] if pick else all_agents[:1]
        if mode == MODE_C:
            agents: list[str] = []
            for domain in analysis.domains or ["code"]:
                pick = self._agent_for_capability(domain)
                if pick and pick not in agents:
                    agents.append(pick)
            for role in ("verifier", "qa"):
                pick = self._agent_for_capability(role)
                if pick and pick not in agents:
                    agents.append(pick)
            return agents[: min(
                self.config.adaptive_max_agents,
                max(self.config.adaptive_min_agents, len(agents)),
            )]
        return all_agents  # collective: everyone participates

    def _agent_for_capability(self, domain: str) -> str | None:
        from agent_hive.orchestrator.planner import DOMAIN_CAPABILITIES
        for capability in DOMAIN_CAPABILITIES.get(domain, [domain]):
            holders = self.runtime.agents_with_capability(capability)
            if holders:
                return holders[0]
        return self.runtime.best_agent_for(capabilities_hint=[])

    async def _delegate(
        self,
        mission_id: str,
        title: str,
        text: str,
        analysis: Analysis,
        involved: list[str],
    ) -> list[str]:
        """Create the mission DAG: workstreams + integration + QA + validation."""
        streams = plan_workstreams(analysis, self.config)
        task_ids: list[str] = []
        base_payload = {
            "mission_id": mission_id,
            "mission_request": text[:4000],
            "keywords": analysis.keywords,
        }

        assigned: set[str] = set()
        for stream in streams:
            agent = self._stream_agent(stream, involved)
            if agent:
                assigned.add(agent)
            task = await self.tasks.create(
                title=stream.title,
                description=stream.description,
                payload={**base_payload, "capabilities_hint": [stream.capability]},
                mission_id=mission_id,
                agent_name=agent,
                mode=analysis.mode,
                priority=2,
            )
            task_ids.append(task.id)

        if analysis.mode == MODE_B:
            # Collective mode: every roster agent gets a real, distinct task.
            for agent_name in involved:
                if agent_name in assigned:
                    continue
                agent = self.runtime.agents.get(agent_name)
                role = getattr(agent, "ROLE", agent_name)
                task = await self.tasks.create(
                    title=f"Contribution from {role} ({agent_name})",
                    description=(
                        f"Contribute from your {role} competence: analyze the shared "
                        "mission context and produce your specific contribution, "
                        "aligned with the other workstreams."
                    ),
                    payload={**base_payload},
                    mission_id=mission_id,
                    agent_name=agent_name,
                    mode=MODE_B,
                    priority=2,
                )
                task_ids.append(task.id)
                assigned.add(agent_name)

        if analysis.mode == MODE_A:
            return task_ids

        pipeline: list[str] = []
        if analysis.mode == MODE_B:
            # Cross-review of all contributions before integration
            verifier = self._agent_for_capability("verification") or self.runtime.best_agent_for()
            review = await self.tasks.create(
                title="Cross-review of contributions",
                description=(
                    "Examine all agent results of this mission for contradictions, "
                    "gaps and unverified claims; challenge questionable results."
                ),
                payload={**base_payload, "results_of": list(task_ids)},
                mission_id=mission_id,
                agent_name=verifier,
                mode=MODE_B,
                priority=3,
                depends_on=list(task_ids),
            )
            pipeline.append(review.id)

        integration_agent = self._agent_for_capability("integration") or self.runtime.best_agent_for()
        integration = await self.tasks.create(
            title="Integrate contributions",
            description=(
                "Merge every agent contribution into one coherent, complete "
                "deliverable; resolve conflicts in favor of verified content."
            ),
            payload={**base_payload, "results_of": list(task_ids)},
            mission_id=mission_id,
            agent_name=integration_agent,
            mode=analysis.mode,
            priority=2,
            depends_on=task_ids + pipeline,
        )
        qa_agent = self._agent_for_capability("quality")
        qa = await self.tasks.create(
            title="Quality assurance review",
            description="Score the integrated deliverable against acceptance criteria.",
            payload={**base_payload, "integrated_task": integration.id},
            mission_id=mission_id,
            agent_name=qa_agent,
            mode=analysis.mode,
            priority=2,
            depends_on=[integration.id],
        )
        validator_agent = self._agent_for_capability("validation")
        validation = await self.tasks.create(
            title="Final validation",
            description="Accept or reject the deliverable against the original request.",
            payload={**base_payload, "qa_task": qa.id, "integrated_task": integration.id},
            mission_id=mission_id,
            agent_name=validator_agent,
            mode=analysis.mode,
            priority=1,
            depends_on=[qa.id],
        )
        return task_ids + [integration.id, qa.id, validation.id]

    def _stream_agent(self, stream: Workstream, involved: list[str]) -> str | None:
        pick = self._agent_for_capability(stream.capability)
        return pick or next((a for a in involved if a), None)

    # ------------------------------------------------------------- integration
    async def _integrate(
        self, mission_id: str, mode: str, analysis: Analysis
    ) -> dict[str, Any]:
        """Merge agent contributions into the final deliverable."""
        tasks = await self.tasks.list(mission_id=mission_id, limit=200)
        results = [
            t for t in tasks
            if t.status == Task.STATUS_COMPLETED and t.result
        ]
        failed = [t for t in tasks if t.status == Task.STATUS_FAILED]

        conflicts = self._detect_conflicts(results, failed)

        if mode == MODE_A and results:
            best = results[0].result
            return {
                "text": best.get("text", ""),
                "by": best.get("agent", "unknown"),
                "task_id": results[0].id,
                "conflicts": conflicts,
            }

        # Prefer the integration agent's synthesis; fall back to template merge.
        integration_task = next(
            (t for t in tasks if t.title == "Integrate contributions"
             and t.status == Task.STATUS_COMPLETED),
            None,
        )
        if integration_task and integration_task.result.get("text"):
            return {
                "text": integration_task.result["text"],
                "by": integration_task.agent_name,
                "task_id": integration_task.id,
                "conflicts": conflicts,
            }
        return {
            "text": self._template_merge(title=mission_id, results=results, failed=failed),
            "by": self.name,
            "task_id": None,
            "conflicts": conflicts,
        }

    async def _revise(
        self,
        mission_id: str,
        deliverable: dict[str, Any],
        gate: dict[str, Any],
        analysis: Analysis,
    ) -> dict[str, Any]:
        """Ask the integration agent for one revision round with feedback."""
        try:
            agent_name = (
                deliverable.get("by") if deliverable.get("by") != self.name
                else self._agent_for_capability("integration")
            ) or self.runtime.best_agent_for()
            payload = {
                "mission_id": mission_id,
                "revision": True,
                "draft": deliverable["text"][:6000],
                "quality_findings": gate["findings"],
                "keywords": analysis.keywords,
            }
            result = await self.runtime.run_direct(
                agent_name,
                f"Revision required — {deliverable.get('task_id') or mission_id}",
                payload=payload,
                description="Revise the deliverable to fix the quality findings.",
            )
            deliverable = {
                "text": result.get("text", deliverable["text"]),
                "by": agent_name,
                "task_id": None,
                "conflicts": deliverable.get("conflicts", []),
            }
        except Exception:  # noqa: BLE001 — never lose the previous draft
            log.exception("Revision round failed; keeping previous deliverable")
        return deliverable

    # ------------------------------------------------------------- conflicts
    @staticmethod
    def _detect_conflicts(
        results: list[Any], failed: list[Any]
    ) -> list[dict[str, Any]]:
        """Heuristic contradiction/gap detection across contributions."""
        conflicts: list[dict[str, Any]] = []
        failed_check_agents = [
            t.agent_name for t in results
            if isinstance(t.result, dict)
            and not t.result.get("self_check", {}).get("passed", True)
        ]
        for agent in failed_check_agents:
            conflicts.append({
                "type": "unverified_output",
                "agent": agent,
                "detail": "agent's own self-check flagged issues",
            })
        for t in failed:
            conflicts.append({
                "type": "failed_task",
                "agent": t.agent_name,
                "detail": (t.error or "unknown error")[:200],
            })
        # Verifier rejections
        for t in results:
            data = t.result.get("data") if isinstance(t.result, dict) else None
            if isinstance(data, dict) and data.get("verdict") == "reject":
                conflicts.append({
                    "type": "rejected_by_validator",
                    "agent": t.agent_name,
                    "detail": str(data.get("reason", ""))[:200],
                })
        return conflicts

    @staticmethod
    def _template_merge(
        title: str, results: list[Any], failed: list[Any]
    ) -> str:
        """Deterministic merge used when no LLM synthesis is available."""
        sections: list[str] = [f"# Deliverable — mission {title}", ""]
        for t in results:
            agent = t.agent_name or "unknown"
            text = (t.result or {}).get("text", "")
            sections.append(f"## Contribution — {agent}")
            sections.append(text[:4000])
            sections.append("")
        if failed:
            sections.append("## Known issues")
            for t in failed:
                sections.append(f"- {t.title} ({t.agent_name}): {t.error}")
            sections.append("")
        return "\n".join(sections)
