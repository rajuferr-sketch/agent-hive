"""Tests for the three-tier versioned memory manager."""

from __future__ import annotations

import uuid

import pytest

from agent_hive.config.settings import get_settings
from agent_hive.db.models import Memory
from agent_hive.memory.manager import MemoryManager


def _key(prefix: str) -> str:
    """Unique per-test key so tests can share one database safely."""
    return f"{prefix}:{uuid.uuid4().hex[:8]}"


async def test_remember_individual_upsert_bumps_version() -> None:
    """Re-writing the same individual key bumps the version in place."""
    memory = MemoryManager()
    agent, key = "mem-agent-1", _key("note")
    first = await memory.remember_individual(agent, key, {"v": 1})
    assert first.version == 1
    second = await memory.remember_individual(agent, key, {"v": 2})
    assert second.id == first.id, "upsert keeps a single canonical entry"
    assert second.version == 2
    assert second.value == {"v": 2}
    recalled = await memory.recall_individual(agent, key)
    assert recalled is not None and recalled.value == {"v": 2}


async def test_share_creates_v1_then_v2_and_archives() -> None:
    """Shared upserts bump versions and archive the previous value."""
    memory = MemoryManager()
    key = _key("shared-fact")
    v1 = await memory.share(key, {"fact": "one"}, author="author-a")
    assert v1.version == 1
    assert v1.agent_name is None  # NULL agent => shared/global

    v2 = await memory.share(key, {"fact": "two"}, author="author-b")
    assert v2.id == v1.id
    assert v2.version == 2
    assert v2.value == {"fact": "two"}

    current = await memory.read_shared(key)
    assert current is not None and current.value == {"fact": "two"}

    archived = [
        entry for entry in await memory.list_scope(Memory.SCOPE_HISTORY)
        if entry.key == key
    ]
    assert len(archived) == 1
    assert archived[0].value["fact"] == "one"          # previous version
    assert archived[0].value["archived_from"] == "author-b"


async def test_search_finds_entries_by_substring() -> None:
    """search() matches keys and JSON value contents."""
    memory = MemoryManager()
    token = uuid.uuid4().hex[:8]
    await memory.share(_key("search"), {"topic": f"zzsearchable{token}"}, author="a")
    await memory.remember_individual("mem-agent-2", _key("search"), {"x": 1})

    hits = await memory.search(f"zzsearchable{token}", scope=Memory.SCOPE_SHARED)
    assert len(hits) == 1
    assert hits[0].value["topic"] == f"zzsearchable{token}"

    assert await memory.search("") == []  # empty query -> no hits


async def test_prune_caps_history_versions(monkeypatch) -> None:
    """prune() keeps only the newest N history rows per logical key."""
    monkeypatch.setattr(get_settings(), "memory_max_versions", 2)
    memory = MemoryManager()
    prefix = f"prunable{uuid.uuid4().hex[:8]}"
    for i in range(4):
        await memory.history_append(prefix, {"seq": i}, actor="tester")

    report = await memory.prune()
    assert report["history_capped"] >= 2
    assert report["history_expired"] == 0  # nothing is older than the retention window

    remaining = [
        entry for entry in await memory.list_scope(Memory.SCOPE_HISTORY, limit=500)
        if entry.key.startswith(prefix)
    ]
    assert len(remaining) == 2, "exactly max_versions rows survive per logical key"


async def test_history_append_records_actor_and_timestamp() -> None:
    """History writes are append-only with actor and timestamp metadata."""
    memory = MemoryManager()
    prefix = _key("hist")
    await memory.history_append(prefix, {"outcome": "ok"}, actor="hist-agent")
    rows = [
        entry for entry in await memory.list_scope(Memory.SCOPE_HISTORY, limit=500)
        if entry.key.startswith(prefix)
    ]
    assert len(rows) == 1
    assert rows[0].value["actor"] == "hist-agent"
    assert rows[0].value["outcome"] == "ok"
    assert rows[0].value["recorded_at"]


@pytest.mark.parametrize(
    "scope", [Memory.SCOPE_INDIVIDUAL, Memory.SCOPE_SHARED, Memory.SCOPE_HISTORY]
)
async def test_list_scope_filters_correctly(scope: str) -> None:
    """list_scope only returns rows of the requested scope."""
    memory = MemoryManager()
    rows = await memory.list_scope(scope, limit=10)
    assert all(entry.scope == scope for entry in rows)
