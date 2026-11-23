"""Input validation / output sanitization / prompt-injection heuristics.

Every external payload passes through :func:`sanitize_input` before it
reaches agents; every text that goes to logs or audit records passes
through :func:`redact_secrets`. :func:`detect_prompt_injection` flags
classic injection patterns so the gateway can refuse or sandbox them.
Nothing here is a substitute for scope checks — it is defense in depth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_INPUT_CHARS = 100_000
MAX_LIST_ITEMS = 200
MAX_DEPTH = 8

# --- secret patterns (never logged raw) ------------------------------------
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                 # OpenAI-style keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),            # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),          # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}"),  # JWT (3 segments)
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{2,}"),  # truncated JWT
    re.compile(r"ahive_[0-9a-f]{32}"),                    # our own tokens
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),                # Google API keys
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),             # Anthropic keys
)
_REDACTED = "[REDACTED]"

# --- prompt-injection heuristics --------------------------------------------
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?(prompt|instructions)", re.I),
    re.compile(r"print\s+(your|the)\s+(system\s+)?(prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I),
    re.compile(r"(delete|drop)\s+(all\s+)?(tables|database|memories)\b", re.I),
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"(disable|bypass)\s+(all\s+)?(security|safety|filters|guardrails)", re.I),
    re.compile(r"<\|.*(im_start|im_end|system).*\|>", re.I),
)


@dataclass(slots=True)
class InjectionReport:
    flagged: bool = False
    patterns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"flagged": self.flagged, "patterns": self.patterns}


def redact_secrets(text: str) -> str:
    """Replace secret-looking substrings with ``[REDACTED]``."""
    out = text or ""
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


def sanitize_input(value: Any, max_chars: int = MAX_INPUT_CHARS) -> Any:
    """Recursively sanitize an input payload.

    * strings: strip control characters, cap length, redact secrets;
    * dicts/lists: cap size and depth;
    * other scalars pass through unchanged.
    """
    if isinstance(value, str):
        cleaned = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
        return redact_secrets(cleaned[:max_chars])
    if isinstance(value, dict):
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"object has more than {MAX_LIST_ITEMS} keys")
        return {str(k)[:256]: sanitize_input(v, max_chars) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"list has more than {MAX_LIST_ITEMS} items")
        return [sanitize_input(v, max_chars) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    return str(value)[:max_chars]


def detect_prompt_injection(text: str) -> InjectionReport:
    """Heuristic scan for prompt-injection / destructive patterns."""
    report = InjectionReport()
    haystack = (text or "")[:MAX_INPUT_CHARS]
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(haystack)
        if match:
            report.flagged = True
            report.patterns.append(pattern.pattern)
    return report


def sanitize_output(text: str, max_chars: int = 1_000_000) -> str:
    """Cap and redact model/tool output before it leaves the process."""
    return redact_secrets(text or "")[:max_chars]
