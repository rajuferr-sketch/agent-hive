"""Tests for the agent runtime and BaseAgent behaviour."""

from __future__ import annotations

import uuid

import pytest

from agent_hive.agents.base import BaseAgent
from agent_hive.agents.roles import ROLE_REGISTRY
from agent_hive.agents.roles.analyst import AnalystAgent
from agent_hive.agents.runtime import AgentRuntime
from agent_hive.communication.bus import MessageBus
from agent_hive.config.loader import AgentConfig, MemoryConfig, ProviderConfig
from agent_hive.core.errors import ConfigError, PermissionDenied
from agent_hive.core.events import EventBus
from agent_hive.db.models import Task
from agent_hive.memory.manager import MemoryManager
from agent_hive.providers.factory import ProviderChain
from agent_hive.providers.mock import MOCK_TAG, MockProvider


def _mock_chain() -> ProviderChain:
    """BaseAgent expects the ProviderChain interface (``.descriptions``)."""
    return ProviderChain([MockProvider()])


def _make_runtime() -> AgentRuntime:
    return AgentRuntime(EventBus(), MemoryManager(), MessageBus())


def _unique(name: str) -> str:
    return f"{name}-{uuid.uuid4().hex[:8]}"


async def test_runtime_loads_all_20_agents() -> None:
    """Loading without explicit names instantiates every configured agent."""
    runtime = _make_runtime()
    loaded = runtime.load()
    assert len(loaded) == 20
    assert len(set(loaded)) == 20
    assert set(loaded) == set(runtime.agents)


async def test_unknown_role_raises_config_error(monkeypatch) -> None:
    """An agent YAML with an unregistered role fails fast."""
    import agent_hive.agents.runtime as runtime_module
    import agent_hive.config.loader as loader

    original = loader.load_agent_config

    def fake_load(name: str):
        config = original(name)
        config.role = "no_such_role"
        return config

    monkeypatch.setattr(runtime_module, "load_agent_config", fake_load)
    runtime = _make_runtime()
    with pytest.raises(ConfigError, match="no role class is registered"):
        runtime.load(["analyst"])


async def test_best_agent_for_matches_capability() -> None:
    """Capability hints select the most competent agent."""
    runtime = _make_runtime()
    runtime.load()
    pick = runtime.best_agent_for(capabilities_hint=["programming"])
    assert pick == "programmer"
    assert "programmer" in runtime.agents_with_capability("programming")


async def test_best_agent_for_is_none_safe() -> None:
    """An empty registry yields None instead of raising."""
    runtime = _make_runtime()
    assert runtime.best_agent_for(capabilities_hint=["anything"]) is None


def _analyst_config(shared_write: bool = False) -> AgentConfig:
    return AgentConfig(
        name="analyst",
        title="Analysis Agent",
        role="analyst",
        description="Test analyst with a deterministic mock provider.",
        capabilities=["analysis", "decomposition"],
        tools=["summarize"],
        memory=MemoryConfig(individual=True, shared_access=True, shared_write=shared_write),
        providers=[ProviderConfig(type="mock")],
    )


async def test_run_direct_task_writes_individual_memory() -> None:
    """A direct task returns the full result dict and persists memory."""
    memory = MemoryManager()
    agent = AnalystAgent(
        _analyst_config(), memory, MessageBus(), EventBus(), _mock_chain()
    )
    task = Task(
        id="direct-" + _unique("analyst"),
        title="Analyze requirements for a caching layer",
        description="Break the request into testable requirements.",
        payload={"requirements": ["caching"]},
    )
    result = await agent.run_task(task)

    assert result["agent"] == "analyst"
    assert result["role"] == "analyst"
    assert MOCK_TAG in result["text"]
    assert isinstance(result["self_check"], dict)
    assert {"passed", "notes"} <= set(result["self_check"])
    assert result["mock"] is True

    entry = await memory.recall_individual("analyst", f"task:{task.id}")
    assert entry is not None, "task result must be stored in individual memory"
    assert entry.key.startswith("task:")
    assert entry.value["title"] == task.title
    assert "passed" in entry.value["self_check"]

    assert agent.busy is False, "busy flag is reset after the task"


async def test_shared_write_denied_by_config() -> None:
    """An agent without shared_write permission cannot create shared entries."""
    memory = MemoryManager()
    agent = AnalystAgent(
        _analyst_config(shared_write=False), memory, MessageBus(), EventBus(),
        _mock_chain(),
    )
    key = _unique("forbidden-share")
    await agent.share_knowledge(key, {"secret": "should not be stored"})
    assert await memory.read_shared(key) is None


async def test_shared_write_allowed_by_config() -> None:
    """With shared_write=true the same call creates the shared entry."""
    memory = MemoryManager()
    agent = AnalystAgent(
        _analyst_config(shared_write=True), memory, MessageBus(), EventBus(),
        _mock_chain(),
    )
    key = _unique("allowed-share")
    await agent.share_knowledge(key, {"fact": "stored"})
    entry = await memory.read_shared(key)
    assert entry is not None and entry.value == {"fact": "stored"}


async def test_use_tool_unauthorized_raises() -> None:
    """Tools outside the agent's YAML list are refused."""
    agent = AnalystAgent(
        _analyst_config(), MemoryManager(), MessageBus(), EventBus(), _mock_chain()
    )
    with pytest.raises(PermissionDenied, match="not authorized"):
        await agent.use_tool("file_write", path="x.txt", content="y")

    # A granted tool works.
    report = await agent.use_tool("summarize", text="One sentence. Two sentences.")
    assert report["summary"]


async def test_role_registry_discovery() -> None:
    """Roles are discovered dynamically and include the core roles."""
    assert ROLE_REGISTRY.get("analyst") is AnalystAgent
    assert "programmer" in ROLE_REGISTRY
    assert issubclass(ROLE_REGISTRY["programmer"], BaseAgent)
    assert len(ROLE_REGISTRY) >= 20
