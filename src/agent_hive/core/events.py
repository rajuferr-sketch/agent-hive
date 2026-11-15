"""In-process event bus with an operation audit log.

Every meaningful operation (task transitions, messages, verifications,
memory writes) is published here. Subscribers include the WebSocket feed
and the persistent event log handled by the orchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_hive.core.ids import now_iso
from agent_hive.core.logging import get_logger

log = get_logger("agent_hive.events")

Subscriber = Callable[["Event"], Awaitable[None]]


@dataclass(slots=True)
class Event:
    kind: str
    actor: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=now_iso)


class EventBus:
    """Async pub/sub bus. Broadcasting never blocks nor raises."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._pump_task: asyncio.Task[None] | None = None

    # -- subscription -------------------------------------------------
    def subscribe(self, handler: Subscriber) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Subscriber) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    # -- publishing ----------------------------------------------------
    async def publish(self, kind: str, actor: str, **data: Any) -> Event:
        event = Event(kind=kind, actor=actor, data=data)
        await self._queue.put(event)
        return event

    async def _pump(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                for handler in list(self._subscribers):
                    try:
                        await handler(event)
                    except Exception:  # noqa: BLE001 — subscriber isolation
                        log.exception("Event subscriber failed")
            finally:
                self._queue.task_done()

    def start(self) -> None:
        """Start the background pump (idempotent)."""
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.get_running_loop().create_task(self._pump())

    async def stop(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
