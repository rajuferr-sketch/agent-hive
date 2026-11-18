"""Ollama provider for locally hosted open-source models."""

from __future__ import annotations

import os
import socket
import time
from typing import Any

import httpx

from agent_hive.core.errors import ProviderError
from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.providers.openai_compat import shared_ssl_context

DEFAULT_OLLAMA_URL = "http://localhost:11434"

_OLLAMA_AVAILABLE_CACHE: dict[str, tuple[float, bool]] = {}
_CACHE_TTL = 30.0


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        self.base_url = (
            base_url or os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.params = params or {}
        self._client = httpx.AsyncClient(timeout=timeout, verify=shared_ssl_context())

    @classmethod
    def from_config(cls, cfg: Any) -> OllamaProvider:
        provider = cls(model=cfg.model, base_url=cfg.base_url, params=cfg.params or {})
        return provider

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {**self.params, **params},
        }
        try:
            resp = await self._client.post(f"{self.base_url}/api/chat", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama call failed: {exc}") from exc
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return CompletionResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.model),
            usage={
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            },
            raw=data,
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    def configured(self) -> bool:
        # Explicitly configured endpoint: always considered usable.
        if self.base_url != DEFAULT_OLLAMA_URL or os.getenv("OLLAMA_BASE_URL"):
            return True
        # Default localhost: probe once (cached) so an absent Ollama does
        # not generate repeated connection-refused noise on every agent call.
        now = time.monotonic()
        cached = _OLLAMA_AVAILABLE_CACHE.get(self.base_url)
        if cached is not None and (now - cached[0]) < _CACHE_TTL:
            return cached[1]
        try:
            host = "localhost"
            port = 11434
            with socket.create_connection((host, port), timeout=0.3):
                available = True
        except OSError:
            available = False
        _OLLAMA_AVAILABLE_CACHE[self.base_url] = (now, available)
        return available

    async def aclose(self) -> None:
        await self._client.aclose()
