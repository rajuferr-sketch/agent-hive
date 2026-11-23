"""Test environment bootstrap.

Environment variables are set *at import time*, before any ``agent_hive``
import, because :func:`agent_hive.config.settings.get_settings` is
``lru_cache``-d and :mod:`agent_hive.db.base` caches the async engine:
after the first import the environment is effectively frozen.

The whole suite runs without PostgreSQL, without network access and
without API keys: it uses a per-process temporary SQLite database and
the deterministic mock provider.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Per-process temp locations for DB, runtime data and the file-tool sandbox.
_TMP_ROOT = Path(tempfile.gettempdir()) / "agent_hive_tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
_DB_PATH = _TMP_ROOT / f"pytest_{os.getpid()}.db"
_DATA_DIR = _TMP_ROOT / f"data_{os.getpid()}"
_WORKSPACE_DIR = _TMP_ROOT / f"workspace_{os.getpid()}"

# --- must happen before agent_hive is imported anywhere --------------------
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["ALLOW_MOCK"] = "true"
os.environ["CONFIG_DIR"] = str(PROJECT_ROOT / "configs")
os.environ["DATA_DIR"] = str(_DATA_DIR)
os.environ["WORKSPACE_DIR"] = str(_WORKSPACE_DIR)
os.environ["ENABLE_FILE_TOOLS"] = "true"
os.environ["ENABLE_HTTP_TOOLS"] = "false"
# Speed: scheduler polling loop interval (mission e2e tests).
os.environ["SCHEDULER_INTERVAL"] = "0.05"
os.environ["HEARTBEAT_INTERVAL"] = "3600"

# A leftover DB from an aborted run would keep stale tables; start clean.
if _DB_PATH.exists():
    try:
        _DB_PATH.unlink()
    except OSError:
        pass

import pytest  # noqa: E402

from agent_hive.communication.bus import MessageBus  # noqa: E402
from agent_hive.core.events import EventBus  # noqa: E402
from agent_hive.db.base import create_all  # noqa: E402
from agent_hive.hive import Hive  # noqa: E402


@pytest.fixture(autouse=True)
async def _database():
    """Ensure the schema exists for every test (idempotent, cheap)."""
    await create_all()
    yield


@pytest.fixture
async def event_bus():
    """A plain in-process event bus (pump not started)."""
    return EventBus()


@pytest.fixture
async def hive():
    """A fully started in-process Hive, shut down after the test.

    The scheduler polls every 50 ms and the mission monitor polls every
    50 ms too, so end-to-end missions finish in well under a second
    (the mock provider is instantaneous).
    """
    import functools

    instance = Hive()
    instance.scheduler.poll_interval = 0.05
    instance.scheduler.wait_for_mission = functools.partial(
        instance.scheduler.wait_for_mission, poll_interval=0.05
    )
    await instance.startup()
    try:
        yield instance
    finally:
        await instance.shutdown()


@pytest.fixture
async def bus():
    """A message bus bound to the shared test database."""
    return MessageBus()

@pytest.fixture(autouse=True)
async def _clean_security_state():
    """After each test: purge tokens so the process returns to local-trust mode.

    Tests that exercise token flows issue and revoke within their own body;
    this guard keeps one test's state from leaking into the next (the
    security model switches to enforced mode as soon as an active token
    exists, which would otherwise change behaviour of later tests).
    """
    yield
    from sqlalchemy import delete

    from agent_hive.api.app import get_security
    from agent_hive.db.base import get_session_factory
    from agent_hive.db.models import ApiToken

    try:
        factory = get_session_factory()
        async with factory() as sess:
            await sess.execute(delete(ApiToken))
            await sess.commit()
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass
    try:
        get_security().invalidate_cache()
    except Exception:  # noqa: BLE001
        pass
