"""BaseAgent — the foundation every specialized agent builds on.

Responsibilities (mirrors the project specification):

* identity & role (from YAML config + role class);
* operational instructions (``system_prompt``);
* competences & tools (``CAPABILITIES`` + permission-checked tool use);
* individual memory & authorized access to shared memory;
* reporting (event bus + persistent messages);
* error handling (task failures propagate to the scheduler's retry logic);
* asking for collaboration (direct messages, broadcast, proposals,
  challenges);
* self-verification (``self_check`` hook).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent_hive.communication.bus import MASTER, MessageBus
from agent_hive.config.loader import AgentConfig
from agent_hive.core.events import EventBus
from agent_hive.core.logging import get_logger
from agent_hive.db.models import Task
from agent_hive.memory.manager import MemoryManager
from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.tools.registry import REGISTRY

log = get_logger("agent_hive.agent")


@dataclass(slots=True)
class TaskContext:
    """Information gathered before prompting the model."""

    task_id: str
    title: str
    description: str
    payload: dict[str, Any] = field(default_factory=dict)
    shared_knowledge: list[dict[str, Any]] = field(default_factory=list)
    inbox: list[dict[str, Any]] = field(default_factory=list)


class BaseAgent:
    """Abstract specialized agent. Role subclasses implement the hooks."""

    ROLE = "generic"
    CAPABILITIES: list[str] = []

    def __init__(
        self,
        config: AgentConfig,
        memory: MemoryManager,
        bus: MessageBus,
        events: EventBus,
        provider: LLMProvider,
    ) -> None:
        self.config = config
        self.name = config.name
        self.title = config.title
        self.memory = memory
        self.bus = bus
        self.events = events
        self.provider = provider
        self.params: dict[str, Any] = dict(config.params)
        self.busy: bool = False
        log.info("Agent initialized: %s (role=%s, providers=%s)",
                 self.name, self.ROLE, provider.descriptions)

    # ---------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        """Operational instructions. Role classes may extend this."""
        capabilities = ", ".join(sorted(set(self.CAPABILITIES) | set(self.config.capabilities)))
        tools = ", ".join(self.config.tools) or "none"
        return (
            f"You are {self.title} (id: {self.name}), the {self.ROLE} agent of AgentHive.\n"
            f"Mission: {self.config.description}\n"
            f"Core competences: {capabilities}\n"
            f"Authorized tools: {tools}\n\n"
            "Operating rules:\n"
            "1. Work strictly within your competences; say so when a request "
            "falls outside them.\n"
            "2. Prefer structured JSON output with the keys: "
            '"analysis", "output", "checklist".\n'
            "3. Flag uncertainty explicitly instead of inventing facts.\n"
            "4. If you cannot complete the task, include the key "
            '"blocked" with the reason and the agent you need help from.\n'
            "5. Never reveal or invent credentials, API keys or secrets.\n"
        )

    # ------------------------------------------------------------------ hooks
    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        """Role-specific post-processing hook (default: identity)."""
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        """Self-verification: output completeness + requirement coverage."""
        notes: list[str] = []
        passed = bool(text and text.strip())
        if not passed:
            notes.append("empty output")
        requirements = task.payload.get("requirements") or []
        if isinstance(requirements, str):
            requirements = [requirements]
        missing = [
            req for req in requirements
            if req and req.lower() not in text.lower()
        ]
        if requirements and missing:
            notes.append(f"requirements not covered: {missing}")
            passed = False
        if re.search(r"\b(TODO|FIXME|not implemented|placeholder)\b", text, re.I):
            notes.append("output contains TODO/placeholder markers")
            passed = False
        return {"passed": passed, "notes": notes}

    # ------------------------------------------------------------------- core
    async def run_task(self, task: Task) -> dict[str, Any]:
        """Execute one task end-to-end and return the structured result."""
        self.busy = True
        try:
            context = await self._gather_context(task)
            messages = [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self._build_user_message(context)},
            ]
            completion = await self.provider.complete(messages, **self.params)
            # Preserve any non-JSON tail (fenced code blocks, markdown) that
            # specialize() may drop when re-serializing the parsed payload.
            original = completion.text
            original_tail = ""
            json_match = re.search(r"\{.*\}", original, re.DOTALL)
            if json_match:
                original_tail = original[json_match.end():]
            completion = await self.specialize(task, completion)
            if (
                original_tail
                and completion.text != original
                and not completion.text.rstrip().endswith(original_tail.rstrip())
            ):
                completion.text = completion.text.rstrip() + "\n" + original_tail
            check = await self.self_check(task, completion.text)
            parsed = self._parse_json(completion.text)

            await self._persist_knowledge(task, completion, check)
            await self.events.publish(
                "agent.task_done", self.name,
                task_id=task.id, mock=completion.mock,
                self_check=check["passed"],
            )
            return {
                "agent": self.name,
                "role": self.ROLE,
                "title": self.title,
                "text": completion.text,
                "data": parsed if isinstance(parsed, dict) else {},
                "self_check": check,
                "provider": completion.provider,
                "model": completion.model,
                "mock": completion.mock,
            }
        finally:
            self.busy = False

    # --------------------------------------------------------------- context
    async def _gather_context(self, task: Task) -> TaskContext:
        context = TaskContext(
            task_id=task.id, title=task.title,
            description=task.description, payload=task.payload or {},
        )
        # Shared memory: authorized read access
        if self.config.memory.shared_access:
            query = (task.title or "")[:60]
            hits = await self.memory.search(query, scope="shared", limit=5)
            context.shared_knowledge = [
                {"key": h.key, "version": h.version, "value": h.value} for h in hits
            ]
        # Unread internal messages (request/assistance/review traffic)
        try:
            unread = await self.bus.unread(self.name, limit=10)
            context.inbox = [
                {"from": m.from_agent, "kind": m.kind, "content": m.content}
                for m in unread
            ]
            await self.bus.mark_read([m.id for m in unread])
        except Exception:  # noqa: BLE001 — inbox is best-effort
            log.debug("Inbox fetch failed for %s", self.name)
        return context

    def _build_user_message(self, context: TaskContext) -> str:
        parts = [f"TASK #{context.task_id}: {context.title}"]
        if context.description:
            parts.append(f"Description: {context.description}")
        payload_ctx = {
            k: v for k, v in context.payload.items()
            if k not in ("requirements", "capabilities_hint")
        }
        if payload_ctx:
            parts.append("Context: " + json.dumps(payload_ctx, ensure_ascii=False)[:4000])
        requirements = context.payload.get("requirements")
        if requirements:
            parts.append("Requirements: " + "; ".join(map(str, requirements)))
        if context.shared_knowledge:
            parts.append(
                "Shared knowledge: "
                + json.dumps(context.shared_knowledge, ensure_ascii=False)[:2000]
            )
        if context.inbox:
            parts.append(
                "Unread messages: "
                + json.dumps(context.inbox, ensure_ascii=False)[:2000]
            )
        return "\n".join(parts)

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract the first JSON object from the completion, if any."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------- memory I/O
    async def remember(self, key: str, value: dict[str, Any]) -> None:
        """Write to individual memory (always authorized)."""
        if self.config.memory.individual:
            await self.memory.remember_individual(self.name, key, value)

    async def recall(self, key: str) -> dict[str, Any] | None:
        entry = await self.memory.recall_individual(self.name, key)
        return entry.value if entry else None

    async def share_knowledge(self, key: str, value: dict[str, Any]) -> None:
        """Write to shared memory — requires explicit authorization."""
        if not self.config.memory.shared_write:
            log.warning(
                "Agent %s attempted unauthorized shared-memory write", self.name
            )
            return
        await self.memory.share(key, value, author=self.name)

    async def _persist_knowledge(
        self, task: Task, completion: CompletionResult, check: dict[str, Any]
    ) -> None:
        await self.remember(
            f"task:{task.id}",
            {
                "title": task.title,
                "summary": (completion.text or "")[:500],
                "provider": completion.provider,
                "mock": completion.mock,
                "self_check": check,
            },
        )
        # Historical memory: every important outcome is recorded forever
        await self.memory.history_append(
            "task_result",
            {
                "task_id": task.id, "agent": self.name, "role": self.ROLE,
                "title": task.title, "outcome": (completion.text or "")[:1000],
                "passed": check["passed"],
            },
            actor=self.name,
        )
        if self.config.memory.shared_write:
            await self.share_knowledge(
                f"result:{task.id}",
                {"agent": self.name, "summary": (completion.text or "")[:500]},
            )

    # ----------------------------------------------------------------- tools
    async def use_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a tool with permission enforcement."""
        return await REGISTRY.run(self.name, self.config.tools, name, **kwargs)

    # ---------------------------------------------------------- collaboration
    async def ask_colleague(
        self, colleague: str, subject: str, detail: str, task_id: str | None = None
    ) -> None:
        await self.bus.request_assistance(self.name, colleague, subject, detail, task_id)

    async def broadcast(self, subject: str, detail: str, task_id: str | None = None) -> None:
        await self.bus.send(
            self.name, "*", "info", {"subject": subject, "detail": detail}, task_id
        )

    async def challenge_result(self, colleague: str, reason: str, task_id: str | None) -> None:
        await self.bus.challenge(self.name, colleague, reason, task_id)

    async def report_to_master(self, subject: str, detail: str, task_id: str | None = None) -> None:
        """Send a report to the Master Agent."""
        await self.bus.send(
            self.name, MASTER, "response",
            {"subject": subject, "detail": detail}, task_id,
        )
