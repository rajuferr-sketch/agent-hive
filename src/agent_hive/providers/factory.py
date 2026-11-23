"""Provider factory: per-agent fallback chains.

Rules
-----
1. Providers are tried in configuration order; the first success wins.
2. If every provider fails:
   - when ``ALLOW_MOCK=true`` the deterministic mock provider is used and
     the result is clearly tagged, so behaviour stays testable offline;
   - otherwise a :class:`ProviderError` is raised.
3. API keys are read from environment variables by *name* — no secret
   ever lives in YAML or in the repository.
"""

from __future__ import annotations

import os
import time
from typing import Any

from agent_hive.config.loader import ProviderConfig
from agent_hive.config.settings import get_settings
from agent_hive.core.errors import ConfigError, ProviderError
from agent_hive.core.logging import get_logger
from agent_hive.providers.anthropic import AnthropicProvider
from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.providers.gemini import GeminiProvider
from agent_hive.providers.host import HostProvider
from agent_hive.providers.mock import MockProvider
from agent_hive.providers.ollama import OllamaProvider
from agent_hive.providers.openai_compat import OpenAICompatProvider

log = get_logger("agent_hive.providers")

_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai_compatible": OpenAICompatProvider,
    "anthropic_native": AnthropicProvider,
    "gemini_native": GeminiProvider,
    "ollama": OllamaProvider,
    "host": HostProvider,
    "mock": MockProvider,
}

_instances: dict[str, LLMProvider] = {}


def resolve_provider(cfg: ProviderConfig) -> LLMProvider:
    """Instantiate (and cache) a single provider from its config.

    Instances are shared across agents with equivalent configuration so
    connection pools and circuit-breaker state are reused.
    """
    base_url = cfg.base_url or os.getenv(cfg.base_url_env or "", "") or "default"
    cache_key = f"{cfg.type}:{cfg.model}:{base_url}:{cfg.api_key_env}"
    if cache_key in _instances:
        return _instances[cache_key]
    if cfg.type not in _REGISTRY:
        raise ConfigError(
            f"Unknown provider type '{cfg.type}'. Registered: {sorted(_REGISTRY)}"
        )
    cls = _REGISTRY[cfg.type]
    if cls is MockProvider:
        provider: LLMProvider = MockProvider(model=cfg.model, params=cfg.params)
    elif hasattr(cls, "from_config"):
        provider = cls.from_config(cfg)  # type: ignore[attr-defined]
    else:
        provider = cls(model=cfg.model, params=cfg.params)  # type: ignore[call-arg]
    _instances[cache_key] = provider
    return provider


def build_provider_chain(configs: list[ProviderConfig]) -> ProviderChain:
    """Build an ordered fallback chain from agent YAML ``providers``."""
    if os.getenv("AGENT_HIVE_HOST_MODE", "").lower() in ("1", "true", "yes"):
        return ProviderChain([HostProvider()])
    chain = ProviderChain([resolve_provider(c) for c in configs])
    if not chain.providers:
        chain.providers.append(MockProvider())
    return chain


def register_provider_type(type_name: str, provider_cls: type[LLMProvider]) -> None:
    """Extension point: add custom provider types without touching core."""
    _REGISTRY[type_name] = provider_cls


class ProviderChain(LLMProvider):
    """Ordered list of providers with automatic fallback + circuit breaker.

    A provider that fails twice in a row is skipped for a cooldown window
    (default 60 s), so a down backend does not slow every agent call.
    """

    name = "provider_chain"
    COOLDOWN_S = 60.0
    TRIP_THRESHOLD = 2

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self._failures: dict[int, tuple[int, float]] = {}  # id → (count, ts)
        self._time = time.monotonic

    def _tripped(self, provider: LLMProvider) -> bool:
        entry = self._failures.get(id(provider))
        if not entry:
            return False
        count, ts = entry
        return count >= self.TRIP_THRESHOLD and (self._time() - ts) < self.COOLDOWN_S

    def _record_success(self, provider: LLMProvider) -> None:
        self._failures.pop(id(provider), None)

    def _record_failure(self, provider: LLMProvider) -> None:
        count = (self._failures.get(id(provider)) or (0, 0.0))[0] + 1
        self._failures[id(provider)] = (count, self._time())

    @property
    def descriptions(self) -> list[dict[str, Any]]:
        return [
            {"provider": p.name, "model": getattr(p, "model", "n/a")}
            for p in self.providers
        ]

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        last_error: Exception | None = None
        for provider in self.providers:
            if not provider.configured() or self._tripped(provider):
                log.debug("Provider '%s' skipped (not configured / circuit open)",
                          provider.name)
                continue
            try:
                result = await provider.complete(messages, **params)
                self._record_success(provider)
                return result
            except Exception as exc:  # noqa: BLE001 — try next fallback
                last_error = exc
                self._record_failure(provider)
                log.debug("Provider '%s' failed, trying next fallback: %s",
                          provider.name, exc)
        if get_settings().allow_mock:
            log.debug("All providers failed — falling back to MOCK provider")
            result = await MockProvider().complete(messages, **params)
            result.provider = "mock(fallback)"
            return result
        raise ProviderError(f"All providers failed: {last_error}")

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()


def has_api_key_for(cfg: ProviderConfig) -> bool:
    """Check (without leaking) that the referenced API key env var is set."""
    return bool(cfg.api_key_env and os.getenv(cfg.api_key_env))
