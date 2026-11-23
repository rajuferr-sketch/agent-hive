"""FastAPI auth middleware — optional-by-default, strict when configured.

Trust model
-----------
* No ``API_MASTER_TOKEN`` and no tokens issued → **local trust mode**:
  every caller gets the admin identity. This makes the documented
  quickstart (``docker compose up -d``) work with zero configuration on
  a trusted host/network.
* ``API_MASTER_TOKEN`` set or at least one token issued → **enforced
  mode**: callers must present a valid token (``Authorization: Bearer``
  or ``x-api-key``); anonymous callers get an identity with zero scopes
  (tools/endpoints that require scopes will refuse).

Rate limiting applies in both modes (per identity or per client IP).
Legacy ``AGENT_HIVE_API_KEY`` remains accepted as an admin token for
backwards compatibility.
"""

from __future__ import annotations

from typing import Any

from agent_hive.config.settings import get_settings
from agent_hive.core.logging import get_logger
from agent_hive.security.audit import AuditLogger
from agent_hive.security.ratelimit import RateLimiter
from agent_hive.security.tokens import TokenIdentity, TokenManager

log = get_logger("agent_hive.security.middleware")

OPEN_PATHS = ("/health", "/docs", "/redoc", "/openapi.json")
PROTECTED_PREFIXES = ("/api", "/v1", "/mcp", "/ws")


class SecurityCoordinator:
    """Resolves caller identity + rate limits for the HTTP layer."""

    def __init__(self) -> None:
        self.tokens = TokenManager()
        self.limiter = RateLimiter()
        self.audit = AuditLogger()
        self._configured: bool | None = None

    async def _security_configured(self) -> bool:
        if self._configured is None:
            settings = get_settings()
            self._configured = bool(
                settings.api_master_token or await self.tokens.active_tokens_exist()
            )
        return self._configured

    def invalidate_cache(self) -> None:
        self._configured = None

    @staticmethod
    def extract_token(request: Any) -> str:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.headers.get("x-api-key") or ""

    async def resolve(self, request: Any) -> TokenIdentity:
        settings = get_settings()
        token = self.extract_token(request)
        configured = await self._security_configured()

        # Legacy static key keeps working (compat) — admin identity.
        legacy = getattr(settings, "_legacy_api_key", "") or ""
        import os

        legacy = os.getenv("AGENT_HIVE_API_KEY", "")
        if legacy and token == legacy:
            return TokenIdentity(
                token_id="legacy", subject="legacy", role="admin", scopes=["*"]
            )

        if token:
            try:
                return await self.tokens.verify(token)
            except Exception as exc:  # noqa: BLE001 — unified denial
                if configured:
                    await self.audit.log(
                        "unknown", "auth.denied", str(request.url.path),
                        "denied", "http", {"reason": str(exc)[:120]},
                    )
                    return TokenIdentity(
                        token_id="anonymous", subject="anonymous",
                        role="anonymous", scopes=[],
                    )
                # not configured: an *invalid* token still yields guest
                return TokenIdentity(
                    token_id="guest", subject="guest", role="guest", scopes=["*"]
                )

        if configured:
            return TokenIdentity(
                token_id="anonymous", subject="anonymous",
                role="anonymous", scopes=[],
            )
        # local trust mode
        return TokenIdentity(
            token_id="local", subject="local", role="admin", scopes=["*"]
        )

    async def check_rate(self, request: Any, identity: TokenIdentity) -> tuple[bool, int]:
        key = identity.token_id if identity.token_id not in ("anonymous",) else (
            request.client.host if request.client else "ip-unknown"
        )
        verdict = self.limiter.check(f"http:{key}")
        return verdict.allowed, verdict.retry_after_s
