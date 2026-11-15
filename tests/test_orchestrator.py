"""Tests for the planner (analysis, mode selection, workstreams)
and the quality gate."""

from __future__ import annotations

import pytest

from agent_hive.config.loader import SystemConfig
from agent_hive.core.events import EventBus
from agent_hive.memory.manager import MemoryManager
from agent_hive.orchestrator.planner import (
    MODE_A,
    MODE_B,
    MODE_C,
    Analysis,
    analyze,
    choose_mode,
    plan_workstreams,
)
from agent_hive.orchestrator.quality import QualityGate

CONFIG = SystemConfig()


def _analysis(complexity: float) -> Analysis:
    return Analysis(complexity=complexity, domains=[], keywords=[], multi_part=False)


# ---------------------------------------------------------------- planner
def test_analyze_complexity_within_bounds() -> None:
    """Complexity is always clamped to [0.0, 1.0]."""
    for text in ("", "hi", "word " * 5000, "1. do this\n2. and then that"):
        assert 0.0 <= analyze(text, CONFIG).complexity <= 1.0


def test_analyze_detects_domains() -> None:
    """Domain keywords trigger the matching domain labels."""
    result = analyze("Design a database schema and write the SQL migration", CONFIG)
    assert "data" in result.domains

    result = analyze("Fix the authentication vulnerability", CONFIG)
    assert "security" in result.domains


def test_analyze_multi_part_detection() -> None:
    """Numbered lists are recognized as multi-part requests."""
    result = analyze("1. write tests\n2. run coverage\n3. deploy", CONFIG)
    assert result.multi_part is True


def test_choose_mode_thresholds() -> None:
    """complexity < simple → A, < adaptive → C, otherwise B."""
    assert choose_mode(_analysis(0.10), CONFIG) == MODE_A
    assert choose_mode(_analysis(0.40), CONFIG) == MODE_C
    assert choose_mode(_analysis(0.80), CONFIG) == MODE_B


def test_choose_mode_forced() -> None:
    """An explicit forced mode overrides the heuristic."""
    analysis = _analysis(0.10)
    assert choose_mode(analysis, CONFIG, forced="C") == MODE_C
    assert analysis.forced is True
    assert analysis.mode == MODE_C


def test_choose_mode_rejects_invalid_forced() -> None:
    """Unknown forced modes are a hard error."""
    with pytest.raises(ValueError, match="Invalid mode"):
        choose_mode(_analysis(0.10), CONFIG, forced="Z")


def test_plan_workstreams_mode_a_is_single_stream() -> None:
    """Mode A plans exactly one workstream."""
    analysis = analyze("Fix this one small bug", CONFIG)
    choose_mode(analysis, CONFIG, forced=MODE_A)
    streams = plan_workstreams(analysis, CONFIG)
    assert len(streams) == 1
    assert streams[0].capability


def test_plan_workstreams_collective_covers_domains() -> None:
    """Mode B/C plans one workstream per detected domain."""
    analysis = analyze(
        "database migration and frontend design with api contract", CONFIG
    )
    choose_mode(analysis, CONFIG, forced=MODE_B)
    streams = plan_workstreams(analysis, CONFIG)
    capabilities = {s.capability for s in streams}
    assert {"database", "frontend", "api"} <= capabilities


# ------------------------------------------------------------ quality gate
async def test_quality_gate_passes_good_deliverable() -> None:
    """A substantive deliverable covering the request scores >= threshold."""
    memory = MemoryManager()
    gate = QualityGate(CONFIG, memory, EventBus())
    title = "Design a caching layer"
    description = "Add a caching layer with invalidation"
    deliverable = (
        "The caching layer design: we add a caching layer in front of the "
        "service with TTL-based invalidation, a warm-up routine and clear "
        "metrics. The caching layer keeps memory bounds and evicts stale "
        "entries, and invalidation is broadcast cluster-wide."
    )
    report = await gate.verify(title, description, deliverable)
    assert report["passed"] is True
    assert report["score"] >= CONFIG.qa_required_score
    assert all(f["ok"] for f in report["findings"])


async def test_quality_gate_fails_on_broken_code_block() -> None:
    """Embedded python with a syntax error is caught by the code check."""
    memory = MemoryManager()
    gate = QualityGate(CONFIG, memory, EventBus())
    deliverable = "```python\ndef broken(:\n```"
    report = await gate.verify("code review", "", deliverable)
    code_findings = [f for f in report["findings"] if f["check"].startswith("code_block")]
    assert code_findings and code_findings[0]["ok"] is False
    assert report["score"] < 1.0
    assert report["passed"] is False  # too short AND broken code


async def test_quality_gate_fails_on_secret() -> None:
    """Hard-coded credentials make the deliverable fail even if long."""
    memory = MemoryManager()
    gate = QualityGate(CONFIG, memory, EventBus())
    title = "Publish configuration"
    deliverable = (
        "Publish configuration guide: configuration for the publish step "
        "is stored here.\napi_key = \"sk-1234567890abcdef12\"\n"
        "Share it with the team during onboarding and keep the service "
        "configuration documented."
    )
    report = await gate.verify(title, "", deliverable)
    secrets = [f for f in report["findings"] if f["check"] == "secrets"]
    assert secrets and secrets[0]["ok"] is False
    assert report["passed"] is False


async def test_quality_gate_flags_todo_markers() -> None:
    """TODO/placeholder markers reduce the score."""
    memory = MemoryManager()
    gate = QualityGate(CONFIG, memory, EventBus())
    deliverable = (
        "Here is the full implementation plan for the reporting feature, "
        "covering data collection, aggregation, storage and dashboards. "
        "TODO: finish the aggregation part."
    )
    report = await gate.verify("reporting feature", "", deliverable)
    markers = [f for f in report["findings"] if f["check"] == "markers"]
    assert markers and markers[0]["ok"] is False
    assert report["score"] < 1.0
