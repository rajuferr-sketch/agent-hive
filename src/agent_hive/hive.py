"""Hive — the composition root assembling every subsystem.

Dependency graph (acyclic)::

    settings/system-config ──▶ db ──▶ memory ──┐
                                               ├─▶ runtime ─▶ scheduler ─▶ master
    event-bus ─▶ task-manager ─────────────────┘

``startup()`` is idempotent and ordered: schema → agents → heartbeat →
scheduler → recovery of interrupted tasks.
"""

from __future__ import annotations

from typing import Any

from agent_hive.communication.bus import MessageBus
from agent_hive.config.loader import SystemConfig, load_system_config
from agent_hive.config.settings import get_settings
from agent_hive.core.events import EventBus
from agent_hive.core.logging import get_logger, setup_logging
from agent_hive.db.base import create_all, dispose_engine
from agent_hive.memory.manager import MemoryManager
from agent_hive.orchestrator.master import MasterAgent
from agent_hive.tasks.manager import TaskManager
from agent_hive.tasks.scheduler import Scheduler

log = get_logger("agent_hive.hive")


class Hive:
    """Owns every subsystem; a single instance per process."""

    def __init__(self) -> None:
        self.settings = get_settings()
        setup_logging(self.settings.log_level)
        self.config: SystemConfig = load_system_config()
        self.events = EventBus()
        self.memory = MemoryManager()
        self.bus = MessageBus()
        self.tasks = TaskManager(self.events)
        from agent_hive.agents.runtime import AgentRuntime  # late: avoid cycle

        self.runtime = AgentRuntime(self.events, self.memory, self.bus)
        self.scheduler = Scheduler(
            self.tasks,
            self.runtime,
            self.events,
            max_concurrency=self.settings.max_concurrency,
            poll_interval=self.settings.scheduler_interval,
        )
        self.master = MasterAgent(
            self.runtime, self.tasks, self.scheduler,
            self.memory, self.bus, self.events, self.config,
        )
        self._started = False

    async def startup(self) -> None:
        """Boot the system (idempotent)."""
        if self._started:
            return
        await create_all()
        loaded = self.runtime.load()
        await self.runtime.start()
        orphaned = await self.tasks.recover()
        self.scheduler.start()
        self.events.start()
        self._started = True
        log.info(
            "AgentHive started: %d agents, mock=%s, orphaned tasks recovered=%d",
            len(loaded), self.settings.allow_mock, orphaned,
        )
        await self.events.publish(
            "hive.started", "master",
            agents=loaded, mock=self.settings.allow_mock,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown (idempotent)."""
        if not self._started:
            return
        self._started = False
        await self.scheduler.stop()
        await self.runtime.stop()
        await self.events.stop()
        await dispose_engine()
        log.info("AgentHive stopped")

    # ------------------------------------------------------------- helpers
    async def run_mission(
        self, text: str, mode: str | None = None, title: str | None = None
    ) -> dict[str, Any]:
        """Delegate a full mission to the Master Agent."""
        return await self.master.handle_mission(text, mode=mode, title=title)

    def status(self) -> dict[str, Any]:
        """Non-async snapshot for the API/CLI status endpoints."""
        return {
            "version": "1.0.1",
            "agents_loaded": len(self.runtime.agents),
            "agent_names": list(self.runtime.agents),
            "mock_allowed": self.settings.allow_mock,
            "database": self.settings.database_url.split("://")[0],
            "config": {
                "simple_threshold": self.config.simple_threshold,
                "adaptive_threshold": self.config.adaptive_threshold,
                "complex_threshold": self.config.complex_threshold,
                "qa_required_score": self.config.qa_required_score,
            },
        }
