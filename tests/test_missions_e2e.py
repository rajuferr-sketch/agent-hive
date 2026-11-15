"""End-to-end mission tests: full Hive startup with the mock provider,
mission execution through the scheduler, integration and quality gate."""

from __future__ import annotations

import asyncio

from agent_hive.db.models import Task
from agent_hive.hive import Hive

MISSION_TIMEOUT = 90.0  # safety net: mock missions finish in well under a second


async def _run_mission(hive: Hive, text: str, mode: str) -> dict:
    return await asyncio.wait_for(
        hive.run_mission(text, mode=mode), timeout=MISSION_TIMEOUT
    )


async def test_mission_mode_a_completes_with_quality_report(hive: Hive) -> None:
    """A simple (mode A) mission runs one agent and passes the quality gate."""
    report = await _run_mission(
        hive, "Write a short haiku about automated testing in Python", mode="A"
    )

    assert report["mode"] == "A"
    assert report["mission_id"]
    assert report["deliverable"].strip(), "deliverable must not be empty"
    assert report["quality"], "a quality report must be attached"
    assert "passed" in report["quality"] and "score" in report["quality"]
    assert 0.0 <= report["quality"]["score"] <= 1.0

    # Every mission task reached a terminal status.
    tasks = await hive.tasks.list(mission_id=report["mission_id"], limit=200)
    assert tasks, "mode A missions must create at least one task"
    assert all(t.status in Task.TERMINAL_STATUSES for t in tasks)
    assert any(t.status == Task.STATUS_COMPLETED for t in tasks)
    assert report["outcome"]["completed"] == len(tasks)

    # Memory: the mission final verdict is recorded in history.
    hits = await hive.memory.search("mission_final", scope="history")
    assert any(
        h.value.get("mission_id") == report["mission_id"] for h in hits
    ), "mission_final must be appended to historical memory"

    # Message bus: the master broadcast the mission kickoff.
    master_messages = await hive.bus.history(agent="master")
    assert any(
        m.from_agent == "master" and m.to_agent == "*" for m in master_messages
    ), "the master must broadcast the mission kickoff"


async def test_mission_mode_c_completes_full_pipeline(hive: Hive) -> None:
    """A moderately complex (mode C) mission runs the adaptive pipeline."""
    text = (
        "Design a complete database schema for a small online shop and then "
        "write the documentation for it. Also describe the api endpoint list. "
        "The whole system must be tested."
    )
    report = await _run_mission(hive, text, mode="C")

    assert report["mode"] == "C"
    assert report["deliverable"].strip()
    assert "passed" in report["quality"] and "score" in report["quality"]

    tasks = await hive.tasks.list(mission_id=report["mission_id"], limit=200)
    assert len(tasks) >= 3, "mode C needs workstreams plus the pipeline stages"
    assert all(t.status in Task.TERMINAL_STATUSES for t in tasks), (
        "every task must terminate: "
        + ", ".join(f"{t.title}={t.status}" for t in tasks)
    )
    titles = {t.title for t in tasks}
    assert "Integrate contributions" in titles
    assert "Quality assurance review" in titles
    assert "Final validation" in titles


async def test_hive_status_snapshot(hive: Hive) -> None:
    """The status snapshot reports the running system accurately."""
    status = hive.status()
    assert status["agents_loaded"] == 20
    assert status["mock_allowed"] is True
    assert status["database"] == "sqlite+aiosqlite"
    assert 0 < status["config"]["simple_threshold"] < 1
