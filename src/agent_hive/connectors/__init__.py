"""Universal client connectors — how external AI clients reach AgentHive.

Server-side connectors (FastAPI routers mounted by the API app):

* :mod:`agent_hive.connectors.openai_api`  — OpenAI-compatible
  ``/v1/models`` + ``/v1/chat/completions`` (with tool-calling intent
  detection and SSE streaming);
* :mod:`agent_hive.connectors.ollama_api`  — Ollama-native
  ``/api/tags`` / ``/api/chat`` / ``/api/generate`` so any Ollama-aware
  UI can point at AgentHive;
* :mod:`agent_hive.connectors.generic`     — provider-neutral tool
  manifest + invocation parser shared by all function-calling clients;
* :mod:`agent_hive.connectors.ws`          — bidirectional WebSocket
  protocol at ``/ws/universal`` (requests, tool calls, live events).

The client-side direction (AgentHive *calling* ChatGPT, Claude, Gemini,
Z.ai, DeepSeek, Qwen, Mistral, Grok, Perplexity, Ollama, HF, llama.cpp,
vLLM, LM Studio, LocalAI) lives in :mod:`agent_hive.providers` — the
presets module documents each verified endpoint contract.
"""

from agent_hive.connectors.generic import (
    GENERIC_TOOLS_MANIFEST,
    parse_tool_invocation,
    tool_manifest,
)

__all__ = ["GENERIC_TOOLS_MANIFEST", "parse_tool_invocation", "tool_manifest"]
