"""Self-heal loop tests — bounded retries, budget, safe stop."""

from __future__ import annotations

import asyncio

from agent_hive.selfheal.loop import SelfHeal


async def test_healthy_cycle_reports_ok(hive) -> None:
    selfheal = SelfHeal(hive)
    report = await selfheal.run_cycle()
    assert report.healthy is True
    assert not report.budget_exceeded
    names = {c["check"] for c in report.checks}
    assert {"database", "scheduler", "agents", "universal_memory", "event_bus"} <= names


async def test_broken_check_triggers_remediation_then_recheck(hive) -> None:
    selfheal = SelfHeal(hive)
    # simulate a dead scheduler loop: the remediation restarts it
    hive.scheduler._loop_task = None
    report = await selfheal.run_cycle()
    assert any(c["check"] == "scheduler" for c in report.checks)
    assert report.remediations, "expected a remediation attempt"
    # after remediation the scheduler is alive again (recheck true)
    scheduler_entry = next(
        c for c in report.checks if c["check"] == "scheduler"
    )
    assert scheduler_entry.get("recheck") is True


async def test_remediation_retry_cap_is_respected(hive) -> None:
    selfheal = SelfHeal(hive)
    selfheal.max_retries = 2

    async def _always_broken() -> tuple[bool, str]:
        return False, "permanently broken"

    async def _failing_remedy() -> bool:
        return False

    selfheal._check_functions = lambda: [("database", _always_broken)]
    selfheal._remediation_for = lambda _check: _failing_remedy

    for _ in range(3):
        await selfheal.run_cycle()
    # after max_retries attempts the loop reports the cap instead of looping
    assert selfheal._remedy_counts["database"] == 2
    report = await selfheal.run_cycle()
    assert any("limit reached" in a for a in report.remediations)


async def test_consecutive_failures_trigger_safe_stop(hive) -> None:
    stopped = {"called": False}

    async def _safe_stop() -> None:
        stopped["called"] = True

    selfheal = SelfHeal(hive, safe_stop=_safe_stop)
    selfheal.fail_limit = 3
    selfheal.interval = 0.01

    async def _always_broken() -> tuple[bool, str]:
        return False, "broken forever"

    selfheal._check_functions = lambda: [("database", _always_broken)]
    selfheal._remediation_for = lambda _check: None  # nothing helps

    selfheal.start()
    try:
        for _ in range(60):
            if stopped["called"]:
                break
            await asyncio.sleep(0.05)
        assert stopped["called"], "safe stop never fired"
        assert selfheal.safe_stop_triggered is True
        # the loop returns after safe stop — no further cycles run
        cycles_before = selfheal._cycle
        await asyncio.sleep(0.1)
        assert selfheal._cycle == cycles_before
    finally:
        await selfheal.stop()


async def test_budget_prevents_unbounded_checks(hive) -> None:
    selfheal = SelfHeal(hive)
    selfheal.budget_s = 0.05  # tiny budget

    async def _slow_check() -> tuple[bool, str]:
        await asyncio.sleep(0.2)
        return True, "slow"

    selfheal._check_functions = lambda: [
        ("slow_one", _slow_check),
        ("slow_two", _slow_check),
        ("slow_three", _slow_check),
    ]
    report = await selfheal.run_cycle()
    assert report.budget_exceeded is True
    assert len(report.checks) < 3  # budget cut the remaining checks


async def test_disabled_selfheal_never_starts(hive) -> None:
    hive.settings.selfheal_enabled = False
    selfheal = SelfHeal(hive)
    selfheal.start()
    assert selfheal._task is None  # no background loop created
    hive.settings.selfheal_enabled = True
