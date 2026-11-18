"""Simple token/cost accounting for missions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class TokenManager:
    budget_usd: float = 0.0
    usage: dict[str, TokenUsage] = field(default_factory=dict)

    def record(self, key: str, prompt_tokens: int = 0, completion_tokens: int = 0,
               cost_usd: float = 0.0) -> None:
        u = self.usage.setdefault(key, TokenUsage())
        u.prompt_tokens += prompt_tokens
        u.completion_tokens += completion_tokens
        u.cost_usd += cost_usd

    def total_cost(self) -> float:
        return sum(u.cost_usd for u in self.usage.values())

    def within_budget(self) -> bool:
        if self.budget_usd <= 0:
            return True
        return self.total_cost() <= self.budget_usd

    def summary(self) -> dict[str, Any]:
        return {
            "budget_usd": self.budget_usd,
            "total_cost_usd": self.total_cost(),
            "within_budget": self.within_budget(),
            "entries": {
                k: {
                    "prompt_tokens": v.prompt_tokens,
                    "completion_tokens": v.completion_tokens,
                    "cost_usd": v.cost_usd,
                }
                for k, v in self.usage.items()
            },
        }
