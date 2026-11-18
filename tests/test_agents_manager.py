"""Tests for the AgentManager: registry view, disable/enable round-trip,
runtime registration of agent #21+, health probe and workload stats."""

from __future__ import annotations

import pytest

from agent_hive.agents.manager import AgentManager
from agent_hive.core.errors import ConfigError
from agent_hive.db.models import Agent
from agent_hive.tasks.manager import TaskManager


async def test_registry_lists_all_agents_with_runtime_flag(hive) -> None:
    registry = await hive.agents_manager.registry()
    names = {row["name"] for row in registry}
    assert {"programmer", "reviewer", "tester"} <= names
    assert len(registry) >= 20
    for row in registry:
        assert row["role"]
        assert isinstance(row["capabilities"], list)


async def test_disable_and_enable_round_trip(hive) -> None:
    manager: AgentManager = hive.agents_manager
    disabled = await manager.disable("optimizer")
    assert disabled["in_runtime"] is False
    assert "optimizer" not in hive.runtime.agents
    # registry reflects the disabled state
    registry = {row["name"]: row for row in await manager.registry()}
    assert registry["optimizer"]["status"] == "disabled"
    assert registry["optimizer"]["in_runtime"] is False

    enabled = await manager.enable("optimizer")
    assert enabled["in_runtime"] is True
    assert "optimizer" in hive.runtime.agents
    # executing a task still works after re-enable
    result = await hive.runtime.run_direct("optimizer", "ping")
    assert result["text"]


async def test_disable_unknown_agent_fails(hive) -> None:
    with pytest.raises(ConfigError, match="not loaded"):
        await hive.agents_manager.disable("ghost")


async def test_enable_unknown_agent_fails(hive) -> None:
    with pytest.raises(ConfigError, match="Missing configuration"):
        await hive.agents_manager.enable("ghost")


async def test_register_adds_agent_21_at_runtime(hive) -> None:
    """A new agent is registered, persisted to YAML and immediately usable."""
    import os

    from agent_hive.config.settings import get_settings

    manager: AgentManager = hive.agents_manager
    yaml_path = os.path.join(
        str(get_settings().config_dir), "agents", "botanist.yaml"
    )
    spec = {
        "name": "botanist",
        "title": "Botany Agent",
        "role": "researcher",
        "description": "Domain expert for plant-related questions (test agent).",
        "capabilities": ["botany", "analysis"],
        "tools": ["summarize", "word_count"],
        "providers": [{"type": "mock"}],
        "memory": {"individual": True, "shared_access": True, "shared_write": False},
    }
    try:
        result = await manager.register(spec)
        assert result["loaded"] is True
        assert result["roster_size"] == 21
        assert "botanist" in hive.runtime.agents

        # usable right away
        out = await hive.runtime.run_direct("botanist", "Identify this plant")
        assert out["text"]

        # config file persisted and reloadable via enable()
        assert os.path.isfile(yaml_path)
        await manager.disable("botanist")
        await manager.enable("botanist")
        assert "botanist" in hive.runtime.agents
    finally:
        # Never leak the test YAML into the repository config directory.
        if "botanist" in hive.runtime.agents:
            hive.runtime.agents.pop("botanist")
        if os.path.isfile(yaml_path):
            os.unlink(yaml_path)


async def test_register_rejects_bad_specs(hive) -> None:
    manager: AgentManager = hive.agents_manager
    with pytest.raises(ConfigError, match="role"):
        await manager.register({
            "name": "bad_role", "title": "Bad", "role": "wizard",
            "providers": [{"type": "mock"}],
        })
    with pytest.raises(ConfigError, match="providers"):
        await manager.register({
            "name": "no_prov", "title": "No provider", "role": "tester",
            "providers": [],
        })
    with pytest.raises(ConfigError, match="name"):
        await manager.register({
            "name": "BAD NAME!", "title": "X", "role": "tester",
            "providers": [{"type": "mock"}],
        })


async def test_health_probes_provider_chain(hive) -> None:
    health = await hive.agents_manager.health("programmer")
    assert health["agent"] == "programmer"
    assert len(health["providers"]) >= 1
    assert health["usable"] is True  # mock is always available
    with pytest.raises(ConfigError, match="not loaded"):
        await hive.agents_manager.health("ghost")


async def test_stats_counts_tasks_per_agent(hive) -> None:
    """Workload counters grow by exactly the tasks this test adds (the
    test database is shared across the suite, so use deltas)."""
    tasks = TaskManager(hive.events)
    before = (await hive.agents_manager.stats())["agents"]
    base_prog = before["programmer"]["total_tasks"]
    base_test = before["tester"]["total_tasks"]

    await tasks.create("Work for programmer", agent_name="programmer")
    await tasks.create("More work", agent_name="programmer")
    await tasks.create("Work for tester", agent_name="tester")

    stats = (await hive.agents_manager.stats())["agents"]
    assert stats["programmer"]["total_tasks"] == base_prog + 2
    assert stats["tester"]["total_tasks"] == base_test + 1

    single = (await hive.agents_manager.stats("tester"))["agents"]
    assert single["tester"]["total_tasks"] == base_test + 1
    assert "programmer" not in single


async def test_registry_survives_as_db_rows(hive) -> None:
    """The registry is DB-backed (Agent rows), not just in-memory."""
    from sqlalchemy import func, select

    from agent_hive.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as sess:
        count = (await sess.execute(
            select(func.count()).select_from(Agent)
        )).scalar_one()
    assert count >= 20
