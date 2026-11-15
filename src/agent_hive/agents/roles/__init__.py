"""Role agents: one module per specialized agent (20 in the default build).

Role classes are discovered dynamically — every module in this package
that defines a ``BaseAgent`` subclass with a distinct ``ROLE`` attribute
is registered automatically. Adding the 21st agent therefore requires
only: a new module here + a new YAML file in ``configs/agents/``.
"""

from __future__ import annotations

import importlib
import pkgutil

from agent_hive.agents.base import BaseAgent
from agent_hive.core.logging import get_logger

log = get_logger("agent_hive.roles")

ROLE_REGISTRY: dict[str, type[BaseAgent]] = {}


def _discover() -> None:
    for module_info in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseAgent)
                and obj is not BaseAgent
                and obj.__module__.startswith(f"{__name__}.")
            ):
                role = getattr(obj, "ROLE", None)
                if role and role != "generic" and role not in ROLE_REGISTRY:
                    ROLE_REGISTRY[role] = obj


_discover()
log.info("Role registry: %d roles — %s", len(ROLE_REGISTRY), sorted(ROLE_REGISTRY))

__all__ = ["ROLE_REGISTRY", "BaseAgent"]
