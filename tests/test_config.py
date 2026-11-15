"""Tests for YAML configuration loading (system, master, agents)."""

from __future__ import annotations

import pytest

from agent_hive.config.loader import (
    ProviderConfig,
    list_agent_names,
    load_agent_config,
    load_master_config,
    load_system_config,
)
from agent_hive.core.errors import ConfigError
from agent_hive.providers.factory import resolve_provider


def test_system_config_loads() -> None:
    """system.yaml produces a populated SystemConfig."""
    config = load_system_config()
    assert 0.0 < config.simple_threshold < config.adaptive_threshold
    assert 0.0 < config.qa_required_score <= 1.0
    assert config.qa_code_check is True
    assert config.qa_secret_scan is True
    assert config.adaptive_min_agents >= 2


def test_master_config_loads() -> None:
    """master.yaml is a mapping describing the Master Agent."""
    master = load_master_config()
    assert master["name"] == "master"
    assert isinstance(master.get("responsibilities"), list)


def test_all_agent_configs_load() -> None:
    """Every configured agent loads with a unique name, role and providers."""
    names = list_agent_names()
    assert len(names) == 20
    seen: set[str] = set()
    for name in names:
        config = load_agent_config(name)
        assert config.name == name, "file stem must match the declared name"
        assert config.name not in seen, f"duplicate agent name: {config.name}"
        seen.add(config.name)
        assert config.role, f"{name}: role must be set"
        assert config.providers, f"{name}: provider chain must not be empty"
        assert config.description, f"{name}: description must be set"


def test_unknown_agent_raises_config_error() -> None:
    """A missing agent YAML fails fast with ConfigError."""
    with pytest.raises(ConfigError, match="Missing configuration"):
        load_agent_config("no_such_agent")


def test_unknown_provider_type_raises_config_error() -> None:
    """An unregistered provider type is rejected by the factory."""
    with pytest.raises(ConfigError, match="Unknown provider type"):
        resolve_provider(ProviderConfig(type="quantum_entangled_llm"))


def test_provider_chain_default_is_mock() -> None:
    """An agent YAML without providers falls back to a mock provider."""
    config = load_agent_config("analyst")
    assert config.has_real_provider is True
    assert any(p.type == "mock" for p in config.providers)
