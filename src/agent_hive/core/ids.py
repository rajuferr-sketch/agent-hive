"""Identifier and timestamp helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id() -> str:
    """Return a URL-safe unique identifier."""
    return uuid.uuid4().hex


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()
