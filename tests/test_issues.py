"""Tests for the issue tracker: numbering, lifecycle transitions,
comments, assignment (manual + best-match), stats and task linking."""

from __future__ import annotations

import pytest

from agent_hive.core.errors import AgentError
from agent_hive.core.events import EventBus
from agent_hive.db.models import Issue
from agent_hive.issues.manager import IssueManager


def _manager() -> IssueManager:
    return IssueManager(EventBus())


async def test_create_assigns_sequential_numbers() -> None:
    """Issues get increasing 1-based numbers, like GitHub."""
    issues = _manager()
    first = await issues.create("First bug", priority=3)
    second = await issues.create("Second bug")
    assert first.number == 1
    assert second.number == first.number + 1
    assert first.status == Issue.STATUS_OPEN
    stored = await issues.get(first.id)
    assert stored is not None and stored.priority == 3


async def test_lifecycle_happy_path() -> None:
    """open -> in_progress -> resolved -> closed."""
    issues = _manager()
    issue = await issues.create("Broken endpoint")
    moved = await issues.set_status(issue.id, Issue.STATUS_IN_PROGRESS)
    assert moved.status == Issue.STATUS_IN_PROGRESS
    moved = await issues.set_status(issue.id, Issue.STATUS_RESOLVED)
    assert moved.status == Issue.STATUS_RESOLVED
    closed = await issues.close(issue.id)
    assert closed.status == Issue.STATUS_CLOSED
    assert closed.closed_at is not None


async def test_illegal_transition_is_rejected() -> None:
    """open -> resolved is allowed, but closed -> in_progress is not."""
    issues = _manager()
    issue = await issues.create("Feature request")
    await issues.close(issue.id)
    with pytest.raises(AgentError, match="Illegal transition"):
        await issues.set_status(issue.id, Issue.STATUS_IN_PROGRESS)


async def test_reopen_clears_closed_at() -> None:
    """A closed issue can be reopened; closed_at is reset."""
    issues = _manager()
    issue = await issues.create("Reopen me")
    await issues.close(issue.id)
    reopened = await issues.reopen(issue.id)
    assert reopened.status == Issue.STATUS_OPEN
    assert reopened.closed_at is None


async def test_comments_persist_and_attach() -> None:
    """Comments are stored and returned with the issue detail."""
    issues = _manager()
    issue = await issues.create("Discuss me")
    await issues.comment(issue.id, "Reproduced on main", author="tester")
    await issues.comment(issue.id, "Root cause found", author="debugger")
    stored = await issues.get(issue.id)
    assert stored is not None
    bodies = [c.body for c in stored.comments]
    assert "Reproduced on main" in bodies and "Root cause found" in bodies
    assert {c.author for c in stored.comments} == {"tester", "debugger"}


async def test_comment_on_missing_issue_fails() -> None:
    issues = _manager()
    with pytest.raises(AgentError, match="not found"):
        await issues.comment("no-such-id", "hello")


async def test_manual_assign_moves_to_in_progress() -> None:
    """Assigning an open issue starts work on it."""
    issues = _manager()
    issue = await issues.create("Fix the login flow")
    assigned = await issues.assign(issue.id, "programmer")
    assert assigned.assignee == "programmer"
    assert assigned.status == Issue.STATUS_IN_PROGRESS


async def test_assign_best_matches_label_to_capability() -> None:
    """The 'security' label routes the issue to the security agent."""

    class FakeRuntime:
        def best_agent_for(self, capabilities=None, exclude_busy=False):
            return "security" if "security" in (capabilities or []) else "analyst"

    issues = _manager()
    issue = await issues.create("SQL injection vector", labels=["security"])
    assigned = await issues.assign_best(issue.id, FakeRuntime())
    assert assigned.assignee == "security"
    assert assigned.status == Issue.STATUS_IN_PROGRESS


async def test_list_filters_by_status_and_label() -> None:
    issues = _manager()
    bug = await issues.create("A bug", labels=["bug"], priority=2)
    await issues.create("A feature", labels=["feature"])
    open_issues = await issues.list(status="open")
    assert {i.id for i in open_issues} >= {bug.id}
    bugs = await issues.list(label="bug")
    assert [i.id for i in bugs] == [bug.id]


async def test_stats_counts_by_status() -> None:
    """Counters grow by exactly the issues created here (delta-based,
    because the test database is shared across the whole suite)."""
    issues = _manager()
    before = await issues.stats()
    base_closed = before.get(Issue.STATUS_CLOSED, 0)
    base_open = before.get(Issue.STATUS_OPEN, 0)

    a = await issues.create("One")
    b = await issues.create("Two")
    await issues.close(a.id)

    stats = await issues.stats()
    assert stats.get(Issue.STATUS_CLOSED, 0) == base_closed + 1
    assert stats.get(Issue.STATUS_OPEN, 0) == base_open + 1  # b is open
    assert stats["open_total"] >= 1
    assert b.id


async def test_link_task_records_reference() -> None:
    tasks_mgr = __import__(
        "agent_hive.tasks.manager", fromlist=["TaskManager"]
    ).TaskManager(EventBus())
    task = await tasks_mgr.create("Fix issue task")

    issues = _manager()
    issue = await issues.create("With task")
    linked = await issues.link_task(issue.id, task.id)
    assert linked.related_task_id == task.id
