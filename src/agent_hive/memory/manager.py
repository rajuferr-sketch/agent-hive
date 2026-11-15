"""Three-tier persistent memory.

Scopes
------
``individual``  private per-agent notes (agent_name set, scope=individual)
``shared``      project-wide knowledge any authorized agent can read
``history``     append-only record of results, decisions, errors, solutions

Anti-duplication & conflict strategy
------------------------------------
* Writes to ``individual``/``shared`` are **upserts keyed by
  (agent, scope, key)**: one canonical entry per key, with a monotonically
  increasing ``version`` counter.
* The previous version of every shared update is automatically archived
  into ``history``, so no information is silently lost.
* ``prune()`` caps per-key version history and drops entries older than
  the retention window, keeping the memory free of obsolete data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hive.config.settings import get_settings
from agent_hive.core.ids import new_id, now_iso
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Memory

SCOPES = (Memory.SCOPE_INDIVIDUAL, Memory.SCOPE_SHARED, Memory.SCOPE_HISTORY)


class MemoryError_(Exception):
    """Memory operation failure."""


class MemoryManager:
    """Stateless async service over the ``memories`` table."""

    # ------------------------------------------------------------------ write
    async def remember_individual(
        self,
        agent: str,
        key: str,
        value: dict[str, Any],
        tags: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> Memory:
        """Upsert a private memory entry for one agent (version bumped)."""
        return await self._upsert(
            agent=agent,
            scope=Memory.SCOPE_INDIVIDUAL,
            key=key,
            value=value,
            tags=tags,
            session=session,
        )

    async def share(
        self,
        key: str,
        value: dict[str, Any],
        author: str,
        tags: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> Memory:
        """Upsert a shared entry; the previous version is archived."""
        async def _write(sess: AsyncSession) -> Memory:
            existing = await MemoryManager._find_in(
                sess, None, Memory.SCOPE_SHARED, key
            )
            if existing is not None:
                await self._archive(sess, agent=author, key=key, value=existing.value)
                existing.value = value
                existing.version += 1
                existing.tags = tags or existing.tags
                await sess.flush()
                return existing
            entry = Memory(
                id=new_id(), agent_name=None, scope=Memory.SCOPE_SHARED,
                key=key, value=value, tags=tags or [], version=1,
            )
            sess.add(entry)
            await sess.flush()
            return entry

        return await self._run(_write, session)

    async def history_append(
        self,
        key: str,
        value: dict[str, Any],
        actor: str = "",
        tags: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> Memory:
        """Append-only write to the historical memory."""
        entry_key = f"{key}:{new_id()[:8]}"
        return await self._upsert(
            agent=None,
            scope=Memory.SCOPE_HISTORY,
            key=entry_key,
            value={**(value or {}), "actor": actor, "recorded_at": now_iso()},
            tags=tags,
            session=session,
        )

    # ------------------------------------------------------------------- read
    async def recall_individual(
        self, agent: str, key: str, session: AsyncSession | None = None
    ) -> Memory | None:
        return await self._find(agent=agent, scope=Memory.SCOPE_INDIVIDUAL, key=key, session=session)

    async def read_shared(
        self, key: str, session: AsyncSession | None = None
    ) -> Memory | None:
        return await self._find(agent=None, scope=Memory.SCOPE_SHARED, key=key, session=session)

    async def list_scope(
        self,
        scope: str,
        agent: str | None = None,
        limit: int = 200,
        session: AsyncSession | None = None,
    ) -> list[Memory]:
        async def _query(sess: AsyncSession) -> list[Memory]:
            stmt = select(Memory).where(Memory.scope == scope)
            if scope == Memory.SCOPE_INDIVIDUAL and agent:
                stmt = stmt.where(Memory.agent_name == agent)
            stmt = stmt.order_by(Memory.updated_at.desc()).limit(limit)
            return list((await sess.execute(stmt)).scalars())

        return await self._run(_query, session)

    async def search(
        self,
        query: str,
        scope: str | None = None,
        agent: str | None = None,
        limit: int = 25,
        session: AsyncSession | None = None,
    ) -> list[Memory]:
        """Substring search across memory contents (JSON-text matching)."""
        q = (query or "").lower()
        if not q:
            return []

        async def _query(sess: AsyncSession) -> list[Memory]:
            stmt = select(Memory)
            if scope:
                stmt = stmt.where(Memory.scope == scope)
            if scope == Memory.SCOPE_INDIVIDUAL and agent:
                stmt = stmt.where(Memory.agent_name == agent)
            stmt = stmt.order_by(Memory.updated_at.desc()).limit(1000)
            return list((await sess.execute(stmt)).scalars())

        rows = await self._run(_query, session)
        hits = [
            r for r in rows
            if q in r.key.lower() or q in json.dumps(r.value, ensure_ascii=False).lower()
        ]
        return hits[:limit]

    # ------------------------------------------------------------------ prune
    async def prune(
        self, session: AsyncSession | None = None
    ) -> dict[str, int]:
        """Remove obsolete memory: version caps + retention window."""
        settings = get_settings()
        cutoff = datetime.now(UTC) - timedelta(
            days=settings.memory_retention_days
        )

        async def _prune(sess: AsyncSession) -> dict[str, int]:
            removed_hist = await sess.execute(
                delete(Memory).where(
                    Memory.scope == Memory.SCOPE_HISTORY,
                    Memory.updated_at < cutoff,
                )
            )
            # Version cap: keep newest N history rows per logical key prefix
            hist = (await sess.execute(
                select(Memory)
                .where(Memory.scope == Memory.SCOPE_HISTORY)
                .order_by(Memory.key, Memory.updated_at.desc())
            )).scalars().all()
            seen: dict[str, int] = {}
            stale_ids: list[str] = []
            for row in hist:
                logical = row.key.split(":")[0]
                seen[logical] = seen.get(logical, 0) + 1
                if seen[logical] > settings.memory_max_versions:
                    stale_ids.append(row.id)
            removed_cap = 0
            if stale_ids:
                res = await sess.execute(
                    delete(Memory).where(Memory.id.in_(stale_ids))
                )
                removed_cap = res.rowcount or 0
            return {
                "history_expired": removed_hist.rowcount or 0,
                "history_capped": removed_cap,
            }

        return await self._run(_prune, session)

    # ---------------------------------------------------------------- helpers
    async def _find(
        self,
        agent: str | None,
        scope: str,
        key: str,
        session: AsyncSession | None = None,
    ) -> Memory | None:
        async def _query(sess: AsyncSession) -> Memory | None:
            return await self._find_in(sess, agent, scope, key)

        return await self._run(_query, session)

    @staticmethod
    async def _find_in(
        sess: AsyncSession, agent: str | None, scope: str, key: str
    ) -> Memory | None:
        stmt = select(Memory).where(
            Memory.agent_name.is_(None) if agent is None else Memory.agent_name == agent,
            Memory.scope == scope,
            Memory.key == key,
        )
        return (await sess.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _upsert(
        agent: str | None, scope: str, key: str,
        value: dict[str, Any], tags: list[str] | None,
        session: AsyncSession | None,
    ) -> Memory:
        async def _write(sess: AsyncSession) -> Memory:
            existing = await MemoryManager._find_in(sess, agent, scope, key)
            if existing is not None:
                existing.value = value
                existing.version += 1
                existing.tags = tags or existing.tags
                await sess.flush()
                return existing
            entry = Memory(
                id=new_id(), agent_name=agent, scope=scope,
                key=key, value=value, tags=tags or [], version=1,
            )
            sess.add(entry)
            await sess.flush()
            return entry

        return await MemoryManager._run(_write, session)

    @staticmethod
    async def _archive(
        sess: AsyncSession, agent: str, key: str, value: dict[str, Any]
    ) -> None:
        sess.add(Memory(
            id=new_id(), agent_name=None, scope=Memory.SCOPE_HISTORY,
            key=key, value={**value, "archived_from": agent}, version=1,
        ))

    @staticmethod
    async def _run(fn, session: AsyncSession | None):
        if session is not None:
            return await fn(session)
        factory = get_session_factory()
        async with factory() as sess:
            try:
                result = await fn(sess)
                await sess.commit()
                return result
            except IntegrityError as exc:
                await sess.rollback()
                raise MemoryError_(f"Memory constraint violation: {exc}") from exc
