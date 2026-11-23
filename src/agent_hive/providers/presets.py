"""Provider presets — verified endpoint configuration for cloud & local runtimes.

A preset is *configuration only* (type/base_url/env var/model hint); no
secret ever lives here. Every ``openai_compatible`` preset works with
:class:`agent_hive.providers.openai_compat.OpenAICompatProvider`.
``anthropic_native`` and ``gemini_native`` use dedicated adapters because
their native APIs differ from the OpenAI wire format (see providers docs
for the exact differences).

Claim discipline: a preset is marked ``verified=True`` only when the
endpoint contract is public and stable (documented by the vendor); the
*credential* must be supplied by the user — presets without a key are
listed as ``configured=False`` at runtime.
"""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------- cloud
    "openai": {
        "type": "openai_compatible", "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY", "model_hint": "gpt-4o-mini",
        "client": "ChatGPT-compatible", "verified": True,
    },
    "anthropic": {
        "type": "anthropic_native", "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY", "model_hint": "claude-sonnet-4-5",
        "client": "Claude", "verified": True,
        "notes": "native /v1/messages; system prompt is top-level, max_tokens required",
    },
    "gemini": {
        "type": "gemini_native", "base_url": "https://generativelanguage.googleapis.com",
        "api_key_env": "GEMINI_API_KEY", "model_hint": "gemini-2.5-flash",
        "client": "Gemini", "verified": True,
        "notes": "native v1beta generateContent; OpenAI-compatible mirror exists "
                 "at {base_url}/v1beta/openai/ as fallback",
    },
    "zai": {
        "type": "openai_compatible", "base_url": "https://api.z.ai/api/paas/v4",
        "api_key_env": "ZAI_API_KEY", "model_hint": "glm-4.6",
        "client": "Z.ai (GLM)", "verified": True,
    },
    "deepseek": {
        "type": "openai_compatible", "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY", "model_hint": "deepseek-chat",
        "client": "DeepSeek", "verified": True,
    },
    "qwen": {
        "type": "openai_compatible", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "QWEN_API_KEY", "model_hint": "qwen-plus",
        "client": "Qwen (DashScope compat mode)", "verified": True,
    },
    "mistral": {
        "type": "openai_compatible", "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY", "model_hint": "mistral-large-latest",
        "client": "Mistral", "verified": True,
    },
    "grok": {
        "type": "openai_compatible", "base_url": "https://api.x.ai/v1",
        "api_key_env": "GROK_API_KEY", "model_hint": "grok-3",
        "client": "Grok (xAI)", "verified": True,
    },
    "perplexity": {
        "type": "openai_compatible", "base_url": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY", "model_hint": "sonar",
        "client": "Perplexity", "verified": True,
        "notes": "supports /chat/completions; /models listing may differ",
    },
    "openrouter": {
        "type": "openai_compatible", "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY", "model_hint": "openai/gpt-4o-mini",
        "client": "OpenRouter (multi-provider router)", "verified": True,
    },
    # ------------------------------------------------------------- local
    "ollama": {
        "type": "ollama", "base_url": "http://localhost:11434",
        "api_key_env": None, "model_hint": "llama3.2",
        "client": "Ollama", "verified": True,
    },
    "lm_studio": {
        "type": "openai_compatible", "base_url": "http://localhost:1234/v1",
        "api_key_env": None, "model_hint": "loaded-model",
        "client": "LM Studio (local server)", "verified": True,
    },
    "llama_cpp": {
        "type": "openai_compatible", "base_url": "http://localhost:8080/v1",
        "api_key_env": None, "model_hint": "local",
        "client": "llama.cpp server", "verified": True,
    },
    "vllm": {
        "type": "openai_compatible", "base_url": "http://localhost:8001/v1",
        "api_key_env": None, "model_hint": "served-model-name",
        "client": "vLLM OpenAI server", "verified": True,
    },
    "localai": {
        "type": "openai_compatible", "base_url": "http://localhost:8080/v1",
        "api_key_env": None, "model_hint": "gpt-4",
        "client": "LocalAI", "verified": True,
    },
    "huggingface": {
        "type": "openai_compatible", "base_url": "https://router.huggingface.co/v1",
        "api_key_env": "HF_TOKEN", "model_hint": "meta-llama/Llama-3.1-8B-Instruct",
        "client": "HuggingFace Inference Providers (OpenAI-compatible router)",
        "verified": True,
    },
}


def provider_presets() -> dict[str, Any]:
    """Preset map for API/CLI discovery (no secrets)."""
    return {k: {kk: vv for kk, vv in v.items()} for k, v in PRESETS.items()}


def preset_for_config(name: str) -> dict[str, Any]:
    """The ``configs/agents/*.yaml`` provider stanza for a preset name."""
    preset = PRESETS.get(name)
    if preset is None:
        raise KeyError(f"unknown provider preset '{name}'")
    stanza: dict[str, Any] = {
        "type": preset["type"],
        "model": preset["model_hint"],
    }
    if preset.get("base_url"):
        stanza["base_url"] = preset["base_url"]
    if preset.get("api_key_env"):
        stanza["api_key_env"] = preset["api_key_env"]
    return stanza
