"""Issue Manager — creation, lifecycle, assignment, discussion, triage.

Issue lifecycle::

    open ──▶ in_progress ──▶ resolved ──▶ closed
      │            │
      └──▶ blocked └──▶ blocked
    resolved/closed ──reopen──▶ open

Issues are the bridge between the outside world and the hive: an issue can
be assigned to the best-capable agent (``assign_best()``), optionally linked
to a Task (so the scheduler executes the fix) and commented on by agents or
humans. Every transition is published on the event bus and persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from agent_hive.core.errors import AgentError
from agent_hive.core.events import EventBus
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Issue, IssueComment


class IssueManager:
    """Async service over the ``issues`` and ``issue_comments`` tables."""

    # Transitions allowed by ``set_status`` (from -> allowed targets).
    TRANSITIONS: dict[str, set[str]] = {
        Issue.STATUS_OPEN: {
            Issue.STATUS_IN_PROGRESS, Issue.STATUS_BLOCKED,
            Issue.STATUS_RESOLVED, Issue.STATUS_CLOSED,
        },
        Issue.STATUS_IN_PROGRESS: {
            Issue.STATUS_BLOCKED, Issue.STATUS_RESOLVED,
            Issue.STATUS_OPEN, Issue.STATUS_CLOSED,
        },
        Issue.STATUS_BLOCKED: {
            Issue.STATUS_OPEN, Issue.STATUS_IN_PROGRESS,
            Issue.STATUS_RESOLVED, Issue.STATUS_CLOSED,
        },
        Issue.STATUS_RESOLVED: {Issue.STATUS_CLOSED, Issue.STATUS_OPEN},
        Issue.STATUS_CLOSED: {Issue.STATUS_OPEN},  # reopen
    }

    def __init__(self, event_bus: EventBus) -> None:
        self.events = event_bus

    # ---------------------------------------------------------------- create
    async def create(
        self,
        title: str,
        description: str = "",
        *,
        labels: list[str] | None = None,
        priority: int = 5,
        reporter: str = "api",
        assignee: str | None = None,
        related_task_id: str | None = None,
    ) -> Issue:
        issue = Issue(
            number=await self._next_number(),
            title=title,
            description=description,
            labels=labels or [],
            priority=max(1, min(9, priority)),
            reporter=reporter,
            assignee=assignee,
            related_task_id=related_task_id,
        )
        factory = get_session_factory()
        async with factory() as sess:
            sess.add(issue)
            await sess.commit()
            await sess.refresh(issue)
        await self.events.publish(
            "issue.created", reporter,
            issue_id=issue.id, number=issue.number, title=issue.title,
            assignee=issue.assignee,
        )
        return issue

    # ------------------------------------------------------------------ read
    async def get(self, issue_id: str) -> Issue | None:
        factory = get_session_factory()
        async with factory() as sess:
            return (await sess.execute(
                select(Issue).where(Issue.id == issue_id)
            )).scalar_one_or_none()

    async def get_by_number(self, number: int) -> Issue | None:
        factory = get_session_factory()
        async with factory() as sess:
            return (await sess.execute(
                select(Issue).where(Issue.number == number)
            )).scalar_one_or_none()

    async def list(
        self,
        status: str | None = None,
        assignee: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> list[Issue]:
        factory = get_session_factory()
        async with factory() as sess:
            stmt = select(Issue)
            if status:
                if status == "open":  # GitHub semantics: any non-terminal state
                    stmt = stmt.where(Issue.status.in_(list(Issue.OPEN_STATUSES)))
                else:
                    stmt = stmt.where(Issue.status == status)
            if assignee:
                stmt = stmt.where(Issue.assignee == assignee)
            stmt = stmt.order_by(Issue.priority, Issue.created_at).limit(max(limit, 200))
            rows = list((await sess.execute(stmt)).scalars())
        if label:
            # JSON columns are not portable to query with operators; filter
            # in Python (SQLite/PostgreSQL compatible, no deprecation risk).
            rows = [r for r in rows if label in (r.labels or [])]
        return rows[:limit]

    async def stats(self) -> dict[str, int]:
        factory = get_session_factory()
        async with factory() as sess:
            rows = await sess.execute(
                select(Issue.status, func.count()).group_by(Issue.status)
            )
            by_status = {status: count for status, count in rows}
        by_status["open_total"] = sum(
            count for s, count in by_status.items() if s in Issue.OPEN_STATUSES
        )
        return by_status

    # ------------------------------------------------------------ transitions
    async def set_status(self, issue_id: str, status: str) -> Issue:
        """Move an issue through the lifecycle with transition validation."""
        factory = get_session_factory()
        async with factory() as sess:
            issue = (await sess.execute(
                select(Issue).where(Issue.id == issue_id)
            )).scalar_one_or_none()
            if issue is None:
                raise AgentError(f"Issue '{issue_id}' not found")
            if status not in Issue.ALL_STATUSES:
                raise AgentError(
                    f"Unknown issue status '{status}'. "
                    f"Valid: {sorted(Issue.ALL_STATUSES)}"
                )
            if status != issue.status and status not in self.TRANSITIONS[issue.status]:
                raise AgentError(
                    f"Illegal transition {issue.status} -> {status}. "
                    f"Allowed: {sorted(self.TRANSITIONS[issue.status])}"
                )
            issue.status = status
            if status == Issue.STATUS_CLOSED:
                issue.closed_at = datetime.now(timezone.utc)
            if status == Issue.STATUS_OPEN:  # reopen clears the closure stamp
                issue.closed_at = None
            await sess.commit()
            await sess.refresh(issue)
        await self.events.publish(
            "issue.status", "issue_manager",
            issue_id=issue.id, number=issue.number, status=status,
        )
        return issue

    async def reopen(self, issue_id: str) -> Issue:
        return await self.set_status(issue_id, Issue.STATUS_OPEN)

    async def close(self, issue_id: str) -> Issue:
        return await self.set_status(issue_id, Issue.STATUS_CLOSED)

    # ------------------------------------------------------------- assignment
    async def assign(self, issue_id: str, agent_name: str) -> Issue:
        """Assign an issue to an agent (any name is accepted; the hive
        roster is validated by the caller/API layer)."""
        factory = get_session_factory()
        async with factory() as sess:
            issue = (await sess.execute(
                select(Issue).where(Issue.id == issue_id)
            )).scalar_one_or_none()
            if issue is None:
                raise AgentError(f"Issue '{issue_id}' not found")
            issue.assignee = agent_name
            if issue.status == Issue.STATUS_OPEN:
                issue.status = Issue.STATUS_IN_PROGRESS
            await sess.commit()
            await sess.refresh(issue)
        await self.events.publish(
            "issue.assigned", "issue_manager",
            issue_id=issue.id, number=issue.number, assignee=agent_name,
        )
        return issue

    async def link_task(self, issue_id: str, task_id: str) -> Issue:
        factory = get_session_factory()
        async with factory() as sess:
            issue = (await sess.execute(
                select(Issue).where(Issue.id == issue_id)
            )).scalar_one_or_none()
            if issue is None:
                raise AgentError(f"Issue '{issue_id}' not found")
            issue.related_task_id = task_id
            await sess.commit()
            await sess.refresh(issue)
        await self.events.publish(
            "issue.linked_task", "issue_manager",
            issue_id=issue.id, task_id=task_id,
        )
        return issue

    # -------------------------------------------------------------- comments
    async def comment(
        self,
        issue_id: str,
        body: str,
        author: str = "api",
        meta: dict[str, Any] | None = None,
    ) -> IssueComment:
        factory = get_session_factory()
        async with factory() as sess:
            issue = (await sess.execute(
                select(Issue).where(Issue.id == issue_id)
            )).scalar_one_or_none()
            if issue is None:
                raise AgentError(f"Issue '{issue_id}' not found")
            row = IssueComment(
                issue_id=issue.id, author=author, body=body, meta=meta or {}
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
        await self.events.publish(
            "issue.comment", author,
            issue_id=issue_id, comment_id=row.id,
        )
        return row

    # ----------------------------------------------------------------- triage
    async def assign_best(
        self,
        issue_id: str,
        runtime: Any,  # AgentRuntime; typed Any to avoid a cyclic import
    ) -> Issue:
        """Assign the issue to the best-capable available agent.

        Capability matching uses the issue labels (e.g. ``bug`` -> debugging,
        ``security`` -> security) with round-robin fallback.
        """
        issue = await self.get(issue_id)
        if issue is None:
            raise AgentError(f"Issue '{issue_id}' not found")

        label_map = {
            "bug": "debugging",
            "security": "security",
            "performance": "performance",
            "database": "database",
            "frontend": "frontend",
            "api": "api",
            "docs": "documentation",
            "test": "testing",
            "refactor": "refactoring",
            "architecture": "architecture",
        }
        capabilities = [label_map.get(lbl, lbl) for lbl in (issue.labels or [])]
        agent_name = runtime.best_agent_for(capabilities) or runtime.best_agent_for()
        if agent_name is None:
            raise AgentError("No agent available for assignment")
        return await self.assign(issue_id, agent_name)

    # -------------------------------------------------------------- internals
    @staticmethod
    async def _next_number() -> int:
        factory = get_session_factory()
        async with factory() as sess:
            current = (await sess.execute(
                select(func.max(Issue.number))
            )).scalar_one_or_none()
        return (current or 0) + 1


__all__ = ["IssueManager"]
