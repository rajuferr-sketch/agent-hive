"""Security-by-design package: tokens, RBAC, rate limiting, sanitization, audit.

Every external entry point (MCP, REST, WebSocket, OpenAI-compatible,
Ollama-compatible) resolves a caller identity through
:mod:`agent_hive.security.tokens`, checks scopes through
:mod:`agent_hive.security.rbac`, is throttled by
:mod:`agent_hive.security.ratelimit` and leaves an auditable trace in
:mod:`agent_hive.security.audit`. Inputs/outputs pass through
:mod:`agent_hive.security.sanitize` (prompt-injection heuristics, secret
redaction, size caps).
"""

from agent_hive.security.audit import AuditLogger
from agent_hive.security.ratelimit import RateLimiter
from agent_hive.security.rbac import Role, all_scopes, role_scopes
from agent_hive.security.sanitize import (
    detect_prompt_injection,
    redact_secrets,
    sanitize_input,
)
from agent_hive.security.tokens import TokenManager

__all__ = [
    "AuditLogger",
    "RateLimiter",
    "Role",
    "TokenManager",
    "all_scopes",
    "detect_prompt_injection",
    "redact_secrets",
    "role_scopes",
    "sanitize_input",
]
