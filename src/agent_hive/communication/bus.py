"""Internal messaging system between agents (and the Master Agent).

Every message is persisted in the ``messages`` table AND, when the
recipient lives in the same process, delivered instantly through an
in-process asyncio mailbox. Message kinds cover the full collaboration
protocol: info, request, response, assistance, problem, proposal,
challenge, review.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hive.core.errors import CommunicationError
from agent_hive.core.ids import new_id
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Message

MASTER = "master"
BROADCAST = "*"


class MessageBus:
    """Persistent message bus with instant in-process delivery."""

    def __init__(self) -> None:
        self._mailboxes: dict[str, asyncio.Queue[Message]] = {}

    # -- registration ---------------------------------------------------
    def register_mailbox(self, agent: str) -> None:
        self._mailboxes.setdefault(agent, asyncio.Queue())

    def unregister_mailbox(self, agent: str) -> None:
        self._mailboxes.pop(agent, None)

    # -- sending --------------------------------------------------------
    async def send(
        self,
        from_agent: str,
        to_agent: str,
        kind: str = Message.KIND_INFO,
        content: dict[str, Any] | None = None,
        task_id: str | None = None,
        priority: int = 5,
        session: AsyncSession | None = None,
    ) -> Message:
        """Send a direct message (persisted + instant mailbox delivery)."""
        if not to_agent:
            raise CommunicationError("Message recipient must not be empty")
        msg = Message(
            id=new_id(), from_agent=from_agent, to_agent=to_agent,
            task_id=task_id, kind=kind, priority=priority,
            content=content or {},
        )

        async def _persist(sess: AsyncSession) -> Message:
            sess.add(msg)
            await sess.commit()
            await sess.refresh(msg)
            return msg

        if session is not None:
            session.add(msg)
            await session.flush()
        else:
            factory = get_session_factory()
            async with factory() as sess:
                await _persist(sess)
        await self._deliver(msg)
        return msg

    async def broadcast(
        self,
        from_agent: str,
        kind: str = Message.KIND_INFO,
        content: dict[str, Any] | None = None,
        task_id: str | None = None,
        priority: int = 5,
        session: AsyncSession | None = None,
    ) -> Message:
        return await self.send(
            from_agent, BROADCAST, kind, content, task_id, priority, session
        )

    async def _deliver(self, msg: Message) -> None:
        targets = (
            list(self._mailboxes) if msg.to_agent == BROADCAST else [msg.to_agent]
        )
        for target in targets:
            box = self._mailboxes.get(target)
            if box is not None:
                await box.put(msg)

    # -- reading --------------------------------------------------------
    async def unread(self, agent: str, limit: int = 50) -> list[Message]:
        factory = get_session_factory()
        async with factory() as sess:
            stmt = (
                select(Message)
                .where(
                    Message.to_agent.in_([agent, BROADCAST]),
                    Message.read_at.is_(None),
                    Message.from_agent != agent,  # never echo own broadcasts
                )
                .order_by(Message.priority, Message.created_at.desc())
                .limit(limit)
            )
            return list((await sess.execute(stmt)).scalars())

    async def mark_read(self, message_ids: list[str]) -> int:
        if not message_ids:
            return 0
        factory = get_session_factory()
        async with factory() as sess:
            res = await sess.execute(
                update(Message)
                .where(Message.id.in_(message_ids), Message.read_at.is_(None))
                .values(read_at=datetime.now(UTC))
            )
            await sess.commit()
            return res.rowcount or 0

    async def history(
        self,
        agent: str | None = None,
        task_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Message]:
        factory = get_session_factory()
        async with factory() as sess:
            stmt = select(Message)
            if agent:
                stmt = stmt.where(
                    (Message.from_agent == agent) | (Message.to_agent == agent)
                )
            if task_id:
                stmt = stmt.where(Message.task_id == task_id)
            if kind:
                stmt = stmt.where(Message.kind == kind)
            stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
            return list((await sess.execute(stmt)).scalars())

    # -- collaboration helpers -------------------------------------------
    async def request_assistance(
        self, from_agent: str, to_agent: str, subject: str, detail: str,
        task_id: str | None = None,
    ) -> Message:
        return await self.send(
            from_agent, to_agent, Message.KIND_ASSISTANCE,
            {"subject": subject, "detail": detail}, task_id, priority=2,
        )

    async def propose(
        self, from_agent: str, to_agent: str, proposal: str, task_id: str | None = None,
    ) -> Message:
        return await self.send(
            from_agent, to_agent, Message.KIND_PROPOSAL,
            {"proposal": proposal}, task_id,
        )

    async def challenge(
        self, from_agent: str, to_agent: str, reason: str, task_id: str | None = None,
    ) -> Message:
        """Contest a result that has not been sufficiently verified."""
        return await self.send(
            from_agent, to_agent, Message.KIND_CHALLENGE,
            {"reason": reason}, task_id, priority=1,
        )
