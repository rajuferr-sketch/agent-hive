"""Shared kernel: ids, logging, event bus, errors."""

from agent_hive.core.errors import (
    AgentError,
    ConfigError,
    DependencyError,
    PermissionDenied,
    ProviderError,
    QualityGateError,
    TaskError,
    TaskTimeout,
)
from agent_hive.core.events import Event, EventBus
from agent_hive.core.ids import new_id, now_iso
from agent_hive.core.logging import get_logger, setup_logging

__all__ = [
    "AgentError",
    "ConfigError",
    "DependencyError",
    "PermissionDenied",
    "ProviderError",
    "QualityGateError",
    "TaskError",
    "TaskTimeout",
    "Event",
    "EventBus",
    "new_id",
    "now_iso",
    "get_logger",
    "setup_logging",
]
