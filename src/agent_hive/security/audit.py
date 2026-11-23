"""Append-only audit trail.

``AuditLogger.log`` writes one row per security-relevant action with the
actor, action, resource, outcome and a *redacted* metadata blob. Failures
to persist an audit row are logged but never break the caller's request
(the audit trail is best-effort for availability, and its absence is
alertable via diagnostics).
"""

from __future__ import annotations

import json
from typing import Any

from agent_hive.core.logging import get_logger
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import AuditLog
from agent_hive.security.sanitize import redact_secrets, sanitize_input

log = get_logger("agent_hive.security.audit")

_VALID_OUTCOMES = ("ok", "denied", "error")


class AuditLogger:
    async def log(
        self,
        actor: str,
        action: str,
        resource: str = "",
        outcome: str = "ok",
        client: str = "",
        meta: dict[str, Any] | None = None,
    ) -> bool:
        """Record one audited event. Returns True when persisted."""
        if outcome not in _VALID_OUTCOMES:
            outcome = "error"
        try:
            safe_meta = json.loads(
                json.dumps(sanitize_input(meta or {}), ensure_ascii=False, default=str)
            )
            row = AuditLog(
                actor=(actor or "")[:128],
                action=(action or "")[:64],
                resource=(resource or "")[:128],
                outcome=outcome,
                client=(client or "")[:64],
                meta=safe_meta,
            )
            factory = get_session_factory()
            async with factory() as sess:
                sess.add(row)
                await sess.commit()
            return True
        except Exception as exc:  # noqa: BLE001 — audit must not break requests
            log.warning("audit write failed (action=%s): %s", action, exc)
            return False

    async def recent(
        self, limit: int = 100, actor: str | None = None, action: str | None = None
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        factory = get_session_factory()
        async with factory() as sess:
            stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
            if actor:
                stmt = stmt.where(AuditLog.actor == actor)
            if action:
                stmt = stmt.where(AuditLog.action == action)
            rows = (await sess.execute(stmt)).scalars()
            return [
                {
                    "ts": str(r.ts),
                    "actor": r.actor,
                    "action": r.action,
                    "resource": r.resource,
                    "outcome": r.outcome,
                    "client": r.client,
                    "meta": r.meta,
                }
                for r in rows
            ]

    @staticmethod
    def redact(text: str) -> str:
        """Convenience passthrough to :func:`redact_secrets`."""
        return redact_secrets(text)
