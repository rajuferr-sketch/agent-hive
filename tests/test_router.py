"""Router difficulty-based selection tests."""

from __future__ import annotations


class _FakeProviderConfig:
    """Minimal provider config that satisfies both router checks and ProviderConfig."""

    def __init__(self, fast: bool = False, quality_focused: bool = False, **kwargs: object) -> None:
        self.fast = fast
        self.quality_focused = quality_focused
        self.type = kwargs.get("type", "mock")
        self.model = kwargs.get("model", "default")
        self.base_url = kwargs.get("base_url", "http://localhost")
        self.base_url_env = kwargs.get("base_url_env", "")
        self.api_key_env = kwargs.get("api_key_env", "")
        self.params = kwargs.get("params", {})


def test_route_low_difficulty() -> None:
    from agent_hive.providers.router import route

    cfg_fast = _FakeProviderConfig(fast=True)
    cfg_quality = _FakeProviderConfig(quality_focused=True)
    chain = route([cfg_fast, cfg_quality], difficulty=0.1)
    assert chain is not None


def test_route_high_difficulty() -> None:
    from agent_hive.providers.router import route

    cfg_fast = _FakeProviderConfig(fast=True)
    cfg_quality = _FakeProviderConfig(quality_focused=True)
    chain = route([cfg_fast, cfg_quality], difficulty=0.9)
    assert chain is not None