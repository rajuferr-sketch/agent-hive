"""OpenAI-compatible chat-completions provider.

Works with OpenAI, Azure OpenAI gateways, vLLM, LM Studio, LiteLLM,
Groq, Together, DeepSeek and any server exposing
``POST {base_url}/chat/completions``.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

import httpx

from agent_hive.core.errors import ProviderError
from agent_hive.providers.base import CompletionResult, LLMProvider

# One SSL context for every provider client: avoids reloading the Windows
# certificate store for each agent (~0.6 s per client otherwise).
_SHARED_SSL: ssl.SSLContext | None = None


def shared_ssl_context() -> ssl.SSLContext:
    global _SHARED_SSL
    if _SHARED_SSL is None:
        _SHARED_SSL = ssl.create_default_context()
    return _SHARED_SSL


class OpenAICompatProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        params: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.params = params or {}
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout, verify=shared_ssl_context())

    @classmethod
    def from_config(cls, cfg: Any) -> OpenAICompatProvider:
        """Build from a :class:`agent_hive.config.loader.ProviderConfig`."""
        base_url = cfg.base_url
        if not base_url and cfg.base_url_env:
            base_url = os.getenv(cfg.base_url_env, "")
        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.getenv(cfg.api_key_env) if cfg.api_key_env else os.getenv("OPENAI_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        client = httpx.AsyncClient(
            timeout=cfg.params.pop("_timeout", 120.0),
            headers=headers,
            verify=shared_ssl_context(),
        )
        provider = cls.__new__(cls)
        LLMProvider.__init__(provider)  # no-op, ABC without state
        provider.model = cfg.model
        provider.base_url = base_url.rstrip("/")
        provider.api_key_env = cfg.api_key_env or "OPENAI_API_KEY"
        provider.params = {k: v for k, v in (cfg.params or {}).items() if not k.startswith("_")}
        provider.timeout = 120.0
        provider._client = client
        return provider

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, **self.params, **params}
        try:
            resp = await self._client.post(f"{self.base_url}/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI-compatible call failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Malformed response payload: {data}") from exc
        return CompletionResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.model),
            usage=data.get("usage") or {},
            raw=data,
        )

    def configured(self) -> bool:
        """A default OpenAI endpoint without an API key is known-unusable."""
        key = os.getenv(self.api_key_env) if self.api_key_env else os.getenv("OPENAI_API_KEY")
        if key:
            return True
        return "api.openai.com" not in self.base_url

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/models")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
