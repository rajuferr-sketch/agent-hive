"""Simple model router: pick a provider chain by difficulty/cost/speed."""

from __future__ import annotations

from typing import Any

from agent_hive.providers.factory import ProviderChain, build_provider_chain


def route(providers_config: list[Any], difficulty: float = 0.5) -> ProviderChain:
    # For now just build the configured chain; difficulty-based selection
    # can be layered on top by callers filtering configs before calling.
    return build_provider_chain(providers_config)
