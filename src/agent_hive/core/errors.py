"""Exception hierarchy for AgentHive.

Every subsystem raises a subclass of :class:`AgentError` so callers can
distinguish error domains without importing implementation details.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all AgentHive errors."""


class ConfigError(AgentError):
    """Invalid or missing configuration."""


class ProviderError(AgentError):
    """An LLM provider call failed (all fallbacks exhausted)."""


class TaskError(AgentError):
    """A task failed during execution."""


class TaskTimeout(AgentError):
    """A task exceeded its time budget."""


class DependencyError(AgentError):
    """Task dependency cycle or unresolvable dependency."""


class PermissionDenied(AgentError):
    """An agent attempted an operation outside its permissions."""


class QualityGateError(AgentError):
    """The quality-control pipeline rejected a result."""


class CommunicationError(AgentError):
    """Message routing/broadcast failure."""
