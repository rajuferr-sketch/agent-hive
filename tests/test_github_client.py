"""GitHub integration tests — mode gates, operations, security scan.

All HTTP is served by an ``httpx.MockTransport``, so the client logic is
tested offline and deterministically.
"""

from __future__ import annotations

import httpx
import pytest

from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.github_integration.client import (
    ASSISTED,
    AUTONOMOUS,
    READ_ONLY,
    SEMI_AUTONOMOUS,
    ConfirmationRequired,
    GitHubClient,
)


def _mock_handler(
    routes: dict[tuple[str, str], object],
    calls: list[str] | None = None,
    scopes: str = "repo, workflow",
):
    """Build a mock transport with literal route responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if calls is not None:
            calls.append(f"{request.method} {request.url.path}")
        if key not in routes:
            return httpx.Response(404, json={"message": "not found"})
        payload = routes[key]
        headers = {"x-oauth-scopes": scopes}
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, int):  # status-code-only response
            return httpx.Response(payload, headers=headers)
        return httpx.Response(200, json=payload, headers=headers)

    return httpx.MockTransport(handler)


def _client(mode: str, routes, calls=None, token: str = "ghs_testtoken"):
    transport = _mock_handler(routes, calls)
    return GitHubClient(
        token=token, mode=mode, owner="octo", repo="hive",
        client=httpx.AsyncClient(transport=transport, base_url="https://api.github.com"),
    )


ROUTES = {
    ("GET", "/repos/octo/hive"): {
        "full_name": "octo/hive", "private": False, "default_branch": "main",
    },
    ("GET", "/repos/octo/hive/branches"): [
        {"name": "main", "commit": {"sha": "abc123"}},
        {"name": "feat/x", "commit": {"sha": "def456"}},
    ],
    ("GET", "/repos/octo/hive/git/ref/heads/main"): {
        "object": {"sha": "abc123", "type": "commit"},
    },
    ("POST", "/repos/octo/hive/git/refs"): {"ref": "refs/heads/feat/new"},
    ("GET", "/repos/octo/hive/issues"): [
        {"number": 1, "title": "bug", "state": "open"},
        {"number": 2, "title": "pr", "state": "open", "pull_request": {}},
    ],
    ("GET", "/repos/octo/hive/pulls"): [
        {"number": 7, "title": "Add gateway", "state": "open"},
    ],
    ("POST", "/repos/octo/hive/issues"): {"number": 3, "title": "New"},
    ("POST", "/repos/octo/hive/issues/3/comments"): {"id": 99},
    ("POST", "/repos/octo/hive/pulls"): {"number": 8, "title": "T"},
    ("POST", "/repos/octo/hive/pulls/8/reviews"): {"id": 1},
    ("PUT", "/repos/octo/hive/pulls/8/merge"): {"merged": True},
    ("GET", "/repos/octo/hive/contents/README.md"): {
        "sha": "filesha", "content": "aGVsbG8=", "path": "README.md",
    },
    ("PUT", "/repos/octo/hive/contents/README.md"): {
        "commit": {"sha": "newcommit"}, "path": "README.md",
    },
    ("GET", "/search/code"): {"total_count": 0, "items": []},
}


# ------------------------------------------------------------------- reads


async def test_read_operations_work_in_every_mode() -> None:
    for mode in (READ_ONLY, ASSISTED, SEMI_AUTONOMOUS, AUTONOMOUS):
        client = _client(mode, ROUTES)
        try:
            repo = await client.get_repository()
            assert repo["full_name"] == "octo/hive"
            branches = await client.list_branches()
            assert {b["name"] for b in branches} >= {"main", "feat/x"}
            issues = await client.list_issues()
            assert all("pull_request" not in i for i in issues)
            pulls = await client.list_pull_requests()
            assert pulls[0]["number"] == 7
            assert client.reported_scopes == ["repo", "workflow"]
        finally:
            await client.aclose()


# ---------------------------------------------------------------- mode gates


async def test_read_only_blocks_writes() -> None:
    client = _client(READ_ONLY, ROUTES)
    with pytest.raises(PermissionDenied, match="read_only"):
        await client.create_branch("feat/blocked")
    with pytest.raises(PermissionDenied, match="read_only"):
        await client.create_issue("t")
    await client.aclose()


async def test_assisted_returns_plans_without_executing() -> None:
    calls: list[str] = []
    client = _client(ASSISTED, ROUTES, calls)
    plan = await client.create_branch("feat/planned")
    assert plan == {
        "planned": True, "operation": "create_branch",
        "params": {"branch": "feat/planned"},
    }
    assert calls == []  # nothing was executed
    await client.aclose()


async def test_semi_autonomous_executes_safe_writes() -> None:
    calls: list[str] = []
    client = _client(SEMI_AUTONOMOUS, ROUTES, calls)
    result = await client.create_branch("feat/real")
    assert result["ref"] == "refs/heads/feat/new"
    assert any("git/refs" in c for c in calls)
    await client.aclose()


async def test_merge_requires_explicit_confirmation() -> None:
    for mode in (SEMI_AUTONOMOUS, AUTONOMOUS):
        client = _client(mode, ROUTES)
        with pytest.raises(ConfirmationRequired):
            await client.merge_pull_request(8)
        result = await client.merge_pull_request(8, confirm=True)
        assert result["merged"] is True
        await client.aclose()


async def test_bad_mode_rejected_at_construction() -> None:
    with pytest.raises(PermissionDenied):
        GitHubClient(token="t", mode="yolo")


# ----------------------------------------------------------------- operations


async def test_commit_file_updates_existing_sha() -> None:
    calls: list[str] = []
    client = _client(AUTONOMOUS, ROUTES, calls)
    result = await client.commit_file("README.md", "# hello", "main", "docs: hello")
    assert result["commit"]["sha"] == "newcommit"
    put_call = [c for c in calls if c.startswith("PUT")][0]
    assert put_call.endswith("/contents/README.md")
    await client.aclose()


async def test_create_pull_request_flow() -> None:
    client = _client(SEMI_AUTONOMOUS, ROUTES)
    pr = await client.create_pull_request("T", "feat/real", "main", "body")
    assert pr["number"] == 8
    review = await client.review_pull_request(8, "APPROVE", "lgtm")
    assert review["id"] == 1
    with pytest.raises(AgentError):
        await client.review_pull_request(8, "NUKE")
    await client.aclose()


async def test_owner_repo_required() -> None:
    transport = _mock_handler({})
    client = GitHubClient(token="t", owner="", repo="",
                          client=httpx.AsyncClient(transport=transport))
    with pytest.raises(AgentError, match="owner/repo"):
        await client.get_repository()
    await client.aclose()


async def test_403_reports_token_scope_limitation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"},
                              headers={"x-oauth-scopes": "read:user"})

    client = GitHubClient(
        token="t", mode=AUTONOMOUS, owner="o", repo="r",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PermissionDenied, match="token limitation"):
        await client.create_branch("x")
    await client.aclose()


# -------------------------------------------------------------- security scan


async def test_security_scan_finds_secrets_and_dangerous_code() -> None:
    client = _client(READ_ONLY, {})
    openai_key = "sk-" + "b2C3" * 6
    aws_key = "AKIA" + "7" * 16
    files = {
        "good.py": "def add(a, b):\n    return a + b\n",
        "leak.py": f'API_KEY = "{openai_key}"\n',
        "danger.py": "import yaml\nyaml.load(cfg)\nrequests.get(url, verify=False)\n",
        "aws.py": f"AWS_ACCESS_KEY = {aws_key}\n",
    }
    report = await client.security_scan(files)
    assert report["scanned_files"] == 4
    assert not report["clean"]
    assert report["summary"]["secrets"] >= 2
    rules = {f["rule"] for f in report["findings"]}
    assert {"openai-style-key", "aws-access-key", "yaml-unsafe-load",
            "verify-false-tls"} <= rules
    for finding in report["findings"]:
        assert "\n" not in finding["snippet"]
        assert len(finding["snippet"]) <= 60


async def test_security_scan_clean_project_passes() -> None:
    client = _client(READ_ONLY, {})
    report = await client.security_scan({"clean.py": "print('hello')\n"})
    assert report["clean"] is True
    await client.aclose()
