"""Download and parse documents into text.

Supported formats depend on optional dependencies:
- PDF: pypdf
- DOCX: python-docx
- HTML: built-in
- TXT/MD: built-in
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_hive.core.errors import AgentError


async def download_document(url: str, dest_dir: str | None = None) -> dict[str, Any]:
    """Download a document and extract its text + basic metadata."""
    dest = Path(dest_dir) if dest_dir else Path(os.getenv("DOCUMENT_DIR", "./documents"))
    dest.mkdir(parents=True, exist_ok=True)

    # Download raw bytes directly (http_get is text-oriented).
    # For binary formats we need the original bytes.
    pass
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path) or "document"
    path = dest / filename

    # Re-download raw bytes.
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.content
    path.write_bytes(raw)

    text, metadata = parse_document(path)
    content_hash = hashlib.sha256(raw).hexdigest()
    return {
        "url": url,
        "path": str(path),
        "filename": filename,
        "content_hash": content_hash,
        "metadata": metadata,
        "text": text[:200_000],
        "chars": len(text),
    }


def parse_document(path: Path) -> tuple[str, dict[str, Any]]:
    suffix = path.suffix.lower()
    metadata: dict[str, Any] = {"title": path.stem, "pages": 0}

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AgentError("pypdf is required for PDF parsing (pip install pypdf)") from exc
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
        metadata["pages"] = len(pages)
        try:
            info = reader.metadata
            if info:
                metadata["title"] = str(info.title or metadata["title"])
                metadata["author"] = str(info.author or "")
        except Exception:
            pass
        return "\n\n".join(pages), metadata

    if suffix == ".docx":
        try:
            import docx
        except ImportError as exc:
            raise AgentError("python-docx is required (pip install python-docx)") from exc
        doc = docx.Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs), metadata

    if suffix in (".html", ".htm"):
        from html.parser import HTMLParser

        class _Stripper(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data: str) -> None:
                self.parts.append(data)

        stripper = _Stripper()
        stripper.feed(path.read_text(encoding="utf-8", errors="replace"))
        return " ".join(stripper.parts), metadata

    # TXT / MD / other
    return path.read_text(encoding="utf-8", errors="replace"), metadata
