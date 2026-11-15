"""AgentRuntime — loads, registers and drives all specialized agents.

The runtime is the *only* owner of agent instances; the scheduler, the
Master Agent and the API all go through it. This inversion keeps the
dependency graph acyclic: agents never import orchestration code.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agent_hive.communication.bus import MessageBus
from agent_hive.config.loader import list_agent_names, load_agent_config
from agent_hive.config.settings import get_settings
from agent_hive.core.errors import ConfigError
from agent_hive.core.events import EventBus
from agent_hive.core.logging import get_logger
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Agent
from agent_hive.memory.manager import MemoryManager
from agent_hive.providers.factory import build_provider_chain

log = get_logger("agent_hive.runtime")


class AgentRuntime:
    """Registry + supervision of every specialized agent in the process."""

    def __init__(
        self,
        events: EventBus,
        memory: MemoryManager,
        bus: MessageBus,
    ) -> None:
        self.events = events
        self.memory = memory
        self.bus = bus
        self.agents: dict[str, Any] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._round_robin = 0

    # ---------------------------------------------------------------- loading
    def load(self, names: list[str] | None = None) -> list[str]:
        """Instantiate agents from configs. Role classes are discovered
        dynamically from ``agents/roles/`` — adding an agent requires no
        runtime change."""
        from agent_hive.agents.roles import ROLE_REGISTRY  # local: avoid cycle

        names = names or list_agent_names()
        if not names:
            raise ConfigError("No agent configurations found in configs/agents/")
        loaded: list[str] = []
        for name in names:
            config = load_agent_config(name)
            role_cls = ROLE_REGISTRY.get(config.role)
            if role_cls is None:
                raise ConfigError(
                    f"Agent '{name}' declares role '{config.role}' but no role "
                    f"class is registered. Available: {sorted(ROLE_REGISTRY)}"
                )
            provider = build_provider_chain(config.providers)
            agent = role_cls(config, self.memory, self.bus, self.events, provider)
            self.agents[agent.name] = agent
            loaded.append(agent.name)
            self.bus.register_mailbox(agent.name)
        log.info("Loaded %d agents: %s", len(loaded), loaded)
        return loaded

    # -------------------------------------------------------------- selection
    def best_agent_for(
        self, capabilities_hint: list[str] | None = None, exclude_busy: bool = False
    ) -> str | None:
        """Pick the most capable idle agent (capability match + round robin)."""
        hint = set(capabilities_hint or [])
        candidates = [
            a for a in self.agents.values()
            if not (exclude_busy and a.busy)
        ]
        if not candidates:
            return None
        if hint:
            scored = [
                (len(hint & set(a.CAPABILITIES) | hint & set(a.config.capabilities)), a)
                for a in candidates
            ]
            scored.sort(key=lambda x: -x[0])
            if scored[0][0] > 0:
                return scored[0][1].name
        self._round_robin = (self._round_robin + 1) % len(candidates)
        return candidates[self._round_robin].name

    def agents_with_capability(self, capability: str) -> list[str]:
        return [
            a.name for a in self.agents.values()
            if capability in a.CAPABILITIES or capability in a.config.capabilities
        ]

    # -------------------------------------------------------------- execution
    async def execute(self, agent_name: str, task: Any) -> dict[str, Any]:
        """Run one task on one agent (called by the scheduler)."""
        agent = self.agents.get(agent_name)
        if agent is None:
            raise ConfigError(f"Unknown agent '{agent_name}'")
        return await agent.run_task(task)

    async def run_direct(
        self, agent_name: str, title: str, payload: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Convenience: execute an ad-hoc request without the task queue."""
        agent = self.agents.get(agent_name)
        if agent is None:
            raise ConfigError(f"Unknown agent '{agent_name}'")
        task = Task(
            id="direct-" + agent_name, title=title, description=description,
            payload=payload or {},
        )
        return await agent.run_task(task)

    # ---------------------------------------------------------- persistence
    async def sync_registry(self) -> None:
        """Upsert the ``agents`` table from the in-memory registry."""
        factory = get_session_factory()
        async with factory() as sess:
            for agent in self.agents.values():
                existing = (await sess.execute(
                    select(Agent).where(Agent.name == agent.name)
                )).scalar_one_or_none()
                cfg = agent.config
                if existing is None:
                    sess.add(Agent(
                        name=agent.name, title=agent.title, role=agent.ROLE,
                        description=cfg.description, status="idle",
                        capabilities=sorted(set(agent.CAPABILITIES) | set(cfg.capabilities)),
                        provider_chain=agent.provider.descriptions,
                        params=cfg.params, memory_enabled=cfg.memory.individual,
                        last_heartbeat=datetime.now(UTC),
                    ))
                else:
                    existing.title = agent.title
                    existing.role = agent.ROLE
                    existing.description = cfg.description
                    existing.capabilities = sorted(
                        set(agent.CAPABILITIES) | set(cfg.capabilities)
                    )
                    existing.provider_chain = agent.provider.descriptions
                    existing.last_heartbeat = datetime.now(UTC)
            await sess.commit()

    async def _heartbeat_loop(self) -> None:
        interval = get_settings().heartbeat_interval
        while True:
            try:
                await asyncio.sleep(interval)
                await self.sync_registry()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 — supervision never dies
                log.exception("Heartbeat failed")

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.sync_registry()
        self._heartbeat_task = asyncio.get_running_loop().create_task(
            self._heartbeat_loop()
        )
        await self.events.publish("runtime.started", "runtime",
                                  agents=list(self.agents))

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        for name in list(self.agents):
            self.bus.unregister_mailbox(name)
        for agent in self.agents.values():
            await agent.provider.aclose()
        await self.events.publish("runtime.stopped", "runtime")

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": a.name,
                "title": a.title,
                "role": a.ROLE,
                "description": a.config.description,
                "capabilities": sorted(set(a.CAPABILITIES) | set(a.config.capabilities)),
                "tools": a.config.tools,
                "providers": a.provider.descriptions,
                "busy": a.busy,
                "memory": {
                    "individual": a.config.memory.individual,
                    "shared_access": a.config.memory.shared_access,
                    "shared_write": a.config.memory.shared_write,
                },
            }
            for a in self.agents.values()
        ]


# Imported late for typing/usage in run_direct
from agent_hive.db.models import Task  # noqa: E402
