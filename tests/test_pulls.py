"""Tests for the pull-request subsystem: opening, review aggregation,
guarded merge, close/reopen and agent-driven review."""

from __future__ import annotations

import pytest

from agent_hive.core.errors import AgentError
from agent_hive.core.events import EventBus
from agent_hive.db.models import PullRequest, PullRequestReview
from agent_hive.pulls.manager import PullRequestManager


def _manager() -> PullRequestManager:
    return PullRequestManager(EventBus())


async def test_open_pr_assigns_sequential_numbers() -> None:
    pulls = _manager()
    first = await pulls.open_pr("Add feature X", "feat/x")
    second = await pulls.open_pr("Add feature Y", "feat/y", target_branch="develop")
    assert first.number == 1
    assert second.number == first.number + 1
    assert first.status == PullRequest.STATUS_OPEN
    assert second.target_branch == "develop"


async def test_single_approve_marks_pr_approved() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("One-shot approval", "feat/a")
    reviewed = await pulls.review(
        pr.id, "reviewer", PullRequestReview.VERDICT_APPROVE, score=0.9
    )
    assert reviewed.status == PullRequest.STATUS_APPROVED


async def test_request_changes_blocks_approval() -> None:
    """Any request_changes keeps the PR in changes_requested even with an approve."""
    pulls = _manager()
    pr = await pulls.open_pr("Mixed verdicts", "feat/b")
    await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_REQUEST_CHANGES)
    reviewed = await pulls.review(pr.id, "qa", PullRequestReview.VERDICT_APPROVE)
    assert reviewed.status == PullRequest.STATUS_CHANGES_REQUESTED


async def test_comment_only_review_does_not_change_status() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Just a remark", "feat/c")
    reviewed = await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_COMMENT)
    assert reviewed.status == PullRequest.STATUS_OPEN


async def test_merge_guard_refuses_unapproved_pr() -> None:
    """Merging without approval is forbidden."""
    pulls = _manager()
    pr = await pulls.open_pr("Not approved", "feat/d")
    with pytest.raises(AgentError, match="cannot be merged"):
        await pulls.merge(pr.id)


async def test_merge_guard_refuses_changes_requested() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Rejected PR", "feat/e")
    await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_REQUEST_CHANGES)
    with pytest.raises(AgentError, match="cannot be merged"):
        await pulls.merge(pr.id)


async def test_merge_approved_pr_stamps_metadata() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Ready to land", "feat/f")
    await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_APPROVE)
    merged = await pulls.merge(pr.id, merged_by="master")
    assert merged.status == PullRequest.STATUS_MERGED
    assert merged.merged_by == "master"
    assert merged.merged_at is not None


async def test_merge_is_terminal_and_close_is_not() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Terminal checks", "feat/g")
    await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_APPROVE)
    await pulls.merge(pr.id)
    with pytest.raises(AgentError, match="cannot be closed"):
        await pulls.close(pr.id)

    pr2 = await pulls.open_pr("Reopenable", "feat/h")
    await pulls.close(pr2.id)
    reopened = await pulls.reopen(pr2.id)
    assert reopened.status == PullRequest.STATUS_OPEN


async def test_review_after_merge_is_refused() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Late review", "feat/i")
    await pulls.review(pr.id, "reviewer", PullRequestReview.VERDICT_APPROVE)
    await pulls.merge(pr.id)
    with pytest.raises(AgentError, match="cannot be reviewed"):
        await pulls.review(pr.id, "qa", PullRequestReview.VERDICT_APPROVE)


async def test_unknown_verdict_is_rejected() -> None:
    pulls = _manager()
    pr = await pulls.open_pr("Bad verdict", "feat/j")
    with pytest.raises(AgentError, match="Unknown verdict"):
        await pulls.review(pr.id, "reviewer", "ship-it")


async def test_agent_review_uses_reviewer_agent_output() -> None:
    """agent_review extracts the verdict from the reviewer agent output."""

    class FakeRuntime:
        async def run_direct(self, agent_name, title, payload=None, description=""):
            assert agent_name == "reviewer"
            assert payload["pr_number"] >= 1
            return {"output": "LGTM, I approve this pull request."}

    pulls = _manager()
    pr = await pulls.open_pr("Agent reviewed", "feat/k")
    reviewed = await pulls.agent_review(pr.id, FakeRuntime())
    assert reviewed.status == PullRequest.STATUS_APPROVED
    assert reviewed.reviews[0].reviewer == "reviewer"


async def test_list_and_stats() -> None:
    """List filter by author + delta-based counters (shared test DB)."""
    pulls = _manager()
    marker = "stats-probe"
    a = await pulls.open_pr("A", "feat/a", author=marker)
    b = await pulls.open_pr("B", "feat/b", author=marker)
    await pulls.close(a.id)

    mine_open = await pulls.list(status="open", author=marker)
    assert {p.id for p in mine_open} == {b.id}

    before_merged = (await pulls.stats()).get(PullRequest.STATUS_CLOSED, 0)
    await pulls.close(b.id)
    stats = await pulls.stats()
    assert stats.get(PullRequest.STATUS_CLOSED, 0) == before_merged + 1
    assert a.id
