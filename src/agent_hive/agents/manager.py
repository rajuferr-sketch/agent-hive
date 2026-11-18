"""Agent Manager — dynamic roster administration over AgentRuntime.

The runtime already owns the *instances*; this module adds the operator
surface on top of it:

* DB-backed registry view (``agents`` table) with enable/disable;
* hot registration of new agents (agent #21+) from a YAML spec, without
  restarting the hive;
* per-agent health probe of the whole provider chain;
* per-agent workload statistics from the ``tasks`` table;
* mailbox inspection for debugging collaboration.
"""

from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy import func, select

from agent_hive.core.errors import ConfigError
from agent_hive.core.events import EventBus
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Agent, Task


class AgentManager:
    """Administration service over the agent registry and runtime."""

    def __init__(self, event_bus: EventBus, runtime: Any, config_dir: str = "./configs") -> None:
        self.events = event_bus
        self.runtime = runtime
        self.config_dir = config_dir

    # ------------------------------------------------------------------ read
    async def registry(self) -> list[dict[str, Any]]:
        """DB-backed registry rows (survives restarts, includes heartbeats)."""
        factory = get_session_factory()
        async with factory() as sess:
            rows = (await sess.execute(
                select(Agent).order_by(Agent.name)
            )).scalars().all()
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "title": a.title,
                    "role": a.role,
                    "description": a.description,
                    "status": a.status,
                    "capabilities": a.capabilities,
                    "provider_chain": a.provider_chain,
                    "memory_enabled": a.memory_enabled,
                    "created_at": str(a.created_at),
                    "last_heartbeat": str(a.last_heartbeat),
                    "in_runtime": a.name in self.runtime.agents,
                }
                for a in rows
            ]

    def describe(self) -> list[dict[str, Any]]:
        """In-memory runtime view (same data as GET /api/agents)."""
        return self.runtime.describe()

    # ------------------------------------------------------- enable / disable
    async def disable(self, name: str) -> dict[str, Any]:
        """Unload an agent from the runtime (its YAML stays on disk)."""
        if name not in self.runtime.agents:
            raise ConfigError(f"Agent '{name}' is not loaded")
        self.runtime.agents.pop(name)
        self.runtime.bus.unregister_mailbox(name)
        await self._set_registry_status(name, "disabled")
        await self.events.publish("agent.disabled", "agent_manager", agent=name)
        return {"name": name, "status": "disabled", "in_runtime": False}

    async def enable(self, name: str) -> dict[str, Any]:
        """(Re)load an agent from its YAML config into the runtime."""
        from agent_hive.agents.roles import ROLE_REGISTRY
        from agent_hive.config.loader import load_agent_config
        from agent_hive.providers.factory import build_provider_chain

        config = load_agent_config(name)
        role_cls = ROLE_REGISTRY.get(config.role)
        if role_cls is None:
            raise ConfigError(
                f"Agent '{name}' declares role '{config.role}' but no role "
                f"class is registered. Available: {sorted(ROLE_REGISTRY)}"
            )
        provider = build_provider_chain(config.providers)
        agent = role_cls(config, self.runtime.memory, self.runtime.bus,
                         self.runtime.events, provider)
        self.runtime.agents[agent.name] = agent
        self.runtime.bus.register_mailbox(agent.name)
        await self._set_registry_status(name, "idle")
        await self.events.publish("agent.enabled", "agent_manager", agent=name)
        return {"name": name, "status": "idle", "in_runtime": True}

    async def _set_registry_status(self, name: str, status: str) -> None:
        factory = get_session_factory()
        async with factory() as sess:
            row = (await sess.execute(
                select(Agent).where(Agent.name == name)
            )).scalar_one_or_none()
            if row is not None:
                row.status = status
                await sess.commit()

    # ------------------------------------------------------------ registration
    async def register(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Register a brand-new agent (agent #21+) at runtime.

        ``spec`` is the agent YAML schema (name, title, role, capabilities,
        tools, providers, memory). It is persisted to
        ``configs/agents/<name>.yaml`` and immediately loaded into the
        runtime — no restart required.
        """
        from agent_hive.agents.roles import ROLE_REGISTRY
        from agent_hive.config.loader import load_agent_config
        from agent_hive.providers.factory import build_provider_chain

        name = str(spec.get("name", "")).strip()
        if not name or not name.replace("_", "").isalnum():
            raise ConfigError("spec.name must be a non-empty alphanumeric identifier")
        if spec.get("role") not in ROLE_REGISTRY:
            raise ConfigError(
                f"Unknown role '{spec.get('role')}'. Available: {sorted(ROLE_REGISTRY)}"
            )
        if not spec.get("providers"):
            raise ConfigError("spec.providers must list at least one provider")

        yaml_path = f"{self.config_dir}/agents/{name}.yaml"
        with open(yaml_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(spec, fh, sort_keys=False, allow_unicode=True)

        config = load_agent_config(name)
        role_cls = ROLE_REGISTRY[config.role]
        provider = build_provider_chain(config.providers)
        agent = role_cls(config, self.runtime.memory, self.runtime.bus,
                         self.runtime.events, provider)
        self.runtime.agents[agent.name] = agent
        self.runtime.bus.register_mailbox(agent.name)
        await self.runtime.sync_registry()
        await self.events.publish(
            "agent.registered", "agent_manager",
            agent=name, role=config.role, file=yaml_path,
        )
        return {
            "name": name,
            "role": config.role,
            "config_file": yaml_path,
            "loaded": True,
            "roster_size": len(self.runtime.agents),
        }

    # ----------------------------------------------------------------- health
    async def health(self, name: str) -> dict[str, Any]:
        """Probe every provider in the agent's chain (ordered fallback)."""
        agent = self.runtime.agents.get(name)
        if agent is None:
            raise ConfigError(f"Agent '{name}' is not loaded")
        checks: list[dict[str, Any]] = []
        for provider in agent.provider.providers:
            try:
                healthy = await provider.health_check()
                detail = "reachable" if healthy else "unreachable"
            except Exception as exc:  # noqa: BLE001 — probes must not raise
                healthy, detail = False, str(exc)[:120]
            checks.append({
                "provider": provider.name,
                "model": getattr(provider, "model", "n/a"),
                "healthy": healthy,
                "detail": detail,
            })
        return {
            "agent": name,
            "providers": checks,
            "usable": any(c["healthy"] for c in checks),
        }

    # ------------------------------------------------------------------ stats
    async def stats(self, name: str | None = None) -> dict[str, Any]:
        """Workload counters per agent (from the ``tasks`` table)."""
        factory = get_session_factory()
        async with factory() as sess:
            stmt = (
                select(Task.agent_name, Task.status, func.count())
                .group_by(Task.agent_name, Task.status)
            )
            if name:
                stmt = stmt.where(Task.agent_name == name)
            rows = await sess.execute(stmt)
            per_agent: dict[str, dict[str, int]] = {}
            for agent_name, status, count in rows:
                if agent_name is None:
                    continue
                per_agent.setdefault(agent_name, {})[status] = count
        roster = {
            a_name: {
                "busy": a.busy,
                "in_runtime": True,
                "tasks": per_agent.get(a_name, {}),
                "total_tasks": sum(per_agent.get(a_name, {}).values()),
            }
            for a_name, a in self.runtime.agents.items()
            if name is None or a_name == name
        }
        return {"agents": roster, "registry_rows": len(per_agent)}


__all__ = ["AgentManager"]
