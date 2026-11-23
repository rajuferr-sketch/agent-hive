"""Universal Shared Memory — cross-client persistent knowledge store.

The defining property: **any** AI client that reaches AgentHive (MCP,
OpenAI-compatible, Ollama-compatible, REST, WebSocket) reads and writes
the *same* durable store, so work started with one client can be picked
up later by another (create task with Claude Desktop → executed by the
hive → results stored → ChatGPT resumes hours later from shared memory).

Memory types
------------
``episodic``      what happened and when (events, interactions, results)
``semantic``      durable facts and knowledge (project concepts, definitions)
``operational``   how-to knowledge (procedures, environment, settings)
``task``          task lifecycle records (created/assigned/completed...)
``decision``      decisions with rationale and alternatives considered

Isolation
---------
Records are namespaced by ``(user_id, project_id, session_id)``; the
``access`` column widens visibility: ``private`` (owning user only),
``project`` (any client of the same project), ``public`` (everyone).
Cross-client sharing is therefore explicit, not accidental.

Retrieval
---------
* full-text: case-insensitive substring match on key/content/tags;
* vector: 128-dim hashed bag-of-words embeddings compared by cosine
  similarity (dependency-free; swap with a real embedder later — the
  schema already stores arbitrary vectors);
* blended ranking with configurable weights.

Hygiene
-------
* dedup: identical content (same content hash) does not bump the version;
* versioning: every real change increments ``version``;
* TTL: per-record ``ttl_seconds`` → ``expires_at``; ``purge_expired``
  removes stale rows (called by the gateway and diagnostics).
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import AgentError
from agent_hive.core.ids import new_id
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import UniversalMemory as UMem
from agent_hive.security.sanitize import sanitize_input

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


def _hash_embedding(text: str, dims: int) -> list[float]:
    """Deterministic hashed bag-of-words vector (dependency-free).

    Each token is hashed into ``dims`` buckets with a sign trick, then the
    vector is L2-normalised. Good enough for similarity ranking; a real
    embedding model can replace it without schema changes.
    """
    vec = [0.0] * dims
    for token in _WORD_RE.findall((text or "").lower()):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if (digest[4] & 1) else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def _content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class UniversalMemoryError(AgentError):
    """Universal memory operation failure."""


class UniversalMemoryManager:
    """Async service over the ``universal_memory`` table."""

    def __init__(self) -> None:
        self._fts_weight = 0.6
        self._vector_weight = 0.4

    # ------------------------------------------------------------------ write
    async def save(
        self,
        *,
        memory_type: str,
        key: str,
        content: str,
        value: dict[str, Any] | None = None,
        user_id: str = "default",
        project_id: str = "default",
        session_id: str = "global",
        tags: list[str] | None = None,
        access: str = UMem.ACCESS_PROJECT,
        ttl_seconds: int | None = None,
        created_by_client: str = "",
    ) -> dict[str, Any]:
        """Upsert one record (version bump on real change; dedup identical)."""
        if memory_type not in UMem.ALL_TYPES:
            raise UniversalMemoryError(
                f"memory_type must be one of {sorted(UMem.ALL_TYPES)}"
            )
        if access not in (UMem.ACCESS_PRIVATE, UMem.ACCESS_PROJECT, UMem.ACCESS_PUBLIC):
            raise UniversalMemoryError("access must be private|project|public")
        key = (key or "").strip()[:256]
        if not key:
            raise UniversalMemoryError("key is required")
        content = str(content or "")[:100_000]
        settings = get_settings()
        ttl = settings.universal_memory_ttl_default if ttl_seconds is None else max(0, ttl_seconds)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl) if ttl > 0 else None
        )
        clean_tags = [str(t)[:64] for t in (tags or [])][:32]
        safe_value = sanitize_input(value or {})
        chash = _content_hash(content)

        async def _write(sess: AsyncSession) -> dict[str, Any]:
            existing = (
                await sess.execute(
                    select(UMem).where(
                        UMem.user_id == user_id,
                        UMem.project_id == project_id,
                        UMem.session_id == session_id,
                        UMem.memory_type == memory_type,
                        UMem.key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if _content_hash(existing.content) == chash and (
                    existing.value == safe_value
                ):
                    # dedup: identical payload → touch metadata only
                    existing.created_by_client = created_by_client or existing.created_by_client
                    await sess.flush()
                    return self._dump(existing, deduplicated=True)
                existing.content = content
                existing.value = safe_value
                existing.tags = clean_tags or existing.tags
                existing.embedding = _hash_embedding(
                    f"{key} {content}", settings.universal_memory_dims
                )
                existing.content_hash = chash
                existing.version += 1
                existing.access = access
                existing.ttl_seconds = ttl or None
                existing.expires_at = expires_at
                existing.created_by_client = created_by_client or existing.created_by_client
                await sess.flush()
                return self._dump(existing)
            row = UMem(
                id=new_id(),
                user_id=user_id,
                project_id=project_id,
                session_id=session_id,
                memory_type=memory_type,
                key=key,
                content=content,
                value=safe_value,
                tags=clean_tags,
                embedding=_hash_embedding(f"{key} {content}", settings.universal_memory_dims),
                content_hash=chash,
                access=access,
                ttl_seconds=ttl or None,
                expires_at=expires_at,
                created_by_client=created_by_client,
            )
            sess.add(row)
            try:
                await sess.flush()
            except IntegrityError as exc:
                await sess.rollback()
                raise UniversalMemoryError(f"memory constraint violation: {exc}") from exc
            return self._dump(row)

        return await self._run(_write)

    async def update(
        self,
        *,
        memory_id: str | None = None,
        key: str | None = None,
        content: str,
        value: dict[str, Any] | None = None,
        user_id: str = "default",
        project_id: str = "default",
        session_id: str = "global",
        memory_type: str | None = None,
        tags: list[str] | None = None,
        created_by_client: str = "",
    ) -> dict[str, Any]:
        """Update an existing record (by id or namespaced key)."""
        async def _write(sess: AsyncSession) -> dict[str, Any]:
            row = await self._locate(
                sess, memory_id=memory_id, key=key, memory_type=memory_type,
                user_id=user_id, project_id=project_id, session_id=session_id,
            )
            assert row is not None  # required=True guarantees a row
            new_hash = _content_hash(content)
            if _content_hash(row.content) == new_hash and (
                row.value == sanitize_input(value or {})
            ):
                return self._dump(row, deduplicated=True)
            row.content = content[:100_000]
            if value is not None:
                row.value = sanitize_input(value)
            if tags is not None:
                row.tags = [str(t)[:64] for t in tags][:32]
            row.content_hash = new_hash
            row.version += 1
            row.created_by_client = created_by_client or row.created_by_client
            settings = get_settings()
            row.embedding = _hash_embedding(
                f"{row.key} {row.content}", settings.universal_memory_dims
            )
            await sess.flush()
            return self._dump(row)

        return await self._run(_write)

    # ------------------------------------------------------------------- read
    async def get(
        self,
        *,
        memory_id: str | None = None,
        key: str | None = None,
        memory_type: str | None = None,
        user_id: str = "default",
        project_id: str = "default",
        session_id: str = "global",
    ) -> dict[str, Any] | None:
        async def _read(sess: AsyncSession) -> dict[str, Any] | None:
            row = await self._locate(
                sess, memory_id=memory_id, key=key, memory_type=memory_type,
                user_id=user_id, project_id=project_id, session_id=session_id,
                required=False,
            )
            return self._dump(row) if row else None

        return await self._run(_read)

    async def list_records(
        self,
        *,
        memory_type: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async def _read(sess: AsyncSession) -> list[dict[str, Any]]:
            stmt = select(UMem)
            if memory_type:
                stmt = stmt.where(UMem.memory_type == memory_type)
            if user_id:
                stmt = stmt.where(UMem.user_id == user_id)
            if project_id:
                stmt = stmt.where(UMem.project_id == project_id)
            if session_id:
                stmt = stmt.where(UMem.session_id == session_id)
            stmt = stmt.order_by(UMem.updated_at.desc()).limit(min(limit, 500))
            return [self._dump(r) for r in (await sess.execute(stmt)).scalars()]

        return await self._run(_read)

    async def search(
        self,
        query: str,
        *,
        memory_type: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Blended full-text + vector search (full-text anchored on query)."""
        q = (query or "").strip()
        if not q:
            return []
        settings = get_settings()
        qvec = _hash_embedding(q, settings.universal_memory_dims)
        qlow = q.lower()

        async def _read(sess: AsyncSession) -> list[dict[str, Any]]:
            stmt = select(UMem)
            if memory_type:
                stmt = stmt.where(UMem.memory_type == memory_type)
            if user_id:
                stmt = stmt.where(UMem.user_id == user_id)
            if project_id:
                stmt = stmt.where(UMem.project_id == project_id)
            if session_id:
                stmt = stmt.where(UMem.session_id == session_id)
            stmt = stmt.order_by(UMem.updated_at.desc()).limit(1000)
            rows = list((await sess.execute(stmt)).scalars())
            scored: list[tuple[float, UMem]] = []
            for row in rows:
                fts = 0.0
                if qlow in row.key.lower() or qlow in row.content.lower():
                    fts = 1.0
                else:
                    hay = (
                        row.key.lower() + " " + row.content.lower() + " "
                        + " ".join(map(str, row.tags or [])).lower()
                    )
                    tokens = [t.lower() for t in _WORD_RE.findall(q)]
                    if tokens:
                        overlap = sum(1 for t in tokens if t in hay) / len(tokens)
                        fts = overlap * 0.8
                vec = _cosine(qvec, list(row.embedding or []))
                score = self._fts_weight * fts + self._vector_weight * vec
                if score > 0.05:
                    scored.append((score, row))
            scored.sort(key=lambda x: -x[0])
            return [self._dump(row, score=round(s, 4)) for s, row in scored[:limit]]

        return await self._run(_read)

    async def history(
        self,
        *,
        key: str | None = None,
        memory_type: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Version history: rows sorted newest-first, optionally by key prefix."""
        async def _read(sess: AsyncSession) -> list[dict[str, Any]]:
            stmt = select(UMem)
            if key:
                stmt = stmt.where(UMem.key.like(f"{key}%"))
            if memory_type:
                stmt = stmt.where(UMem.memory_type == memory_type)
            if user_id:
                stmt = stmt.where(UMem.user_id == user_id)
            if project_id:
                stmt = stmt.where(UMem.project_id == project_id)
            if session_id:
                stmt = stmt.where(UMem.session_id == session_id)
            stmt = stmt.order_by(UMem.updated_at.desc()).limit(min(limit, 500))
            return [self._dump(r) for r in (await sess.execute(stmt)).scalars()]

        return await self._run(_read)

    # ------------------------------------------------------------------ stats
    async def stats(self) -> dict[str, Any]:
        async def _read(sess: AsyncSession) -> dict[str, Any]:
            by_type = {
                t: int(c)
                for t, c in (
                    await sess.execute(
                        select(UMem.memory_type, func.count(UMem.id)).group_by(UMem.memory_type)
                    )
                ).all()
            }
            total = int(
                (await sess.execute(select(func.count(UMem.id)))).scalar_one()
            )
            return {"total": total, "by_type": by_type}

        return await self._run(_read)

    # -------------------------------------------------------------------- TTL
    async def purge_expired(self) -> int:
        async def _purge(sess: AsyncSession) -> int:
            now = datetime.now(timezone.utc)
            res = await sess.execute(
                delete(UMem).where(UMem.expires_at.is_not(None), UMem.expires_at < now)
            )
            await sess.commit()
            return int(getattr(res, "rowcount", 0) or 0)

        return await self._run(_purge)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _dump(row: UMem, score: float | None = None, deduplicated: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": row.id,
            "user_id": row.user_id,
            "project_id": row.project_id,
            "session_id": row.session_id,
            "memory_type": row.memory_type,
            "key": row.key,
            "content": row.content,
            "value": row.value,
            "tags": list(row.tags or []),
            "version": row.version,
            "access": row.access,
            "ttl_seconds": row.ttl_seconds,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "created_by_client": row.created_by_client,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if score is not None:
            out["score"] = score
        if deduplicated:
            out["deduplicated"] = True
        return out

    @staticmethod
    async def _locate(
        sess: AsyncSession,
        *,
        memory_id: str | None,
        key: str | None,
        memory_type: str | None,
        user_id: str,
        project_id: str,
        session_id: str,
        required: bool = True,
    ) -> UMem | None:
        if memory_id:
            row = (
                await sess.execute(select(UMem).where(UMem.id == memory_id))
            ).scalar_one_or_none()
        elif key:
            stmt = select(UMem).where(
                UMem.user_id == user_id,
                UMem.project_id == project_id,
                UMem.session_id == session_id,
                UMem.key == key,
            )
            if memory_type:
                stmt = stmt.where(UMem.memory_type == memory_type)
            row = (await sess.execute(stmt)).scalar_one_or_none()
        else:
            raise UniversalMemoryError("memory_id or key is required")
        if row is None and required:
            raise UniversalMemoryError("Memory record not found")
        return row

    @staticmethod
    async def _run(fn):
        factory = get_session_factory()
        async with factory() as sess:
            try:
                result = await fn(sess)
                await sess.commit()
                return result
            except IntegrityError as exc:
                await sess.rollback()
                raise UniversalMemoryError(
                    f"Memory constraint violation: {exc}"
                ) from exc
            except UniversalMemoryError:
                raise
            except Exception as exc:
                await sess.rollback()
                raise UniversalMemoryError(f"Memory operation failed: {exc}") from exc
