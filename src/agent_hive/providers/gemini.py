"""Google Gemini native provider — real adapter, not an OpenAI clone.

Differences from the OpenAI wire format (why this adapter exists):

* endpoint ``POST {base_url}/v1beta/models/{model}:generateContent``;
* API key travels in the ``x-goog-api-key`` header;
* the system prompt goes into ``systemInstruction.parts[0].text``;
* contents carry ``role`` ``user``/``model`` (not ``assistant``) with
  ``parts: [{text: ...}]`` blocks;
* the response text lives at ``candidates[0].content.parts[*].text``.

Gemini also exposes an OpenAI-compatible mirror at
``{base_url}/v1beta/openai/`` which works with ``OpenAICompatProvider``
when native function-calling parity is not required.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from agent_hive.core.errors import ProviderError
from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.providers.openai_compat import shared_ssl_context


class GeminiProvider(LLMProvider):
    name = "gemini_native"

    def __init__(
        self,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        api_key_env: str = "GEMINI_API_KEY",
        params: dict[str, Any] | None = None,
        timeout: float = 120.0,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.params = params or {}
        key = api_key if api_key is not None else os.getenv(api_key_env)
        self._headers = {"x-goog-api-key": key or ""}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers=self._headers, verify=shared_ssl_context()
        )

    @classmethod
    def from_config(cls, cfg: Any) -> GeminiProvider:
        base_url = cfg.base_url or os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"
        )
        return cls(
            model=cfg.model,
            base_url=base_url,
            api_key_env=cfg.api_key_env or "GEMINI_API_KEY",
            params=dict(cfg.params or {}),
        )

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        system_text = ""
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_text += text + "\n"
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            })
        if contents and contents[-1]["role"] == "model":
            contents.append({"role": "user", "parts": [{"text": "(continue)"}]})
        body: dict[str, Any] = {
            "contents": contents,
            **self.params,
            **params,
        }
        if system_text.strip():
            body["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
        try:
            resp = await self._client.post(url, json=body, headers=self._headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini call failed: {exc}") from exc
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Malformed Gemini payload: {data}") from exc
        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            usage=data.get("usageMetadata") or {},
            raw=data,
        )

    def configured(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/v1beta/models")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
