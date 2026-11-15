"""Pydantic API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MissionRequest(BaseModel):
    text: str = Field(min_length=5, max_length=20_000, description="User request")
    mode: str | None = Field(
        default=None, pattern="^[ACB]$", description="Force mode A/C/B (optional)"
    )
    title: str | None = Field(default=None, max_length=200)


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    agent_name: str | None = None
    priority: int = Field(default=5, ge=1, le=9)
    depends_on: list[str] = Field(default_factory=list)


class DirectMessage(BaseModel):
    from_agent: str = "master"
    kind: str = Field(default="info", pattern="^(info|request|response|assistance|problem|proposal|challenge|review)$")
    content: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=9)


class SharedMemoryWrite(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any]
    author: str = "master"
    tags: list[str] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    allow_mock: bool | None = None
