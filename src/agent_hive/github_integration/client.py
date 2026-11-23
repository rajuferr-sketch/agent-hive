"""GitHub integration client — repository operations with mode gating.

Four operating modes (``AGENT_HIVE_GITHUB_MODE`` or per-call override):

* ``read_only``       — reads only (repo info, branches, issues, PRs, search);
* ``assisted``        — reads + returns *plans* for writes without executing;
* ``semi_autonomous`` — executes non-destructive writes (branches, files,
  comments, issues, PRs); destructive ops (merge, delete) need explicit
  ``confirm=True``;
* ``autonomous``      — executes everything; merge still requires
  ``confirm=True`` as a hard safety net (never silently destructive).

Token hygiene: the token comes from ``GITHUB_TOKEN`` (env) and is never
logged; when the API reports insufficient scope via headers or 403, the
error distinguishes *token limitation* from *mode limitation* so the
operator knows exactly what to fix. Destructive or unexecuted-but-planned
operations raise :class:`ConfirmationRequired` / return a plan dict.

All HTTP goes through an injectable httpx client (``MockTransport`` in
tests), so the client itself is fully testable offline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.core.logging import get_logger

log = get_logger("agent_hive.github")

API_BASE = "https://api.github.com"

READ_ONLY = "read_only"
ASSISTED = "assisted"
SEMI_AUTONOMOUS = "semi_autonomous"
AUTONOMOUS = "autonomous"
MODES = (READ_ONLY, ASSISTED, SEMI_AUTONOMOUS, AUTONOMOUS)

# Severity-ranked pattern set for the built-in security scan.
SECRET_SCAN_RULES: tuple[tuple[str, str], ...] = (
    ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    ("openai-style-key", r"sk-[A-Za-z0-9_-]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("slack-token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("google-api-key", r"AIza[0-9A-Za-z_-]{30,}"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    ("private-key-header", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("hardcoded-password", r"(?i)(password|passwd)\s*=\s*[\"'][^\"']{8,}[\"']"),
)
DANGEROUS_CODE_RULES: tuple[tuple[str, str], ...] = (
    ("shell-true", r"(?i)shell\s*=\s*True"),
    ("eval-usage", r"(?<![\w.])eval\s*\("),
    ("yaml-unsafe-load", r"yaml\.load\((?![^)]*Loader)"),
    ("sql-format-string", r"(?i)execute\(\s*f[\"']"),
    ("verify-false-tls", r"verify\s*=\s*False"),
)


class ConfirmationRequired(AgentError):
    """A destructive operation needs explicit confirmation (confirm=True)."""


@dataclass(slots=True)
class OperationPlan:
    """What *would* be executed — returned in ``assisted`` mode."""

    operation: str
    params: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"planned": True, "operation": self.operation, "params": self.params}


class GitHubClient:
    """Thin async GitHub REST client with mode-based safety gates."""

    def __init__(
        self,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        mode: str | None = None,
        owner: str = "",
        repo: str = "",
    ) -> None:
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
        self.mode = mode or os.getenv("AGENT_HIVE_GITHUB_MODE", READ_ONLY)
        if self.mode not in MODES:
            raise PermissionDenied(
                f"github mode '{self.mode}' invalid; expected one of {MODES}"
            )
        self.owner = owner or os.getenv("GITHUB_OWNER", "")
        self.repo = repo or os.getenv("GITHUB_REPO", "")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._owns_client = client is None
        base = str((client.base_url if client else "") or "")
        # Injected transports (tests) may carry no base_url: fall back to the
        # absolute GitHub API base so relative paths still resolve.
        self._base_url = base.rstrip("/") if base.rstrip("/") not in ("", "http://") else API_BASE
        self._client = client or httpx.AsyncClient(
            base_url=API_BASE, headers=headers, timeout=30.0
        )
        self._scopes: list[str] = []

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------- internals
    def _require_write(self, operation: str, params: dict[str, Any],
                       destructive: bool = False) -> OperationPlan | None:
        """Mode gate. Returns a plan in assisted mode, None when allowed."""
        if self.mode == READ_ONLY:
            raise PermissionDenied(
                f"github mode is 'read_only': operation '{operation}' blocked"
            )
        plan = OperationPlan(operation, params)
        if self.mode == ASSISTED:
            return plan
        if destructive and self.mode in (SEMI_AUTONOMOUS, AUTONOMOUS) and not params.get("confirm"):
            raise ConfirmationRequired(
                f"operation '{operation}' is destructive — call again with "
                f"confirm=true to execute it"
            )
        return None

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        resp = await self._client.request(
            method, f"{self._base_url}{path}", json=json_body, params=params
        )
        scopes = resp.headers.get("x-oauth-scopes")
        if scopes:
            self._scopes = [s.strip() for s in scopes.split(",") if s.strip()]
        if resp.status_code == 403:
            raise PermissionDenied(
                "GitHub API forbidden — the current token lacks the required "
                f"scope for '{path}' (token scopes reported: "
                f"{self._scopes or 'unknown'}). This is a token limitation, "
                "not an AgentHive mode limitation."
            )
        if resp.status_code >= 400:
            raise AgentError(f"GitHub {method} {path} → {resp.status_code}: "
                             f"{resp.text[:200]}")
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def _full_repo(self) -> str:
        if not (self.owner and self.repo):
            raise AgentError("owner/repo not configured for the GitHub client")
        return f"{self.owner}/{self.repo}"

    @property
    def reported_scopes(self) -> list[str]:
        """OAuth scopes the API last reported for the current token."""
        return list(self._scopes)

    # ------------------------------------------------------------------ reads
    async def get_repository(self, owner: str = "", repo: str = "") -> dict[str, Any]:
        if not (owner or self.owner) or not (repo or self.repo):
            raise AgentError("owner/repo not configured for the GitHub client")
        return await self._request(
            "GET", f"/repos/{owner or self.owner}/{repo or self.repo}"
        )

    async def list_branches(self, owner: str = "", repo: str = "") -> list[dict[str, Any]]:
        if not (owner or self.owner) or not (repo or self.repo):
            raise AgentError("owner/repo not configured for the GitHub client")
        data: Any = await self._request(
            "GET", f"/repos/{owner or self.owner}/{repo or self.repo}/branches",
            params={"per_page": 100},
        )
        return [
            {"name": b.get("name"), "sha": (b.get("commit") or {}).get("sha")}
            for b in data if isinstance(b, dict)
        ]

    async def get_file(self, path: str, ref: str = "", owner: str = "", repo: str = "") -> dict[str, Any]:
        params: dict[str, Any] | None = {"ref": ref} if ref else None
        return await self._request(
            "GET",
            f"/repos/{owner or self.owner}/{repo or self.repo}/contents/{path}",
            params=params,
        )

    async def list_issues(self, state: str = "open", owner: str = "", repo: str = "") -> list[dict[str, Any]]:
        data: Any = await self._request(
            "GET", f"/repos/{owner or self.owner}/{repo or self.repo}/issues",
            params={"state": state, "per_page": 50},
        )
        return [i for i in data if isinstance(i, dict) and "pull_request" not in i]

    async def list_pull_requests(self, state: str = "open", owner: str = "", repo: str = "") -> list[dict[str, Any]]:
        data: Any = await self._request(
            "GET", f"/repos/{owner or self.owner}/{repo or self.repo}/pulls",
            params={"state": state, "per_page": 50},
        )
        return [p for p in data if isinstance(p, dict)]

    async def search_code(self, query: str) -> dict[str, Any]:
        return await self._request(
            "GET", "/search/code", params={"q": query, "per_page": 20}
        )

    # ----------------------------------------------------------------- writes
    async def create_branch(self, branch: str, from_branch: str = "main") -> dict[str, Any]:
        plan = self._require_write("create_branch", {"branch": branch})
        if plan:
            return plan.as_dict()
        full = self._full_repo()
        base = await self._request("GET", f"/repos/{full}/git/ref/heads/{from_branch}")
        sha = (base.get("object") or {}).get("sha")
        if not sha:
            raise AgentError(f"source branch '{from_branch}' not found")
        return await self._request(
            "POST", f"/repos/{full}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    async def commit_file(
        self, path: str, content: str, branch: str, message: str
    ) -> dict[str, Any]:
        plan = self._require_write("commit_file", {"path": path, "branch": branch})
        if plan:
            return plan.as_dict()
        full = self._full_repo()
        sha: str | None = None
        existing: Any = None
        try:
            existing = await self._request(
                "GET", f"/repos/{full}/contents/{path}", params={"ref": branch}
            )
            sha = existing.get("sha") if isinstance(existing, dict) else None
        except AgentError:
            sha = None  # new file
        return await self._request(
            "PUT", f"/repos/{full}/contents/{path}",
            json_body={
                "message": message, "content": _b64(content),
                "branch": branch, **({"sha": sha} if sha else {}),
            },
        )

    async def create_issue(self, title: str, body: str = "", labels: list[str] | None = None) -> dict[str, Any]:
        plan = self._require_write("create_issue", {"title": title})
        if plan:
            return plan.as_dict()
        return await self._request(
            "POST", f"/repos/{self._full_repo()}/issues",
            json_body={"title": title, "body": body, "labels": labels or []},
        )

    async def add_issue_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        plan = self._require_write("add_issue_comment", {"issue": issue_number})
        if plan:
            return plan.as_dict()
        return await self._request(
            "POST", f"/repos/{self._full_repo()}/issues/{issue_number}/comments",
            json_body={"body": body},
        )

    async def create_pull_request(
        self, title: str, head: str, base: str, body: str = ""
    ) -> dict[str, Any]:
        plan = self._require_write("create_pull_request", {"head": head, "base": base})
        if plan:
            return plan.as_dict()
        return await self._request(
            "POST", f"/repos/{self._full_repo()}/pulls",
            json_body={"title": title, "head": head, "base": base, "body": body},
        )

    async def review_pull_request(
        self, pr_number: int, event: str, body: str = ""
    ) -> dict[str, Any]:
        if event not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
            raise AgentError("event must be APPROVE|REQUEST_CHANGES|COMMENT")
        plan = self._require_write("review_pull_request", {"pr": pr_number, "event": event})
        if plan:
            return plan.as_dict()
        return await self._request(
            "POST", f"/repos/{self._full_repo()}/pulls/{pr_number}/reviews",
            json_body={"event": event, "body": body},
        )

    async def merge_pull_request(
        self, pr_number: int, method: str = "squash", confirm: bool = False
    ) -> dict[str, Any]:
        if method not in ("merge", "squash", "rebase"):
            raise AgentError("merge method must be merge|squash|rebase")
        plan = self._require_write(
            "merge_pull_request", {"pr": pr_number, "confirm": confirm},
            destructive=True,
        )
        if plan:
            return plan.as_dict()
        return await self._request(
            "PUT", f"/repos/{self._full_repo()}/pulls/{pr_number}/merge",
            json_body={"merge_method": method},
        )

    # ----------------------------------------------------------- security scan
    async def security_scan(self, files: dict[str, str]) -> dict[str, Any]:
        """Scan provided ``{path: content}`` for secrets & dangerous patterns.

        Runs locally (files never leave the process) — usable in every mode.
        """
        findings: list[dict[str, Any]] = []
        for path, content in files.items():
            for rule_name, pattern in SECRET_SCAN_RULES:
                for match in re.finditer(pattern, content or ""):
                    findings.append({
                        "file": path, "rule": rule_name,
                        "severity": "high", "kind": "secret",
                        "snippet": _snippet(content, match.start()),
                    })
            for rule_name, pattern in DANGEROUS_CODE_RULES:
                for match in re.finditer(pattern, content or ""):
                    findings.append({
                        "file": path, "rule": rule_name,
                        "severity": "medium", "kind": "dangerous_pattern",
                        "snippet": _snippet(content, match.start()),
                    })
        return {
            "scanned_files": len(files),
            "findings": findings,
            "clean": not findings,
            "summary": {
                "secrets": sum(1 for f in findings if f["kind"] == "secret"),
                "dangerous": sum(1 for f in findings if f["kind"] == "dangerous_pattern"),
            },
        }


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _snippet(content: str, position: int, width: int = 60) -> str:
    start = max(0, position - width // 2)
    return content[start:start + width].replace("\n", "\\n")[:width]
