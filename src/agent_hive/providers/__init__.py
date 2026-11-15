"""Provider layer: pluggable LLM backends.

Every provider implements :class:`LLMProvider`. The factory builds an
ordered fallback chain per agent from its YAML configuration, so an agent
can run on OpenAI-compatible APIs, Ollama, or the deterministic mock
provider — independently of every other agent.
"""

from agent_hive.providers.base import CompletionResult, LLMProvider
from agent_hive.providers.factory import build_provider_chain, resolve_provider
from agent_hive.providers.mock import MockProvider
from agent_hive.providers.ollama import OllamaProvider
from agent_hive.providers.openai_compat import OpenAICompatProvider

__all__ = [
    "CompletionResult",
    "LLMProvider",
    "MockProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
    "build_provider_chain",
    "resolve_provider",
]
