"""Tests for built-in tools and the permission-controlled registry."""

from __future__ import annotations

import pytest

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.tools import builtin
from agent_hive.tools.registry import REGISTRY


async def test_summarize_produces_text() -> None:
    """summarize returns a non-empty extractive summary."""
    text = (
        "The database migration failed because of a locked table. "
        "Engineers restarted the service to clear the lock. "
        "Afterwards the migration was retried and completed successfully. "
        "A post-mortem documented the incident for the team. "
        "Monitoring now alerts on table locks."
    )
    result = await builtin.summarize(text, max_sentences=2)
    assert result["summary"]
    assert result["sentences"] == 5
    summary_sentences = [s for s in result["summary"].split(". ") if s]
    assert 1 <= len(summary_sentences) <= 2
    assert all(s in text for s in summary_sentences)


async def test_json_validate_valid_and_invalid() -> None:
    """json_validate parses objects and reports parse failures."""
    ok = await builtin.json_validate('{"alpha": 1, "beta": [2, 3]}')
    assert ok["valid"] is True
    assert ok["data"] == {"alpha": 1, "beta": [2, 3]}

    bad = await builtin.json_validate("this is {not json")
    assert bad["valid"] is False
    assert "error" in bad


async def test_code_lint_py_valid_code() -> None:
    """Syntactically valid Python passes the static lint."""
    code = "import math\n\n\ndef area(radius: float) -> float:\n    return math.pi * radius ** 2\n"
    report = await builtin.code_lint_py(code)
    assert report["valid"] is True
    assert "area" in report["functions"]
    assert "math" in report["imports"]


async def test_code_lint_py_syntax_error() -> None:
    """A syntax error fails the lint with a line number."""
    report = await builtin.code_lint_py("def broken(:\n    pass\n")
    assert report["valid"] is False
    assert "error" in report and "line" in report["error"]


async def test_secret_scan_detects_hardcoded_api_key() -> None:
    """Hard-coded API keys are detected and redacted."""
    result = await builtin.secret_scan('config = dict(api_key = "sk-1234567890abcdef12")')
    assert result["clean"] is False
    assert result["findings"], "at least one pattern must match"
    preview = result["findings"][0]["preview"]
    assert "sk-1234567890abcdef12" not in preview, "preview must be redacted"


async def test_secret_scan_clean_text() -> None:
    """Ordinary prose contains no secrets."""
    result = await builtin.secret_scan("Nothing sensitive to see here.")
    assert result["clean"] is True
    assert result["findings"] == []


async def test_word_count_and_regex_extract() -> None:
    """Other text tools return the expected statistics."""
    stats = await builtin.word_count("one two three\nfour")
    assert stats == {"words": 4, "chars": 18, "lines": 2}

    found = await builtin.regex_extract(r"\d+", "a1 b22 c333")
    assert found["count"] == 3 and found["matches"] == ["1", "22", "333"]


async def test_registry_denies_unlisted_tool() -> None:
    """A tool outside the agent's allowed list raises PermissionDenied."""
    with pytest.raises(PermissionDenied, match="not authorized"):
        await REGISTRY.run("rogue-agent", ["summarize"], "secret_scan", text="x")


async def test_registry_denies_unknown_tool() -> None:
    """Unknown tool names are also permission errors."""
    with pytest.raises(PermissionDenied, match="Unknown tool"):
        await REGISTRY.run("agent", ["summarize", "does_not_exist"], "does_not_exist")


async def test_file_tools_blocked_when_disabled(monkeypatch) -> None:
    """The global ENABLE_FILE_TOOLS switch gates the whole file family."""
    monkeypatch.setattr(get_settings(), "enable_file_tools", False)
    with pytest.raises(PermissionDenied, match="File tools are disabled"):
        await REGISTRY.run(
            "agent", ["file_write"], "file_write", path="x.txt", content="hi"
        )


async def test_file_write_read_roundtrip_in_sandbox() -> None:
    """file_write + file_read round-trip inside the workspace."""
    token = "roundtrip-content"
    written = await REGISTRY.run(
        "agent", ["file_write", "file_read"], "file_write",
        path="sandbox_tests/hello.txt", content=token,
    )
    assert written["written"] is True
    assert written["size"] == len(token)

    read = await REGISTRY.run(
        "agent", ["file_write", "file_read"], "file_read",
        path="sandbox_tests/hello.txt",
    )
    assert read["content"] == token
    assert read["size"] == len(token)


async def test_path_escaping_is_blocked() -> None:
    """Relative paths leaving the workspace sandbox raise AgentError."""
    for path in ("../escape.txt", "sub/../../escape.txt"):
        with pytest.raises(AgentError, match="escapes the workspace"):
            await builtin.file_write(path, "boom")
        with pytest.raises(AgentError, match="escapes the workspace"):
            await builtin.file_read(path)


async def test_file_read_missing_file() -> None:
    """Reading a nonexistent sandbox file raises AgentError."""
    with pytest.raises(AgentError, match="File not found"):
        await builtin.file_read("definitely_missing_file.txt")
