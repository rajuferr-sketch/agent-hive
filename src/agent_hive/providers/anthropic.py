"""Anthropic native provider (Claude) — real adapter, not an OpenAI clone.

Differences from the OpenAI wire format (why this adapter exists):

* endpoint ``POST {base_url}/v1/messages`` (no ``/chat/completions``);
* header ``x-api-key`` instead of ``Authorization: Bearer`` plus
  ``anthropic-version: 2023-06-01``;
* the system prompt is a **top-level ``system`` field**, not a message;
* ``max_tokens`` is required;
* response text lives at ``content[0].text`` where content is a list of
  typed blocks.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from agent_hive.core.errors import ProviderError
from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.providers.openai_compat import shared_ssl_context

DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    name = "anthropic_native"

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.anthropic.com",
        api_key_env: str = "ANTHROPIC_API_KEY",
        params: dict[str, Any] | None = None,
        timeout: float = 120.0,
        api_key: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.params = params or {}
        self.max_tokens = max_tokens
        key = api_key if api_key is not None else os.getenv(api_key_env)
        self._headers = {
            "x-api-key": key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers=self._headers, verify=shared_ssl_context()
        )

    @classmethod
    def from_config(cls, cfg: Any) -> AnthropicProvider:
        base_url = cfg.base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        return cls(
            model=cfg.model,
            base_url=base_url,
            api_key_env=cfg.api_key_env or "ANTHROPIC_API_KEY",
            params=dict(cfg.params or {}),
        )

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        # Split the OpenAI-style system message into the native field.
        system_text = ""
        chat: list[dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text += (msg.get("content") or "") + "\n"
            else:
                chat.append({"role": msg.get("role", "user"),
                             "content": msg.get("content", "")})
        if chat and chat[0]["role"] != "user":
            chat.insert(0, {"role": "user", "content": "(begin)"})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": chat,
            "max_tokens": int(params.pop("max_tokens", self.max_tokens)),
            **self.params,
            **params,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        try:
            resp = await self._client.post(f"{self.base_url}/v1/messages", json=body,
                                          headers=self._headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic call failed: {exc}") from exc
        data = resp.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        if not text and blocks:
            raise ProviderError(f"Malformed Anthropic content: {data}")
        return CompletionResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.model),
            usage=data.get("usage") or {},
            raw=data,
        )

    def configured(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/v1/models")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
