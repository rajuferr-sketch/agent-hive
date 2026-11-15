"""Tests for LLM providers: mock, OpenAI-compat config detection,
fallback chains and the circuit breaker."""

from __future__ import annotations

import pytest

from agent_hive.core.errors import ProviderError
from agent_hive.config.settings import get_settings
from agent_hive.providers.base import LLMProvider
from agent_hive.providers.factory import ProviderChain
from agent_hive.providers.mock import MOCK_TAG, MockProvider
from agent_hive.providers.openai_compat import OpenAICompatProvider

MESSAGES = [
    {"role": "system", "content": "You are a test agent."},
    {"role": "user", "content": "Say hello."},
]


class _FailingProvider(LLMProvider):
    """Provider that always raises (simulates a dead backend)."""

    name = "failing"

    def __init__(self, label: str = "failing") -> None:
        self.label = label

    async def complete(self, messages, **params):
        raise RuntimeError(f"{self.label} is down")


class _CountingProvider(LLMProvider):
    """Provider that counts calls and always fails."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, **params):
        self.calls += 1
        raise RuntimeError("counting provider failure")


async def test_mock_provider_tags_output() -> None:
    """The mock provider is deterministic and clearly tagged."""
    provider = MockProvider()
    result = await provider.complete(MESSAGES)
    assert MOCK_TAG in result.text
    assert result.mock is True
    assert result.provider == "mock"
    again = await provider.complete(MESSAGES)
    assert again.text == result.text  # deterministic


async def test_openai_compat_not_configured_without_key(monkeypatch) -> None:
    """Default OpenAI endpoint without an API key is known-unusable."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAICompatProvider(model="gpt-4o-mini")
    try:
        assert provider.configured() is False
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123456")
        assert provider.configured() is True
    finally:
        await provider.aclose()


async def test_openai_compat_configured_with_custom_base_url(monkeypatch) -> None:
    """A non-OpenAI base URL (e.g. a local gateway) needs no API key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAICompatProvider(
        model="local", base_url="http://127.0.0.1:9999/v1"
    )
    try:
        assert provider.configured() is True
    finally:
        await provider.aclose()


async def test_provider_chain_falls_back_to_next_provider() -> None:
    """First provider failing means the second one answers."""
    chain = ProviderChain([_FailingProvider("dead"), MockProvider()])
    result = await chain.complete(MESSAGES)
    assert result.mock is True
    assert MOCK_TAG in result.text
    assert result.provider == "mock"  # from the real fallback, not chain mock


async def test_provider_chain_raises_when_all_fail_and_mock_disallowed(
    monkeypatch,
) -> None:
    """With ALLOW_MOCK=false, exhausting the chain raises ProviderError."""
    monkeypatch.setattr(get_settings(), "allow_mock", False)
    chain = ProviderChain([_FailingProvider("a"), _FailingProvider("b")])
    with pytest.raises(ProviderError, match="All providers failed"):
        await chain.complete(MESSAGES)


async def test_provider_chain_mock_fallback_when_allowed(monkeypatch) -> None:
    """With ALLOW_MOCK=true the chain falls back to a tagged mock result."""
    monkeypatch.setattr(get_settings(), "allow_mock", True)
    chain = ProviderChain([_FailingProvider("only")])
    result = await chain.complete(MESSAGES)
    assert result.provider == "mock(fallback)"
    assert MOCK_TAG in result.text


async def test_circuit_breaker_skips_trip_provider() -> None:
    """After 2 consecutive failures the provider is skipped (not called)."""
    counting = _CountingProvider()
    chain = ProviderChain([counting, MockProvider()])

    await chain.complete(MESSAGES)  # attempt 1 fails, fallback works
    assert counting.calls == 1
    await chain.complete(MESSAGES)  # attempt 2 fails -> circuit trips
    assert counting.calls == 2

    result = await chain.complete(MESSAGES)  # circuit open -> provider skipped
    assert counting.calls == 2
    assert result.mock is True

    # A success resets the failure counter for that provider.
    chain._record_success(counting)
    assert chain._tripped(counting) is False
