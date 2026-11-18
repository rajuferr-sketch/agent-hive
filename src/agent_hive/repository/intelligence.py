"""Repository Intelligence Engine — import and analyse a GitHub repository."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_hive.core.errors import AgentError


async def import_github_repo(url: str, dest_dir: str | None = None) -> dict[str, Any]:
    """Download a public GitHub repository as a ZIP and extract it."""
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc:
        raise AgentError("Only github.com URLs are supported")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise AgentError("URL must be https://github.com/<owner>/<repo>")
    owner, repo = parts[0], parts[1].replace(".git", "")
    branch = parts[3] if len(parts) >= 4 and parts[2] == "tree" else "main"
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"

    dest = Path(dest_dir) if dest_dir else Path(os.getenv("REPO_DIR", "./repos"))
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{owner}-{repo}"
    target.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(zip_url)
        if resp.status_code == 404:
            # try master branch
            zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip"
            resp = await client.get(zip_url)
        resp.raise_for_status()
        zip_path = dest / f"{owner}-{repo}.zip"
        zip_path.write_bytes(resp.content)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    try:
        zip_path.unlink()
    except OSError:
        pass

    # The extracted folder is <repo>-<branch>
    extracted = [p for p in target.iterdir() if p.is_dir()]
    root = extracted[0] if extracted else target
    return {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "path": str(root),
        "url": url,
    }


def analyze_repository(path: str) -> dict[str, Any]:
    """Scan a local repository and produce a lightweight intelligence report."""
    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise AgentError(f"Repository path not found: {path}")

    files: list[str] = []
    languages: dict[str, int] = {}
    extensions = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".java": "Java", ".go": "Go", ".rs": "Rust", ".cs": "C#",
        ".cpp": "C++", ".c": "C", ".rb": "Ruby", ".php": "PHP",
    }
    entry_candidates = {"main.py", "app.py", "index.js", "main.go", "Main.java",
                        "package.json", "pyproject.toml", "Cargo.toml", "go.mod"}
    entries: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        rel = str(p.relative_to(root))
        files.append(rel)
        ext = p.suffix.lower()
        if ext in extensions:
            languages[extensions[ext]] = languages.get(extensions[ext], 0) + 1
        if p.name in entry_candidates:
            entries.append(rel)

    return {
        "path": str(root),
        "file_count": len(files),
        "languages": languages,
        "entry_points": entries[:20],
        "top_level": sorted({p.split("/")[0] for p in files})[:50],
    }
