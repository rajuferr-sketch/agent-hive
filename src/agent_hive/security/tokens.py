"""Scoped API tokens: issue, verify, revoke, rotate.

Design
------
* Raw tokens look like ``ahive_<32 hex>`` and are shown **once** at issue
  time; the database stores only a SHA-256 hash plus a display prefix.
* Verification is constant-time (``hmac.compare_digest``) and updates the
  ``last_used_at`` marker without leaking the raw value into logs.
* Scopes follow ``resource:action`` with ``*`` wildcards (``memory:*``).
* Rotation revokes the old token and issues a replacement atomically.
* The optional ``API_MASTER_TOKEN`` environment variable acts as an
  implicit admin identity for bootstrap (its hash is computed on the fly,
  never persisted).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import PermissionDenied
from agent_hive.core.ids import new_id
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import ApiToken

TOKEN_PREFIX = "ahive_"
_DISPLAY_PREFIX_LEN = 12


def hash_token(raw: str) -> str:
    """SHA-256 of the raw token (never logged, never reversed)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    """Normalise DB-loaded datetimes to timezone-aware UTC (SQLite is naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(slots=True)
class TokenIdentity:
    """Resolved caller identity attached to every request."""

    token_id: str
    subject: str
    role: str
    scopes: list[str] = field(default_factory=list)

    def has_scope(self, required: str) -> bool:
        for scope in self.scopes:
            if scope == "*" or scope == required:
                return True
            if scope.endswith(":*") and required.startswith(scope[:-1]):
                return True
        return False


class TokenManager:
    """Async service over the ``api_tokens`` table."""

    # ------------------------------------------------------------------ issue
    async def issue(
        self,
        subject: str,
        scopes: list[str],
        role: str = "client",
        ttl_s: int | None = None,
    ) -> tuple[TokenIdentity, str]:
        """Create a token; returns ``(identity, raw_token)`` — raw shown once."""
        raw = TOKEN_PREFIX + secrets.token_hex(16)
        settings = get_settings()
        ttl = settings.token_default_ttl if ttl_s is None else max(1, ttl_s)
        row = ApiToken(
            id=new_id(),
            subject=subject,
            role=role,
            prefix=raw[:_DISPLAY_PREFIX_LEN],
            token_hash=hash_token(raw),
            scopes=list(scopes),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
        factory = get_session_factory()
        async with factory() as sess:
            sess.add(row)
            await sess.commit()
        return (
            TokenIdentity(
                token_id=row.id, subject=subject, role=role, scopes=list(scopes)
            ),
            raw,
        )

    # ----------------------------------------------------------------- verify
    async def verify(self, raw: str) -> TokenIdentity:
        """Resolve a raw token to an identity or raise ``PermissionDenied``."""
        if not raw:
            raise PermissionDenied("Missing token")
        # Bootstrap master token (environment): implicit admin.
        master = get_settings().api_master_token
        if master and hmac.compare_digest(raw, master):
            return TokenIdentity(
                token_id="master", subject="master", role="admin", scopes=["*"]
            )
        digest = hash_token(raw)
        factory = get_session_factory()
        async with factory() as sess:
            row = (
                await sess.execute(
                    select(ApiToken).where(ApiToken.token_hash == digest)
                )
            ).scalar_one_or_none()
            if row is None:
                raise PermissionDenied("Unknown token")
            if row.revoked_at is not None:
                raise PermissionDenied("Token revoked")
            now = datetime.now(timezone.utc)
            if row.expires_at is not None and _as_utc(row.expires_at) < now:
                raise PermissionDenied("Token expired")
            await sess.execute(
                update(ApiToken)
                .where(ApiToken.id == row.id)
                .values(last_used_at=now)
            )
            await sess.commit()
            return TokenIdentity(
                token_id=row.id,
                subject=row.subject,
                role=row.role,
                scopes=list(row.scopes),
            )

    # ----------------------------------------------------------------- revoke
    async def revoke(self, token_id: str) -> bool:
        factory = get_session_factory()
        async with factory() as sess:
            res = await sess.execute(
                update(ApiToken)
                .where(ApiToken.id == token_id, ApiToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await sess.commit()
            return bool(getattr(res, "rowcount", 0))

    async def revoke_raw(self, raw: str) -> bool:
        digest = hash_token(raw)
        factory = get_session_factory()
        async with factory() as sess:
            res = await sess.execute(
                update(ApiToken)
                .where(ApiToken.token_hash == digest, ApiToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await sess.commit()
            return bool(getattr(res, "rowcount", 0))

    # ----------------------------------------------------------------- rotate
    async def rotate(
        self, raw: str, ttl_s: int | None = None
    ) -> tuple[TokenIdentity, str] | None:
        """Revoke ``raw`` and issue a replacement with identical scopes."""
        digest = hash_token(raw)
        factory = get_session_factory()
        async with factory() as sess:
            row = (
                await sess.execute(
                    select(ApiToken).where(ApiToken.token_hash == digest)
                )
            ).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            identity, new_raw = await self.issue(
                subject=row.subject,
                scopes=list(row.scopes),
                role=row.role,
                ttl_s=ttl_s,
            )
            row.revoked_at = datetime.now(timezone.utc)
            await sess.execute(
                update(ApiToken)
                .where(ApiToken.id == identity.token_id)
                .values(rotated_from=row.id)
            )
            await sess.commit()
            return identity, new_raw

    # ------------------------------------------------------------------ list
    async def active_tokens_exist(self) -> bool:
        """True when at least one non-revoked token exists (enforced mode)."""
        factory = get_session_factory()
        async with factory() as sess:
            row = (
                await sess.execute(
                    select(ApiToken.id)
                    .where(ApiToken.revoked_at.is_(None))
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None

    async def list_tokens(self, limit: int = 100) -> list[dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as sess:
            rows = (
                await sess.execute(
                    select(ApiToken).order_by(ApiToken.created_at.desc()).limit(limit)
                )
            ).scalars()
            return [
                {
                    "id": r.id,
                    "subject": r.subject,
                    "role": r.role,
                    "prefix": r.prefix,
                    "scopes": list(r.scopes),
                    "revoked": r.revoked_at is not None,
                    "expires_at": (
                        _as_utc(r.expires_at).isoformat()
                        if r.expires_at is not None
                        else None
                    ),
                }
                for r in rows
            ]
