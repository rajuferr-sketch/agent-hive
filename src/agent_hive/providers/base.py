"""Provider abstraction shared by all LLM backends."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

Role = str  # "system" | "user" | "assistant"


@dataclass(slots=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    mock: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Interface every provider must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        **params: Any,
    ) -> CompletionResult:
        """Return a completion for the given chat messages."""

    async def health_check(self) -> bool:
        """Best-effort availability probe (used for diagnostics)."""
        return True

    def configured(self) -> bool:
        """False when the provider is known to be unusable (e.g. missing API key)."""
        return True

    async def aclose(self) -> None:  # noqa: B027 — optional lifecycle hook
        """Release resources (HTTP clients etc.)."""
