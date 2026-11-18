"""SQLAlchemy 2.0 ORM models for AgentHive.

Tables
------
agents          agent registry snapshot (identity, capabilities, heartbeat)
tasks           task manager state machine (DAG via ``depends_on``)
messages        persistent internal message bus
memories        3-tier memory (individual / shared / history) with versioning
events          append-only operation audit log
verifications   quality-control verdicts for tasks
documents       ingested documents (PDF/DOCX/HTML/TXT/MD)
chunks          text chunks + embeddings for retrieval (RAG-ready)
issues          issue tracker (open/in_progress/blocked/resolved/closed)
issue_comments  threaded discussion on issues
pull_requests   PR lifecycle (open/changes_requested/approved/merged/closed)
pr_reviews      per-agent review verdicts on pull requests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from agent_hive.core.ids import now_iso


def _gen_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base with a consistent naming convention."""


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="offline")
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provider_chain: Mapped[list[Any]] = mapped_column(JSON, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    # Status machine:
    # pending -> queued -> assigned -> running -> completed | failed
    #                                  \-> blocked (deps unmet) / cancelled
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_ASSIGNED = "assigned"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_BLOCKED = "blocked"
    STATUS_CANCELLED = "cancelled"
    TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED}

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    mission_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_PENDING, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 (highest) .. 9
    mode: Mapped[str] = mapped_column(String(16), default="simple")  # A | C | B
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    timeout_s: Mapped[int] = mapped_column(Integer, default=120)
    depends_on: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(64), default="master")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso, onupdate=now_iso)

    parent: Mapped[Task | None] = relationship(
        remote_side=[id], backref="children", lazy="selectin"
    )

    __table_args__ = (Index("ix_tasks_status_priority", "status", "priority"),)


class Message(Base):
    __tablename__ = "messages"

    KIND_INFO = "info"
    KIND_REQUEST = "request"
    KIND_RESPONSE = "response"
    KIND_ASSISTANCE = "assistance"
    KIND_PROBLEM = "problem"
    KIND_PROPOSAL = "proposal"
    KIND_CHALLENGE = "challenge"
    KIND_REVIEW = "review"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    from_agent: Mapped[str] = mapped_column(String(64), index=True)
    to_agent: Mapped[str] = mapped_column(String(64), index=True, default="*")  # '*' = broadcast
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), default=KIND_INFO)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Memory(Base):
    __tablename__ = "memories"

    SCOPE_INDIVIDUAL = "individual"
    SCOPE_SHARED = "shared"
    SCOPE_HISTORY = "history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    agent_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # NULL => shared/global
    scope: Mapped[str] = mapped_column(String(16), index=True)
    key: Mapped[str] = mapped_column(String(256))
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("agent_name", "scope", "key", name="uq_memory_key"),
        Index("ix_memory_scope_agent", "scope", "agent_name"),
    )


class EventLog(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    url: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    author: Mapped[str] = mapped_column(String(256), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.id"), index=True)
    verifier: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    findings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Issue(Base):
    __tablename__ = "issues"

    # Status machine:
    # open ──▶ in_progress ──▶ resolved ──▶ closed
    #   │            │
    #   └──▶ blocked └──▶ blocked
    # closed/resolved ──reopen──▶ open
    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_BLOCKED = "blocked"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    OPEN_STATUSES = {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED}
    ALL_STATUSES = {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED,
                    STATUS_RESOLVED, STATUS_CLOSED}

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=STATUS_OPEN, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 (highest) .. 9
    labels: Mapped[list[Any]] = mapped_column(JSON, default=list)
    reporter: Mapped[str] = mapped_column(String(64), default="api")
    assignee: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    related_task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    comments: Mapped[list[IssueComment]] = relationship(
        back_populates="issue", cascade="all, delete-orphan",
        lazy="selectin", order_by="IssueComment.created_at",
    )

    __table_args__ = (Index("ix_issues_status_priority", "status", "priority"),)


class IssueComment(Base):
    __tablename__ = "issue_comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(64), default="api")
    body: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    issue: Mapped[Issue] = relationship(back_populates="comments")


class PullRequest(Base):
    __tablename__ = "pull_requests"

    # Status machine:
    # open ──▶ changes_requested ──(new review)──▶ open ──▶ approved ──▶ merged
    #   └────────────────────────────────────────────▶ approved
    # open/changes_requested/approved ──▶ closed (reopen allowed if not merged)
    STATUS_OPEN = "open"
    STATUS_CHANGES_REQUESTED = "changes_requested"
    STATUS_APPROVED = "approved"
    STATUS_MERGED = "merged"
    STATUS_CLOSED = "closed"
    REVIEWABLE_STATUSES = {STATUS_OPEN, STATUS_CHANGES_REQUESTED, STATUS_APPROVED}
    ALL_STATUSES = {STATUS_OPEN, STATUS_CHANGES_REQUESTED, STATUS_APPROVED,
                    STATUS_MERGED, STATUS_CLOSED}

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    source_branch: Mapped[str] = mapped_column(String(256))
    target_branch: Mapped[str] = mapped_column(String(256), default="main")
    author: Mapped[str] = mapped_column(String(64), default="api")
    status: Mapped[str] = mapped_column(String(32), default=STATUS_OPEN, index=True)
    files_changed: Mapped[list[Any]] = mapped_column(JSON, default=list)
    related_issue_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    task_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    merged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reviews: Mapped[list[PullRequestReview]] = relationship(
        back_populates="pull_request", cascade="all, delete-orphan",
        lazy="selectin", order_by="PullRequestReview.created_at",
    )


class PullRequestReview(Base):
    __tablename__ = "pr_reviews"

    VERDICT_APPROVE = "approve"
    VERDICT_REQUEST_CHANGES = "request_changes"
    VERDICT_COMMENT = "comment"
    ALL_VERDICTS = {VERDICT_APPROVE, VERDICT_REQUEST_CHANGES, VERDICT_COMMENT}

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_gen_id)
    pull_request_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(32), default=VERDICT_COMMENT)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    comments: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    pull_request: Mapped[PullRequest] = relationship(back_populates="reviews")
