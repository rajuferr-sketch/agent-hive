"""Tests for the persistent message bus."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from agent_hive.communication.bus import MASTER, MessageBus
from agent_hive.core.errors import CommunicationError
from agent_hive.db.models import Message


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def test_send_persists_message(bus: MessageBus) -> None:
    """send() writes the message to the database."""
    tag = _suffix()
    msg = await bus.send("alice-" + tag, "bob-" + tag, content={"hello": tag})
    history = await bus.history(agent="bob-" + tag)
    assert any(m.id == msg.id for m in history)
    assert history[0].from_agent == "alice-" + tag


async def test_send_rejects_empty_recipient(bus: MessageBus) -> None:
    """A message without recipient is a routing error."""
    with pytest.raises(CommunicationError):
        await bus.send("alice", "", content={})


async def test_unread_excludes_own_broadcasts(bus: MessageBus) -> None:
    """Your own broadcast never shows up in your own unread inbox."""
    tag = _suffix()
    sender, other = "carol-" + tag, "dave-" + tag
    msg = await bus.broadcast(sender, content={"tag": tag})

    own_inbox = await bus.unread(sender)
    assert not any(m.id == msg.id for m in own_inbox)

    other_inbox = await bus.unread(other)
    received = next(m for m in other_inbox if m.id == msg.id)
    assert received.to_agent == "*"


async def test_broadcast_reaches_registered_mailboxes(bus: MessageBus) -> None:
    """Broadcast delivery to a registered in-process mailbox is instant."""
    tag = _suffix()
    listener = "erin-" + tag
    bus.register_mailbox(listener)
    try:
        msg = await bus.broadcast("frank-" + tag, content={"tag": tag})
        delivered = await asyncio.wait_for(bus._mailboxes[listener].get(), timeout=2)
        assert delivered.id == msg.id
        assert delivered.to_agent == "*"
    finally:
        bus.unregister_mailbox(listener)


async def test_mark_read_clears_unread(bus: MessageBus) -> None:
    """mark_read() removes messages from the unread queue exactly once."""
    tag = _suffix()
    recipient = "gina-" + tag
    msg = await bus.send("hank-" + tag, recipient, content={"tag": tag})

    unread = await bus.unread(recipient)
    assert any(m.id == msg.id for m in unread)

    assert await bus.mark_read([msg.id]) == 1
    unread_after = await bus.unread(recipient)
    assert not any(m.id == msg.id for m in unread_after)
    assert await bus.mark_read([msg.id]) == 0  # already read


async def test_request_assistance_sets_kind_and_priority(bus: MessageBus) -> None:
    """Assistance requests are high-priority 'assistance' messages."""
    tag = _suffix()
    msg = await bus.request_assistance(
        "requester-" + tag, "helper-" + tag, "Need schema review", "detail here"
    )
    assert msg.kind == Message.KIND_ASSISTANCE
    assert msg.priority == 2
    assert msg.content == {"subject": "Need schema review", "detail": "detail here"}


async def test_challenge_sets_kind_and_priority(bus: MessageBus) -> None:
    """Challenges are the highest-priority messages."""
    tag = _suffix()
    msg = await bus.challenge(
        "challenger-" + tag, "author-" + tag, "unverified claim"
    )
    assert msg.kind == Message.KIND_CHALLENGE
    assert msg.priority == 1
    assert msg.content == {"reason": "unverified claim"}


async def test_history_filters_by_kind_and_agent(bus: MessageBus) -> None:
    """history() can filter by participant and kind."""
    tag = _suffix()
    a, b = "iva-" + tag, "jon-" + tag
    info = await bus.send(a, b, "info", {"n": 1})
    await bus.send(a, b, "problem", {"n": 2})

    both = await bus.history(agent=b)
    assert {m.id for m in both} >= {info.id}
    assert any(m.kind == "problem" for m in both)

    only_info = await bus.history(agent=b, kind="info")
    assert all(m.kind == "info" for m in only_info)
    assert any(m.id == info.id for m in only_info)


async def test_report_to_master_goes_to_master_mailbox_name(bus: MessageBus) -> None:
    """Direct reports use the reserved 'master' recipient name."""
    assert MASTER == "master"
    tag = _suffix()
    msg = await bus.send("worker-" + tag, MASTER, "response", {"tag": tag})
    history = await bus.history(agent=MASTER)
    assert any(m.id == msg.id and m.to_agent == MASTER for m in history)
