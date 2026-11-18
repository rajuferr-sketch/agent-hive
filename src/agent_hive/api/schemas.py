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


# ------------------------------------------------------------------- issues
class IssueCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=9)
    reporter: str = "api"
    assignee: str | None = None


class IssueCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    author: str = "api"
    meta: dict[str, Any] = Field(default_factory=dict)


class IssueAssign(BaseModel):
    agent_name: str | None = Field(
        default=None,
        description="Agent to assign; omit to pick the best-capable one",
    )


class IssueStatus(BaseModel):
    status: str = Field(pattern="^(open|in_progress|blocked|resolved|closed)$")


# -------------------------------------------------------------- pull requests
class PullRequestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    source_branch: str = Field(min_length=1, max_length=200)
    target_branch: str = "main"
    author: str = "api"
    files_changed: list[str] = Field(default_factory=list)
    related_issue_ids: list[str] = Field(default_factory=list)


class PullRequestReviewCreate(BaseModel):
    reviewer: str = "api"
    verdict: str | None = Field(
        default=None,
        pattern="^(approve|request_changes|comment)$",
        description="Required unless reviewer='agent' (verdict extracted from the agent output)",
    )
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    comments: list[dict[str, Any]] = Field(default_factory=list)


class PullRequestMerge(BaseModel):
    merged_by: str = "master"


# -------------------------------------------------------------------- agents
class AgentRegister(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern="^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=2, max_length=100)
    role: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    providers: list[dict[str, Any]]
    memory: dict[str, Any] = Field(default_factory=dict)
