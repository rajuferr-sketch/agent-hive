"""Host (chat-AI) provider.

This provider does not call any LLM itself. Instead it writes the full
prompt of an agent to a request file and waits for the *host* AI (the one
running the chat) to read it, produce a completion and write the result to
a response file. This makes AgentHive usable in environments where no API
key and no local Ollama instance are available.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from agent_hive.core.errors import ProviderError
from agent_hive.core.ids import now_iso
from agent_hive.core.logging import get_logger
from agent_hive.providers.base import CompletionResult, LLMProvider

log = get_logger("agent_hive.host_provider")

DEFAULT_REQUEST_DIR = os.getenv("HOST_REQUEST_DIR", "./host_requests")
DEFAULT_RESPONSE_DIR = os.getenv("HOST_RESPONSE_DIR", "./host_responses")


class HostProvider(LLMProvider):
    name = "host"

    def __init__(
        self,
        model: str = "chat-host",
        request_dir: str | None = None,
        response_dir: str | None = None,
        timeout: float = 600.0,
        poll_interval: float = 1.0,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.request_dir = Path(request_dir or DEFAULT_REQUEST_DIR)
        self.response_dir = Path(response_dir or DEFAULT_RESPONSE_DIR)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.params = params or {}
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.response_dir.mkdir(parents=True, exist_ok=True)

    def configured(self) -> bool:
        return True

    async def complete(
        self, messages: list[dict[str, str]], **params: Any
    ) -> CompletionResult:
        request_id = uuid.uuid4().hex
        request_path = self.request_dir / f"{request_id}.json"
        response_path = self.response_dir / f"{request_id}.json"

        payload = {
            "id": request_id,
            "created_at": now_iso(),
            "messages": messages,
            "params": {**self.params, **params},
        }
        await asyncio.to_thread(
            request_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        log.info("Host provider wrote request %s — waiting for chat AI response",
                 request_path)

        waited = 0.0
        while waited < self.timeout:
            if response_path.exists():
                try:
                    data = json.loads(response_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ProviderError(f"Malformed host response: {exc}") from exc
                text = data.get("text", "") if isinstance(data, dict) else str(data)
                # Clean up consumed files.
                try:
                    request_path.unlink(missing_ok=True)
                    response_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return CompletionResult(
                    text=text,
                    provider=self.name,
                    model=data.get("model", self.model) if isinstance(data, dict) else self.model,
                    mock=False,
                    raw=data if isinstance(data, dict) else {},
                )
            await asyncio.sleep(self.poll_interval)
            waited += self.poll_interval

        raise ProviderError(
            f"Host provider timed out after {self.timeout}s waiting for "
            f"{response_path}"
        )

    async def health_check(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
