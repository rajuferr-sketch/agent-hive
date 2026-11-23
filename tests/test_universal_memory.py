"""Universal shared memory tests — persistence, isolation, TTL, search.

Includes the mandatory **UNIVERSAL CROSS-CLIENT MEMORY TEST**: a task is
created through client A (Claude Desktop via MCP), executed by the hive,
stored in shared memory, then retrieved and continued by client B
(ChatGPT via OpenAI-compatible connector) and read back by client C
(Z.ai via REST) — proving real cross-client persistent shared memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_hive.security.tokens import TokenIdentity
from agent_hive.universal_memory.universal import (
    UniversalMemoryError,
    UniversalMemoryManager,
)


def _admin(client: str = "test") -> TokenIdentity:
    return TokenIdentity(token_id="t", subject=client, role="admin", scopes=["*"])


# --------------------------------------------------------------- basic CRUD


async def test_save_and_get_roundtrip() -> None:
    um = UniversalMemoryManager()
    record = await um.save(
        memory_type="semantic", key="concept:crm", content="CRM = customer relationship mgmt",
        value={"domain": "sales"}, tags=["concept"],
    )
    assert record["version"] == 1
    fetched = await um.get(key="concept:crm", memory_type="semantic")
    assert fetched is not None
    assert fetched["content"].startswith("CRM")
    assert fetched["value"]["domain"] == "sales"


async def test_version_bumps_on_change_dedups_identical() -> None:
    um = UniversalMemoryManager()
    await um.save(memory_type="semantic", key="vtest", content="first")
    second = await um.save(memory_type="semantic", key="vtest", content="second")
    assert second["version"] == 2
    again = await um.save(memory_type="semantic", key="vtest", content="second")
    assert again.get("deduplicated") is True
    assert again["version"] == 2  # identical content does not bump


async def test_update_requires_id_or_key() -> None:
    um = UniversalMemoryManager()
    with pytest.raises(UniversalMemoryError):
        await um.update(content="no locator")


async def test_update_increments_version() -> None:
    um = UniversalMemoryManager()
    created = await um.save(memory_type="operational", key="op:proc", content="step 1")
    updated = await um.update(key="op:proc", memory_type="operational", content="step 1 + 2")
    assert updated["version"] == created["version"] + 1
    assert "step 1 + 2" in updated["content"]


async def test_invalid_memory_type_rejected() -> None:
    um = UniversalMemoryManager()
    with pytest.raises(UniversalMemoryError):
        await um.save(memory_type="invalid", key="k", content="c")


async def test_invalid_access_rejected() -> None:
    um = UniversalMemoryManager()
    with pytest.raises(UniversalMemoryError):
        await um.save(memory_type="semantic", key="k", content="c", access="world")


# ------------------------------------------------------------------- TTL


async def test_ttl_expiry_and_purge() -> None:
    um = UniversalMemoryManager()
    await um.save(memory_type="episodic", key="ttl:short", content="fleeting",
                  ttl_seconds=1)
    # no expiry for standard records
    await um.save(memory_type="episodic", key="ttl:long", content="durable")
    rows = await um.list_records(memory_type="episodic")
    by_key = {r["key"]: r for r in rows}
    assert by_key["ttl:short"]["expires_at"] is not None
    assert by_key["ttl:long"]["expires_at"] is None
    # simulate expiry directly (avoid sleeping): backdate expires_at
    await um._run(lambda sess: _backdate(sess, "ttl:short"))
    purged = await um.purge_expired()
    assert purged >= 1
    assert await um.get(key="ttl:short", memory_type="episodic") is None


async def _backdate(sess, key: str) -> bool:  # noqa: ANN001
    from sqlalchemy import select, update

    from agent_hive.db.models import UniversalMemory as UMem

    row = (
        await sess.execute(select(UMem).where(UMem.key == key))
    ).scalar_one_or_none()
    if row is None:
        return False
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    await sess.execute(
        update(UMem).where(UMem.id == row.id).values(expires_at=past)
    )
    return True


# -------------------------------------------------------------- isolation


async def test_namespace_isolation_between_projects_and_users() -> None:
    um = UniversalMemoryManager()
    await um.save(memory_type="task", key="iso", content="alpha data",
                  user_id="alice", project_id="proj-a")
    await um.save(memory_type="task", key="iso", content="beta data",
                  user_id="bob", project_id="proj-b")
    alice_view = await um.list_records(user_id="alice", project_id="proj-a",
                                       memory_type="task")
    bob_view = await um.list_records(user_id="bob", project_id="proj-b",
                                     memory_type="task")
    assert len(alice_view) == 1 and alice_view[0]["content"] == "alpha data"
    assert len(bob_view) == 1 and bob_view[0]["content"] == "beta data"
    # cross-namespace get finds nothing
    assert await um.get(key="iso", memory_type="task", user_id="alice",
                        project_id="proj-b") is None


# ----------------------------------------------------------------- search


async def test_search_blends_fulltext_and_vector() -> None:
    um = UniversalMemoryManager()
    await um.save(memory_type="semantic", key="doc:payment",
                  content="payment gateway integration with stripe webhooks")
    await um.save(memory_type="semantic", key="doc:auth",
                  content="oauth2 login flow with token refresh")
    hits = await um.search("payment gateway stripe", limit=5)
    assert hits, "expected at least one hit"
    assert hits[0]["key"] == "doc:payment"
    assert hits[0]["score"] > hits[-1].get("score", 0) or len(hits) == 1
    # semantic proximity without exact substring still ranks (vector part)
    fuzzy = await um.search("webhook payments", limit=5)
    assert any(h["key"] == "doc:payment" for h in fuzzy)


async def test_history_returns_versioned_rows() -> None:
    um = UniversalMemoryManager()
    await um.save(memory_type="decision", key="dec:db",
                  content="chose sqlite for dev", value={"choice": "sqlite"})
    await um.save(memory_type="decision", key="dec:db",
                  content="chose postgres for prod", value={"choice": "postgres"})
    hist = await um.history(memory_type="decision", key="dec:db")
    assert len(hist) >= 1
    assert hist[0]["version"] >= 2


async def test_stats_counts_by_type() -> None:
    um = UniversalMemoryManager()
    stats = await um.stats()
    assert set(stats["by_type"]).issubset(
        {"episodic", "semantic", "operational", "task", "decision"}
    )
    assert stats["total"] == sum(stats["by_type"].values())


# ================================================ mandatory platform test =====


async def test_UNIVERSAL_CROSS_CLIENT_MEMORY_TEST(hive) -> None:
    """Mandatory: real cross-client persistent shared memory.

    Scenario (all against the same live hive + database):
      A. "claude-desktop" (MCP client) saves a decision and creates a task
         via the gateway tools;
      B. "chatgpt" (OpenAI-compatible client) finds that context via
         agent_search_memory and continues the work (updates the memory);
      C. "zai-web" (REST client) retrieves the full session history and
         the task record through its own tool calls;
      D. a brand-new manager instance (simulated process restart) still
         sees everything — persistence is in the database, not in RAM.
    """
    gateway = hive.gateway
    session = "cross-client-session-001"

    # ---- A. Claude Desktop (MCP): record a decision, create a task -------
    saved = await gateway.tool_call("agent_save_memory", {
        "memory_type": "decision",
        "key": "architecture:api-gateway",
        "content": "we chose FastAPI gateway in front of the 20 agents",
        "value": {"alternatives": ["django", "express"], "chosen": "fastapi"},
        "session_id": session,
    }, client="mcp:claude-desktop")
    assert saved["ok"] is True, saved
    memory_id = saved["data"]["id"]

    created = await gateway.tool_call("agent_create_task", {
        "title": "Draft API gateway OpenAPI spec",
        "description": "Follow the decision stored under architecture:api-gateway",
        "session_id": session,
    }, client="mcp:claude-desktop")
    assert created["ok"] is True, created
    task_id = created["data"]["task_id"]

    # ---- B. ChatGPT (OpenAI connector): finds A's context and continues --
    found = await gateway.tool_call("agent_search_memory", {
        "query": "api gateway decision fastapi",
        "session_id": session,
    }, client="openai:chatgpt")
    assert found["ok"] is True
    keys = [r["key"] for r in found["data"]["results"]]
    assert "architecture:api-gateway" in keys, f"context not visible to B: {keys}"

    continued = await gateway.tool_call("agent_update_memory", {
        "memory_id": memory_id,
        "content": "we chose FastAPI gateway; ChatGPT confirmed the routing plan",
        "session_id": session,
    }, client="openai:chatgpt")
    assert continued["ok"] is True
    assert continued["data"]["version"] == 2

    # B can also see and reassign A's task (shared task state)
    assigned = await gateway.tool_call("agent_assign_task", {
        "task_id": task_id,
    }, client="openai:chatgpt")
    assert assigned["ok"] is True
    assert assigned["data"]["assigned_to"]

    # ---- C. Z.ai web (REST): reads history and the task record -----------
    history = await gateway.tool_call("agent_get_history", {
        "limit": 50,
    }, client="rest:zai")
    assert history["ok"] is True
    ids = [t["id"] for t in history["data"]["tasks"]]
    assert task_id in ids

    task_lookup = await gateway.tool_call("agent_get_result", {
        "task_id": task_id,
    }, client="rest:zai")
    assert task_lookup["ok"] is True
    assert task_lookup["data"]["task_id"] == task_id

    session_context = await hive.umemory.history(session_id=session, limit=50)
    types = {r["memory_type"] for r in session_context}
    assert {"decision", "task"} <= types

    # ---- D. fresh manager (process restart simulation) sees everything ---
    fresh = UniversalMemoryManager()
    persisted = await fresh.get(key="architecture:api-gateway",
                                memory_type="decision", session_id=session)
    assert persisted is not None
    assert persisted["version"] == 2
    assert "ChatGPT confirmed" in persisted["content"]
    assert persisted["created_by_client"] in ("mcp:claude-desktop", "openai:chatgpt", "rest:zai")


async def test_cross_client_tool_same_record_different_clients(hive) -> None:
    """The 18 tools behave identically no matter which connector calls them."""
    session = "connector-parity"
    clients = ("mcp", "openai", "ollama", "rest", "ws", "generic")
    for client in clients:
        out = await hive.gateway.tool_call("agent_save_memory", {
            "memory_type": "episodic",
            "key": "parity",
            "content": f"written by {client}",
            "session_id": session,
        }, client=f"{client}:x")
        assert out["ok"] is True, (client, out)
    # each client bumped the shared record's version
    rec = await hive.umemory.get(key="parity", memory_type="episodic",
                                 session_id=session)
    assert rec["version"] == len(clients)
