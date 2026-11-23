"""Universal AI Gateway — one front door for every AI client.

Flow (per request)::

    USER/AI CLIENT ──▶ validate ──▶ rate-limit ──▶ translate ──▶ select agent
                     ──▶ execute (mission/task via scheduler) ──▶ monitor
                     ──▶ structured response ──▶ persist history (shared memory)

The gateway does *not* care which client is on the other side: MCP,
OpenAI-compatible, Ollama-compatible, REST and WebSocket connectors all
call :meth:`UniversalGateway.handle` / :meth:`UniversalGateway.tool_call`.
Concurrency is bounded by a semaphore, each request has a timeout budget,
in-flight requests can be cancelled by id, and every completed exchange
is persisted to the universal shared memory so another client (or the
same client tomorrow) can resume with full context.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.core.ids import new_id
from agent_hive.core.logging import get_logger
from agent_hive.security.audit import AuditLogger
from agent_hive.security.ratelimit import RateLimiter
from agent_hive.security.sanitize import detect_prompt_injection, sanitize_input
from agent_hive.security.tokens import TokenIdentity, TokenManager

if TYPE_CHECKING:  # pragma: no cover
    from agent_hive.hive import Hive
    from agent_hive.mcp.tools import ToolRegistry
    from agent_hive.universal_memory.universal import UniversalMemoryManager

log = get_logger("agent_hive.gateway")

VALID_CLIENT_KINDS = ("mcp", "openai", "ollama", "rest", "ws", "generic")


class GatewayError(AgentError):
    """Gateway-level failure (validation, timeout, overload)."""


@dataclass(slots=True)
class UniversalRequest:
    """Provider-agnostic request envelope."""

    instruction: str = ""
    client_id: str = "anonymous"
    client_kind: str = "rest"
    session_id: str = "global"
    user_id: str = "default"
    project_id: str = "default"
    mode: str | None = None
    title: str | None = None
    timeout_s: int | None = None
    save_history: bool = True
    context_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UniversalResponse:
    ok: bool
    request_id: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


class UniversalGateway:
    """Validates, routes, executes and records universal AI requests."""

    def __init__(
        self,
        hive: Hive,
        umemory: UniversalMemoryManager,
        tools: ToolRegistry,
    ) -> None:
        self.hive = hive
        self.umemory = umemory
        self.tools = tools
        self.tokens = TokenManager()
        self.limiter = RateLimiter()
        self.audit = AuditLogger()
        settings = hive.settings
        self._sem = asyncio.Semaphore(settings.gateway_max_concurrent)
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._ttl_task: asyncio.Task[None] | None = None
        self._started = False

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        """Start the background TTL purge loop (bounded, cancellable)."""
        if self._started:
            return
        self._started = True
        self._ttl_task = asyncio.get_running_loop().create_task(self._ttl_loop())

    async def stop(self) -> None:
        if self._ttl_task is not None:
            self._ttl_task.cancel()
            try:
                await self._ttl_task
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._ttl_task = None
        for task in list(self._inflight.values()):
            task.cancel()
        self._inflight.clear()
        self._started = False

    async def _ttl_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(10.0, self.hive.settings.selfheal_interval))
                try:
                    await asyncio.wait_for(self.umemory.purge_expired(), timeout=30)
                except (asyncio.TimeoutError, AgentError) as exc:
                    log.debug("TTL purge issue: %s", exc)
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------ handle
    async def _fallback_identity(self) -> TokenIdentity | None:
        """Local-trust identity when security is unconfigured; else anonymous.

        Mirrors the HTTP middleware trust model: with no master token and
        no issued tokens the gateway executes for locally trusted callers;
        once tokens exist, callers must present one.
        """
        if self.hive.settings.api_master_token:
            return None
        try:
            enforced = await self.tokens.active_tokens_exist()
        except AgentError:
            enforced = False
        if enforced:
            return None
        return TokenIdentity(
            token_id="gateway-local", subject="local", role="admin", scopes=["*"]
        )

    async def handle(
        self,
        request: UniversalRequest,
        identity: TokenIdentity | None = None,
    ) -> UniversalResponse:
        """Process a natural-language request from any connected client."""
        request_id = new_id()
        session_id = (request.session_id or "global").strip()[:64] or "global"
        identity = identity or await self._fallback_identity()
        try:
            verdict = self.limiter.check(f"gw:{request.client_id}")
            if not verdict.allowed:
                await self.audit.log(
                    request.client_id, "gateway.rate_limited", "request",
                    "denied", request.client_kind,
                )
                return UniversalResponse(
                    False, request_id, session_id,
                    error={"code": "rate_limited",
                           "message": f"retry after {verdict.retry_after_s}s"},
                )

            instruction = sanitize_input(request.instruction or "")
            if not str(instruction).strip():
                return UniversalResponse(
                    False, request_id, session_id,
                    error={"code": "invalid_request",
                           "message": "instruction is required"},
                )
            injection = detect_prompt_injection(str(instruction))
            if injection.flagged:
                await self.audit.log(
                    request.client_id, "gateway.injection_blocked", "request",
                    "denied", request.client_kind,
                    {"patterns": injection.patterns},
                )
                return UniversalResponse(
                    False, request_id, session_id,
                    error={"code": "injection_blocked",
                           "message": "instruction refused by prompt-injection guard",
                           "patterns": injection.patterns},
                )

            timeout = request.timeout_s or self.hive.settings.gateway_request_timeout
            async with self._sem:
                result = await asyncio.wait_for(
                    self._execute(request, str(instruction), session_id, request_id,
                                  identity),
                    timeout=max(1, timeout),
                )
            return UniversalResponse(
                True, request_id, session_id, data=result
            )
        except asyncio.TimeoutError:
            await self.audit.log(
                request.client_id, "gateway.timeout", "request", "error",
                request.client_kind, {"request_id": request_id},
            )
            return UniversalResponse(
                False, request_id, session_id,
                error={"code": "timeout",
                       "message": "request exceeded the configured timeout budget"},
            )
        except PermissionDenied as exc:
            return UniversalResponse(
                False, request_id, session_id,
                error={"code": "permission_denied", "message": str(exc)},
            )
        except AgentError as exc:
            return UniversalResponse(
                False, request_id, session_id,
                error={"code": "gateway_error", "message": str(exc)},
            )

    async def _execute(
        self,
        request: UniversalRequest,
        instruction: str,
        session_id: str,
        request_id: str,
        identity: TokenIdentity | None,
    ) -> dict[str, Any]:
        # 1. session context: pull prior cross-client memory for continuity
        prior = await self.umemory.history(
            session_id=session_id, project_id=request.project_id,
            user_id=request.user_id, memory_type=None, limit=8,
        )
        context_summary = [
            {"key": p["key"], "type": p["memory_type"], "version": p["version"]}
            for p in prior[:5]
        ]

        # 2. record that this session exchange happened (episodic)
        await self.umemory.save(
            memory_type="episodic",
            key=f"request:{request_id}",
            content=f"[{request.client_kind}] {instruction[:400]}",
            value={"client": request.client_kind, "client_id": request.client_id,
                   "request_id": request_id, "status": "accepted"},
            user_id=request.user_id,
            project_id=request.project_id,
            session_id=session_id,
            created_by_client=request.client_kind,
        )

        # 3. translate to mission and execute through the master orchestrator
        from agent_hive.mcp.tools import ToolContext

        exec_ctx = ToolContext(
            hive=self.hive, umemory=self.umemory,
            identity=identity, client=f"gateway:{request.client_kind}",
        )
        mission_args: dict[str, Any] = {
            "instruction": instruction,
            "session_id": session_id,
        }
        if request.mode:
            mission_args["mode"] = request.mode
        if request.title:
            mission_args["title"] = request.title
        mission = await self.tools.call(
            "agent_execute",
            mission_args,
            ctx=exec_ctx,
            identity=identity,
            client=f"gateway:{request.client_kind}",
        )

        if not mission.get("ok"):
            tool_error = mission.get("error") or {}
            code = str(tool_error.get("code", "tool_error"))
            message = str(tool_error.get("message", "mission execution failed"))
            if code in ("unauthenticated", "permission_denied"):
                raise PermissionDenied(message)
            raise GatewayError(message)

        # 4. persist the outcome as task + decision memory (cross-client)
        data = mission.get("data", {}) if mission.get("ok") else {}
        mission_id = data.get("mission_id")
        deliverable = data.get("deliverable") or data.get("summary") or ""
        if request.save_history:
            await self.umemory.save(
                memory_type="task",
                key=f"mission:{mission_id}" if mission_id else f"request:{request_id}",
                content=f"mission {mission_id or request_id}: {str(deliverable)[:400]}",
                value={
                    "mission_id": mission_id,
                    "request_id": request_id,
                    "client": request.client_kind,
                    "client_id": request.client_id,
                    "status": "completed" if mission.get("ok") else "failed",
                    "tasks": data.get("tasks", []),
                },
                user_id=request.user_id,
                project_id=request.project_id,
                session_id=session_id,
                created_by_client=request.client_kind,
            )

        return {
            "request_id": request_id,
            "session_id": session_id,
            "mission_id": mission_id,
            "deliverable": deliverable,
            "mission": mission,
            "prior_context": context_summary,
        }

    # --------------------------------------------------------------- tool_call
    async def tool_call(
        self,
        name: str,
        args: dict[str, Any],
        identity: TokenIdentity | None = None,
        client: str = "rest",
    ) -> dict[str, Any]:
        """Execute one of the 18 platform tools on behalf of any client."""
        verdict = self.limiter.check(f"tool:{client}")
        if not verdict.allowed:
            return {"ok": False,
                    "error": {"code": "rate_limited",
                              "message": f"retry after {verdict.retry_after_s}s"}}
        effective = identity or await self._fallback_identity()
        from agent_hive.mcp.tools import ToolContext

        ctx = ToolContext(
            hive=self.hive, umemory=self.umemory,
            identity=effective, client=client or "gateway",
        )
        result = await self.tools.call(name, sanitize_input(args or {}),
                                       ctx=ctx, identity=effective, client=client)
        await self.audit.log(
            (effective.subject if effective else "anonymous"), f"tool.{name}",
            name, "ok" if result.get("ok") else "error", client,
        )
        return result

    # ------------------------------------------------------------------ resume
    async def resume(
        self,
        session_id: str,
        instruction: str,
        client_id: str = "anonymous",
        client_kind: str = "rest",
        identity: TokenIdentity | None = None,
        user_id: str = "default",
        project_id: str = "default",
    ) -> UniversalResponse:
        """Continue a previous session: load cross-client context, then act."""
        context = await self.umemory.history(session_id=session_id, limit=20)
        if not context:
            return UniversalResponse(
                False, new_id(), session_id,
                error={"code": "session_not_found",
                       "message": f"no stored context for session '{session_id}'"},
            )
        lines = []
        for rec in context[:10]:
            lines.append(f"- [{rec['memory_type']}] {rec['key']}: {rec['content'][:200]}")
        stitched = instruction + "\n\nContext from previous session:\n" + "\n".join(lines)
        return await self.handle(
            UniversalRequest(
                instruction=stitched,
                client_id=client_id,
                client_kind=client_kind,
                session_id=session_id,
                user_id=user_id,
                project_id=project_id,
                title=f"Resume session {session_id}",
            ),
            identity=identity,
        )
    # ------------------------------------------------------------------ cancel
    async def cancel(self, request_id: str) -> bool:
        task = self._inflight.pop(request_id, None)
        if task is not None:
            task.cancel()
            await self.audit.log("gateway", "gateway.cancelled", request_id, "ok")
            return True
        return False

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "max_concurrent": self.hive.settings.gateway_max_concurrent,
            "in_flight": len(self._inflight),
            "clients_supported": list(VALID_CLIENT_KINDS),
        }
