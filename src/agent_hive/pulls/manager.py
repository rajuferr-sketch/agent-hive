"""Pull Request Manager — lifecycle, agent reviews, guarded merge.

PR lifecycle::

    open ──▶ changes_requested ──(new review)──▶ open ──▶ approved ──▶ merged
    open/approved/changes_requested ──▶ closed (reopen allowed if not merged)

Review aggregation follows GitHub semantics:

* any ``request_changes`` verdict => PR status ``changes_requested``;
* at least one ``approve`` and no open ``request_changes`` => ``approved``;
* a merge is **only** allowed from ``approved`` — the merge guard refuses
  every other state, so an un-reviewed or rejected PR cannot land.
"""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from agent_hive.core.errors import AgentError
from agent_hive.core.events import EventBus
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import PullRequest, PullRequestReview


class PullRequestManager:
    """Async service over the ``pull_requests`` and ``pr_reviews`` tables."""

    def __init__(self, event_bus: EventBus) -> None:
        self.events = event_bus

    # ---------------------------------------------------------------- create
    async def open_pr(
        self,
        title: str,
        source_branch: str,
        *,
        description: str = "",
        target_branch: str = "main",
        author: str = "api",
        files_changed: list[str] | None = None,
        related_issue_ids: list[str] | None = None,
        task_id: str | None = None,
    ) -> PullRequest:
        pr = PullRequest(
            number=await self._next_number(),
            title=title,
            description=description,
            source_branch=source_branch,
            target_branch=target_branch,
            author=author,
            files_changed=files_changed or [],
            related_issue_ids=related_issue_ids or [],
            task_id=task_id,
        )
        factory = get_session_factory()
        async with factory() as sess:
            sess.add(pr)
            await sess.commit()
            await sess.refresh(pr)
        await self.events.publish(
            "pull_request.opened", author,
            pr_id=pr.id, number=pr.number, title=pr.title,
            source=source_branch, target=target_branch,
        )
        return pr

    # ------------------------------------------------------------------ read
    async def get(self, pr_id: str) -> PullRequest | None:
        factory = get_session_factory()
        async with factory() as sess:
            return (await sess.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )).scalar_one_or_none()

    async def get_by_number(self, number: int) -> PullRequest | None:
        factory = get_session_factory()
        async with factory() as sess:
            return (await sess.execute(
                select(PullRequest).where(PullRequest.number == number)
            )).scalar_one_or_none()

    async def list(
        self,
        status: str | None = None,
        author: str | None = None,
        limit: int = 100,
    ) -> list[PullRequest]:
        factory = get_session_factory()
        async with factory() as sess:
            stmt = select(PullRequest)
            if status == "open":  # GitHub semantics: not merged/closed yet
                stmt = stmt.where(PullRequest.status.in_(list(PullRequest.REVIEWABLE_STATUSES)))
            elif status:
                stmt = stmt.where(PullRequest.status == status)
            if author:
                stmt = stmt.where(PullRequest.author == author)
            stmt = stmt.order_by(PullRequest.created_at.desc()).limit(limit)
            return list((await sess.execute(stmt)).scalars())

    async def stats(self) -> dict[str, int]:
        factory = get_session_factory()
        async with factory() as sess:
            rows = await sess.execute(
                select(PullRequest.status, func.count()).group_by(PullRequest.status)
            )
            return {status: count for status, count in rows}

    # ---------------------------------------------------------------- review
    async def review(
        self,
        pr_id: str,
        reviewer: str,
        verdict: str,
        *,
        score: float = 0.0,
        summary: str = "",
        comments: builtins.list[dict] | None = None,
    ) -> PullRequest:
        """Record a review and recompute the aggregate PR status."""
        if verdict not in PullRequestReview.ALL_VERDICTS:
            raise AgentError(
                f"Unknown verdict '{verdict}'. "
                f"Valid: {sorted(PullRequestReview.ALL_VERDICTS)}"
            )
        factory = get_session_factory()
        async with factory() as sess:
            pr = (await sess.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )).scalar_one_or_none()
            if pr is None:
                raise AgentError(f"Pull request '{pr_id}' not found")
            if pr.status not in PullRequest.REVIEWABLE_STATUSES:
                raise AgentError(
                    f"PR #{pr.number} is '{pr.status}' and cannot be reviewed"
                )
            sess.add(PullRequestReview(
                pull_request_id=pr.id, reviewer=reviewer, verdict=verdict,
                score=score, summary=summary, comments=comments or [],
            ))
            # Re-aggregate over all reviews so far.
            rows = (await sess.execute(
                select(PullRequestReview.verdict)
                .where(PullRequestReview.pull_request_id == pr.id)
            )).scalars().all()
            verdicts = set(rows)
            if PullRequestReview.VERDICT_REQUEST_CHANGES in verdicts:
                pr.status = PullRequest.STATUS_CHANGES_REQUESTED
            elif PullRequestReview.VERDICT_APPROVE in verdicts:
                pr.status = PullRequest.STATUS_APPROVED
            # comments-only reviews never change the status
            await sess.commit()
            await sess.refresh(pr)
        await self.events.publish(
            "pull_request.review", reviewer,
            pr_id=pr.id, number=pr.number, verdict=verdict, status=pr.status,
        )
        return pr

    async def agent_review(
        self, pr_id: str, runtime: Any  # AgentRuntime; Any avoids a cyclic import
    ) -> PullRequest:
        """Have the hive's ``reviewer`` agent review this PR end-to-end.

        The agent produces a structured review via its provider chain; the
        verdict is extracted from the output (falls back to ``comment``) and
        recorded through :meth:`review`.
        """
        pr = await self.get(pr_id)
        if pr is None:
            raise AgentError(f"Pull request '{pr_id}' not found")
        payload = {
            "pr_number": pr.number,
            "title": pr.title,
            "description": pr.description,
            "source_branch": pr.source_branch,
            "target_branch": pr.target_branch,
            "files_changed": pr.files_changed,
        }
        result = await runtime.run_direct(
            "reviewer",
            f"Review pull request #{pr.number}: {pr.title}",
            payload=payload,
            description="Agent-driven pull request review",
        )
        text = str(result.get("text", result.get("output", "")))
        if "request_changes" in text or "request changes" in text.lower():
            verdict = PullRequestReview.VERDICT_REQUEST_CHANGES
        elif "approve" in text.lower():
            verdict = PullRequestReview.VERDICT_APPROVE
        else:
            verdict = PullRequestReview.VERDICT_COMMENT
        return await self.review(
            pr_id, "reviewer", verdict,
            summary=text[:2000], comments=[],
        )

    # ----------------------------------------------------------------- merge
    async def merge(self, pr_id: str, merged_by: str = "master") -> PullRequest:
        """Merge an approved PR (guarded transition)."""
        factory = get_session_factory()
        async with factory() as sess:
            pr = (await sess.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )).scalar_one_or_none()
            if pr is None:
                raise AgentError(f"Pull request '{pr_id}' not found")
            if pr.status != PullRequest.STATUS_APPROVED:
                raise AgentError(
                    f"PR #{pr.number} cannot be merged from status "
                    f"'{pr.status}' — at least one 'approve' review with no "
                    f"'request_changes' is required"
                )
            pr.status = PullRequest.STATUS_MERGED
            pr.merged_at = datetime.now(timezone.utc)
            pr.merged_by = merged_by
            await sess.commit()
            await sess.refresh(pr)
        await self.events.publish(
            "pull_request.merged", merged_by,
            pr_id=pr.id, number=pr.number,
        )
        return pr

    async def close(self, pr_id: str) -> PullRequest:
        factory = get_session_factory()
        async with factory() as sess:
            pr = (await sess.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )).scalar_one_or_none()
            if pr is None:
                raise AgentError(f"Pull request '{pr_id}' not found")
            if pr.status == PullRequest.STATUS_MERGED:
                raise AgentError("A merged PR cannot be closed")
            pr.status = PullRequest.STATUS_CLOSED
            await sess.commit()
            await sess.refresh(pr)
        await self.events.publish(
            "pull_request.closed", "pull_request_manager", pr_id=pr_id
        )
        return pr

    async def reopen(self, pr_id: str) -> PullRequest:
        factory = get_session_factory()
        async with factory() as sess:
            pr = (await sess.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )).scalar_one_or_none()
            if pr is None:
                raise AgentError(f"Pull request '{pr_id}' not found")
            if pr.status != PullRequest.STATUS_CLOSED:
                raise AgentError(
                    f"Only a closed PR can be reopened (current: {pr.status})"
                )
            pr.status = PullRequest.STATUS_OPEN
            await sess.commit()
            await sess.refresh(pr)
        await self.events.publish(
            "pull_request.reopened", "pull_request_manager", pr_id=pr_id
        )
        return pr

    # -------------------------------------------------------------- internals
    @staticmethod
    async def _next_number() -> int:
        factory = get_session_factory()
        async with factory() as sess:
            current = (await sess.execute(
                select(func.max(PullRequest.number))
            )).scalar_one_or_none()
        return (current or 0) + 1


__all__ = ["PullRequestManager"]
