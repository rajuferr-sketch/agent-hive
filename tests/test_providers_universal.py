"""Universal provider adapter tests — Anthropic/Gemini natives + presets."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_hive.core.errors import ProviderError
from agent_hive.providers.anthropic import AnthropicProvider
from agent_hive.providers.base import CompletionResult
from agent_hive.providers.factory import resolve_provider
from agent_hive.providers.gemini import GeminiProvider
from agent_hive.providers.presets import PRESETS, preset_for_config

# ---------------------------------------------------------------- presets


def test_presets_cover_required_clients() -> None:
    required_cloud = {"openai", "anthropic", "gemini", "zai", "deepseek",
                      "qwen", "mistral", "grok", "perplexity"}
    required_local = {"ollama", "lm_studio", "llama_cpp", "vllm",
                      "localai", "huggingface"}
    assert required_cloud <= set(PRESETS)
    assert required_local <= set(PRESETS)
    for name, preset in PRESETS.items():
        assert preset["type"], name
        assert preset["model_hint"], name
        # no literal secrets anywhere in the preset map
        assert "sk-" not in str(preset)
        assert preset.get("api_key_env") in (None, "") or "KEY" in preset["api_key_env"].upper() \
            or "TOKEN" in preset["api_key_env"].upper() or "HF_TOKEN" == preset["api_key_env"]


def test_preset_for_config_maps_stanza() -> None:
    stanza = preset_for_config("deepseek")
    assert stanza["type"] == "openai_compatible"
    assert stanza["base_url"] == "https://api.deepseek.com/v1"
    assert stanza["api_key_env"] == "DEEPSEEK_API_KEY"
    with pytest.raises(KeyError):
        preset_for_config("nonexistent")


def test_factory_knows_new_native_types() -> None:
    from agent_hive.config.loader import ProviderConfig

    cfg = ProviderConfig(type="anthropic_native", model="claude-sonnet-4-5")
    provider = resolve_provider(cfg)
    assert provider.name == "anthropic_native"
    cfg2 = ProviderConfig(type="gemini_native", model="gemini-2.5-flash")
    assert resolve_provider(cfg2).name == "gemini_native"


# ------------------------------------------------------- anthropic adapter


def test_anthropic_request_shape() -> None:
    """System message split out, x-api-key header, /v1/messages endpoint."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "ciao from claude"}],
            "usage": {"input_tokens": 3, "output_tokens": 4},
        })

    provider = AnthropicProvider(
        model="claude-sonnet-4-5", api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    import asyncio

    result = asyncio.run(provider.complete([
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]))
    assert result.text == "ciao from claude"
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"] == "be brief"
    assert captured["body"]["max_tokens"] >= 1
    assert all(m["role"] != "system" for m in captured["body"]["messages"])


def test_anthropic_error_mapped_to_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = AnthropicProvider(
        model="m", api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    import asyncio

    with pytest.raises(ProviderError):
        asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))


# ---------------------------------------------------------- gemini adapter


def test_gemini_request_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "ciao from gemini"}]}}],
            "usageMetadata": {"totalTokenCount": 7},
        })

    provider = GeminiProvider(
        model="gemini-2.5-flash", api_key="g-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    import asyncio

    result = asyncio.run(provider.complete([
        {"role": "system", "content": "be nice"},
        {"role": "assistant", "content": "sure"},
        {"role": "user", "content": "hi"},
    ]))
    assert result.text == "ciao from gemini"
    assert "/v1beta/models/gemini-2.5-flash:generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "g-key"
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "be nice"
    roles = {c["role"] for c in captured["body"]["contents"]}
    assert "model" in roles and "assistant" not in roles


def test_gemini_malformed_payload_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    provider = GeminiProvider(
        model="m", api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    import asyncio

    with pytest.raises(ProviderError, match="Malformed"):
        asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))


def test_completion_result_defaults() -> None:
    result = CompletionResult(text="t", provider="p", model="m")
    assert result.mock is False and result.usage == {}
