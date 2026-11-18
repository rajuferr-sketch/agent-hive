"""Built-in, dependency-free tools for agents."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import AgentError
from agent_hive.tools.registry import REGISTRY

_SECRET_PATTERNS = [
    r'(?i)["\']?api[_-]?key["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}["\']',
    r'(?i)["\']?secret["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-]{12,}["\']',
    r'(?i)["\']?password["\']?\s*[:=]\s*["\'][^"\']{8,}["\']',
    r"(?i)(bearer\s+[A-Za-z0-9_\-\.=]{20,})",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]


async def summarize(text: str, max_sentences: int = 5) -> dict[str, Any]:
    """Extractive summarizer: sentence scoring by term frequency."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]
    if not sentences:
        return {"summary": "", "sentences": 0}
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on",
            "with", "as", "at", "by", "da", "di", "che", "il", "la", "e", "per", "con"}
    freq: dict[str, int] = {}
    for sent in sentences:
        for word in re.findall(r"\w+", sent.lower()):
            if word not in stop and len(word) > 2:
                freq[word] = freq.get(word, 0) + 1
    scored = [
        (sum(freq.get(w, 0) for w in re.findall(r"\w+", s.lower())) / max(len(s.split()), 1), i, s)
        for i, s in enumerate(sentences)
    ]
    top = sorted(scored, key=lambda x: (-x[0], x[1]))[: max(1, max_sentences)]
    ordered = sorted(top, key=lambda x: x[1])
    return {"summary": " ".join(s for _, _, s in ordered), "sentences": len(sentences)}


async def word_count(text: str) -> dict[str, Any]:
    return {
        "words": len(re.findall(r"\S+", text or "")),
        "chars": len(text or ""),
        "lines": len((text or "").splitlines()),
    }


async def regex_extract(pattern: str, text: str, flags: str = "") -> dict[str, Any]:
    import concurrent.futures

    f = re.IGNORECASE if "i" in flags else 0

    def _run() -> list[Any]:
        return re.findall(pattern, text or "", f)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            matches = future.result(timeout=1.0)
    except concurrent.futures.TimeoutError:
        return {"matches": [], "count": 0, "error": "regex timed out after 1s"}
    except re.error as exc:
        return {"matches": [], "count": 0, "error": str(exc)}
    return {"matches": [m if isinstance(m, str) else list(m) for m in matches[:100]],
            "count": len(matches)}


async def json_validate(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "")
        return {"valid": True, "data": data if isinstance(data, dict) else {"value": data}}
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": str(exc)}


async def dedupe_lines(text: str) -> dict[str, Any]:
    seen: set[str] = set()
    out: list[str] = []
    for line in (text or "").splitlines():
        norm = line.strip()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(line)
    return {"text": "\n".join(out), "removed": len((text or "").splitlines()) - len(out)}


async def code_lint_py(code: str) -> dict[str, Any]:
    """Static syntax check (AST parse + compile) — never executes code."""
    try:
        tree = ast.parse(code or "")
        compile(tree, "<agent-code>", "exec")  # no exec of code itself
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [
            n.names[0].name if isinstance(n, ast.Import) else n.module or ""
            for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        return {"valid": True, "functions": funcs, "classes": classes,
                "imports": sorted(set(imports))}
    except SyntaxError as exc:
        return {"valid": False, "error": f"line {exc.lineno}: {exc.msg}"}


async def secret_scan(text: str) -> dict[str, Any]:
    """Detect hard-coded secrets (never stores the matches' context)."""
    findings: list[dict[str, str]] = []
    for pattern in _SECRET_PATTERNS:
        for match in re.finditer(pattern, text or ""):
            snippet = match.group(0)
            findings.append({
                "type": pattern[:40],
                "preview": snippet[:8] + "***",  # redacted preview
            })
    return {"clean": not findings, "findings": findings[:20]}


async def file_read(path: str) -> dict[str, Any]:
    """Read a file inside the sandboxed workspace directory."""
    workspace = Path(get_settings().workspace_dir).resolve()
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace):
        raise AgentError("Path escapes the workspace sandbox")
    if not target.is_file():
        raise AgentError(f"File not found: {path}")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "size": target.stat().st_size, "content": content[:100_000]}


async def http_get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch a URL (requires ENABLE_HTTP_TOOLS=true)."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return {"url": url, "status": resp.status_code,
                "content": resp.text[:50_000]}


async def file_write(path: str, content: str) -> dict[str, Any]:
    """Write a file inside the sandboxed workspace directory."""
    content = content or ""
    if len(content.encode("utf-8")) > 1_000_000:
        raise AgentError("File content exceeds 1 MB limit")
    workspace = Path(get_settings().workspace_dir).resolve()
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace):
        raise AgentError("Path escapes the workspace sandbox")
    existing = list(workspace.rglob("*")) if workspace.exists() else []
    files = [p for p in existing if p.is_file()]
    if target not in files and len(files) >= 1000:
        raise AgentError("Workspace file count limit (1000) reached")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "size": len(content), "written": True}
    """Write a file inside the sandboxed workspace directory."""
    content = content or ""
    if len(content.encode("utf-8")) > 1_000_000:
        raise AgentError("File content exceeds 1 MB limit")
    workspace = Path(get_settings().workspace_dir).resolve()
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace):
        raise AgentError("Path escapes the workspace sandbox")
    # Limit total number of files in the workspace.
    existing = list(workspace.rglob("*")) if workspace.exists() else []
    files = [p for p in existing if p.is_file()]
    if target not in files and len(files) >= 1000:
        raise AgentError("Workspace file count limit (1000) reached")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "size": len(content), "written": True}


def register_builtins() -> None:
    REGISTRY.register("summarize", "Extractive text summary", "text", summarize)
    REGISTRY.register("word_count", "Word/char/line statistics", "text", word_count)
    REGISTRY.register("regex_extract", "Extract regex matches from text", "text", regex_extract)
    REGISTRY.register("json_validate", "Validate and parse JSON text", "text", json_validate)
    REGISTRY.register("dedupe_lines", "Remove duplicate lines from text", "text", dedupe_lines)
    REGISTRY.register("code_lint_py", "Static Python syntax check (no execution)", "code", code_lint_py)
    REGISTRY.register("secret_scan", "Scan text for hard-coded secrets", "code", secret_scan)
    REGISTRY.register("file_read", "Read a file from the sandboxed workspace", "file", file_read)
    REGISTRY.register("file_write", "Write a file to the sandboxed workspace", "file", file_write)
    REGISTRY.register("http_get", "Fetch a URL (requires ENABLE_HTTP_TOOLS)", "http", http_get)


register_builtins()
