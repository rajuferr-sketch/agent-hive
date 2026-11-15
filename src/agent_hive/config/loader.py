"""YAML configuration loader for the system and for every agent.

Configuration layout::

    configs/
      system.yaml        global orchestration & quality settings
      master.yaml        Master Agent configuration
      agents/            one file per specialized agent (20 files)

Agent YAML schema (validated here — unknown agents fail fast)::

    name: analyst            # unique, machine id
    title: "Analysis Agent"  # human-readable
    role: analyst            # must match a class in agents/roles/
    description: "..."
    capabilities: [analysis, decomposition]
    tools: [summarize, json_validate]      # subset of tools registry
    memory:
      individual: true
      shared_access: true      # may read shared memory
      shared_write: false      # may write shared memory
    providers:                 # ordered fallback chain
      - type: openai_compatible
        model: gpt-4o-mini
        base_url_env: OPENAI_BASE_URL      # optional env var holding base url
        api_key_env: OPENAI_API_KEY        # env var name, never the secret
        params: {temperature: 0.3}
      - type: mock
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import ConfigError
from agent_hive.core.logging import get_logger

log = get_logger("agent_hive.config")


@dataclass(slots=True)
class MemoryConfig:
    individual: bool = True
    shared_access: bool = False
    shared_write: bool = False


@dataclass(slots=True)
class ProviderConfig:
    type: str
    model: str = "default"
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentConfig:
    name: str
    title: str
    role: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    providers: list[ProviderConfig] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def has_real_provider(self) -> bool:
        return any(p.type != "mock" for p in self.providers)


@dataclass(slots=True)
class SystemConfig:
    # Master orchestration thresholds (0.0 – 1.0 complexity scale)
    simple_threshold: float = 0.25
    adaptive_threshold: float = 0.55
    complex_threshold: float = 0.75
    # Quality control
    qa_required_score: float = 0.7
    qa_code_check: bool = True
    qa_secret_scan: bool = True
    qa_requirement_check: bool = True
    # Collaboration
    adaptive_min_agents: int = 3
    adaptive_max_agents: int = 10
    allow_cross_review: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Missing configuration file: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return data


def load_system_config() -> SystemConfig:
    settings = get_settings()
    raw = _load_yaml(Path(settings.config_dir) / "system.yaml")
    known = {f for f in SystemConfig.__dataclass_fields__ if f != "raw"}
    filtered = {k: v for k, v in raw.items() if k in known}
    return SystemConfig(raw=raw, **filtered)


def load_agent_config(name: str) -> AgentConfig:
    settings = get_settings()
    path = Path(settings.config_dir) / "agents" / f"{name}.yaml"
    raw = _load_yaml(path)
    mem = raw.get("memory", {}) or {}
    providers = [
        ProviderConfig(
            type=p.get("type", "mock"),
            model=str(p.get("model", "default")),
            base_url=p.get("base_url"),
            base_url_env=p.get("base_url_env"),
            api_key_env=p.get("api_key_env"),
            params=p.get("params") or {},
        )
        for p in raw.get("providers", [])
    ]
    return AgentConfig(
        name=str(raw["name"]),
        title=str(raw.get("title", raw["name"])),
        role=str(raw.get("role", raw["name"])),
        description=str(raw.get("description", "")),
        capabilities=list(raw.get("capabilities", [])),
        tools=list(raw.get("tools", [])),
        memory=MemoryConfig(
            individual=bool(mem.get("individual", True)),
            shared_access=bool(mem.get("shared_access", False)),
            shared_write=bool(mem.get("shared_write", False)),
        ),
        providers=providers or [ProviderConfig(type="mock")],
        params=raw.get("params") or {},
    )


def list_agent_names() -> list[str]:
    """Return all configured agent names (from configs/agents/*.yaml)."""
    settings = get_settings()
    agents_dir = Path(settings.config_dir) / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.yaml"))


def load_master_config() -> dict[str, Any]:
    settings = get_settings()
    return _load_yaml(Path(settings.config_dir) / "master.yaml")
