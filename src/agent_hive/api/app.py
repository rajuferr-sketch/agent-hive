"""REST + WebSocket API for AgentHive.

Endpoints overview (details in docs/api.md):

* GET  /health                          liveness probe
* GET  /system/status                   aggregate system status
* POST /api/missions                    delegate a full mission to the Master
* GET  /api/missions/{id}               mission summary
* GET  /api/tasks?status=&mission_id=   task list
* GET  /api/tasks/{id}                  task detail
* POST /api/tasks                       enqueue a single task (bypass Master)
* GET  /api/agents                      agent roster + capabilities
* GET  /api/agents/{name}               agent detail
* POST /api/agents/{name}/message       send an internal message
* GET  /api/agents/registry             DB-backed agent registry
* POST /api/agents/registry             register agent #21+ at runtime
* POST /api/agents/{name}/enable        (re)load an agent
* POST /api/agents/{name}/disable       unload an agent
* GET  /api/agents/{name}/health        provider-chain probe
* GET  /api/agents/{name}/stats         workload counters
* GET  /api/messages?agent=             message history
* GET  /api/memory/{scope}?q=&agent=    read/search memory
* POST /api/memory/shared               write to shared memory
* POST /api/system/settings             toggle mock mode
* POST /api/issues                      open an issue
* GET  /api/issues                      list/filter issues
* GET  /api/issues/{id}                 issue detail (with comments)
* POST /api/issues/{id}/comments        comment on an issue
* POST /api/issues/{id}/assign          assign to an agent (or best-match)
* POST /api/issues/{id}/status          transition the lifecycle
* GET  /api/issues/stats/summary        issue counters by status
* POST /api/pulls                       open a pull request
* GET  /api/pulls                       list/filter pull requests
* GET  /api/pulls/{id}                  PR detail (with reviews)
* POST /api/pulls/{id}/review           record a review (or agent-review)
* POST /api/pulls/{id}/merge            guarded merge (approved only)
* POST /api/pulls/{id}/close            close a PR (reopenable)
* POST /api/pulls/{id}/reopen           reopen a closed PR
* GET  /api/pulls/stats/summary         PR counters by status
* WS   /ws                              live event stream
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from agent_hive.api.schemas import (
    AgentRegister,
    DirectMessage,
    IssueAssign,
    IssueCommentCreate,
    IssueCreate,
    IssueStatus,
    MissionRequest,
    PullRequestCreate,
    PullRequestMerge,
    PullRequestReviewCreate,
    SettingsUpdate,
    SharedMemoryWrite,
    TaskCreate,
)
from agent_hive.connectors.ollama_api import build_ollama_router
from agent_hive.connectors.openai_api import build_openai_router
from agent_hive.connectors.ws import build_ws_router
from agent_hive.core.errors import AgentError, ConfigError, PermissionDenied
from agent_hive.gateway.gateway import UniversalRequest
from agent_hive.hive import Hive
from agent_hive.mcp.http import build_mcp_router
from agent_hive.mcp.server import MCPServerCore
from agent_hive.mcp.tools import ToolContext
from agent_hive.security.middleware import OPEN_PATHS, SecurityCoordinator
from agent_hive.version import __version__

_STATE: Hive | None = None
_SECURITY: SecurityCoordinator | None = None


class _AppState:
    """Late-bound holder so connectors can reach the live Hive."""

    @staticmethod
    def hive() -> Hive:
        if _STATE is None:
            raise RuntimeError("Hive not initialized")
        return _STATE


def get_hive() -> Hive:
    if _STATE is None:
        raise RuntimeError("Hive not initialized")
    return _STATE


def get_security() -> SecurityCoordinator:
    global _SECURITY
    if _SECURITY is None:
        _SECURITY = SecurityCoordinator()
    return _SECURITY


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _STATE
    _STATE = Hive()
    await _STATE.startup()
    if _STATE.settings.selfheal_enabled:
        from agent_hive.selfheal.loop import SelfHeal

        healer: Any = SelfHeal(_STATE, safe_stop=_STATE.shutdown)
        _STATE.selfheal = healer
        healer.start()
    try:
        yield
    finally:
        await _STATE.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentHive",
        description="Advanced multi-agent orchestration: 1 Master Agent + 20 specialized AI agents.",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_middleware(request, call_next):
        """Token auth + rate limiting (optional-by-default; see middleware docs)."""
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)
        security = get_security()
        identity = await security.resolve(request)
        request.state.identity = identity
        allowed, retry_after = await security.check_rate(request, identity)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"detail": "rate limit exceeded"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def legacy_api_key_guard(request, call_next):
        """Back-compat static key check (kept for existing deployments)."""
        import os

        key = os.getenv("AGENT_HIVE_API_KEY")
        if key and request.url.path.startswith("/api"):
            supplied = (
                request.headers.get("x-api-key")
                or (request.headers.get("authorization") or "").removeprefix("Bearer ")
            )
            if supplied and supplied != key:
                return JSONResponse(status_code=401, content={"detail": "invalid or missing API key"})
        return await call_next(request)

    # ------------------------------------------------------------- system
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/system/status")
    async def system_status() -> dict[str, Any]:
        hive = get_hive()
        info = hive.status()
        info["task_stats"] = await hive.tasks.stats()
        return info

    @app.post("/api/system/settings")
    async def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
        hive = get_hive()
        if payload.allow_mock is not None:
            hive.settings.allow_mock = payload.allow_mock
        return {"allow_mock": hive.settings.allow_mock}

    # ------------------------------------------------------------ missions
    @app.post("/api/missions")
    async def create_mission(payload: MissionRequest) -> dict[str, Any]:
        hive = get_hive()
        try:
            return await hive.run_mission(
                payload.text, mode=payload.mode, title=payload.title
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/missions/{mission_id}")
    async def mission(mission_id: str) -> dict[str, Any]:
        hive = get_hive()
        tasks = await hive.tasks.list(mission_id=mission_id, limit=200)
        if not tasks:
            raise HTTPException(status_code=404, detail="Mission not found")
        return {"mission_id": mission_id, "tasks": [
            {"id": t.id, "title": t.title, "agent": t.agent_name,
             "status": t.status, "attempts": t.attempts, "error": t.error}
            for t in tasks
        ]}

    # --------------------------------------------------------------- tasks
    @app.post("/api/tasks")
    async def create_task(payload: TaskCreate) -> dict[str, Any]:
        hive = get_hive()
        task = await hive.tasks.create(
            title=payload.title,
            description=payload.description,
            payload=payload.payload,
            agent_name=payload.agent_name,
            priority=payload.priority,
            depends_on=payload.depends_on,
            created_by="api",
        )
        return {"id": task.id, "status": task.status}

    @app.get("/api/tasks")
    async def list_tasks(
        status: str | None = Query(default=None),
        mission_id: str | None = Query(default=None),
        limit: int = Query(default=50, le=200),
    ) -> list[dict[str, Any]]:
        hive = get_hive()
        tasks = await hive.tasks.list(status=status, mission_id=mission_id, limit=limit)
        return [
            {"id": t.id, "title": t.title, "agent": t.agent_name,
             "status": t.status, "priority": t.priority,
             "attempts": t.attempts, "mission_id": t.mission_id}
            for t in tasks
        ]

    @app.get("/api/tasks/{task_id}")
    async def task_detail(task_id: str) -> dict[str, Any]:
        hive = get_hive()
        task = await hive.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "id": task.id, "title": task.title, "description": task.description,
            "status": task.status, "agent": task.agent_name,
            "attempts": task.attempts, "max_retries": task.max_retries,
            "result": task.result, "error": task.error,
            "depends_on": task.depends_on, "mission_id": task.mission_id,
        }

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str) -> dict[str, Any]:
        hive = get_hive()
        task = await hive.tasks.cancel(task_id)
        if task is None:
            raise HTTPException(status_code=409, detail="Task not cancellable")
        return {"id": task.id, "status": task.status}

    # -------------------------------------------------------------- agents
    # NOTE: static registry routes must precede /api/agents/{name} routes.
    @app.get("/api/agents/registry")
    async def agents_registry() -> list[dict[str, Any]]:
        return await get_hive().agents_manager.registry()

    @app.post("/api/agents/registry")
    async def register_agent(payload: AgentRegister) -> dict[str, Any]:
        hive = get_hive()
        try:
            return await hive.agents_manager.register(payload.model_dump(exclude_none=True))
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        return get_hive().runtime.describe()

    @app.get("/api/agents/{name}")
    async def agent_detail(name: str) -> dict[str, Any]:
        hive = get_hive()
        agent = hive.runtime.agents.get(name)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        entry = next(
            d for d in hive.runtime.describe() if d["name"] == name
        )
        memories = await hive.memory.list_scope("individual", agent=name, limit=20)
        entry["recent_memories"] = [
            {"key": m.key, "version": m.version, "updated_at": str(m.updated_at)}
            for m in memories
        ]
        return entry

    @app.post("/api/agents/{name}/message")
    async def send_message(name: str, payload: DirectMessage) -> dict[str, Any]:
        hive = get_hive()
        if name not in hive.runtime.agents and name != "*":
            raise HTTPException(status_code=404, detail="Agent not found")
        msg = await hive.bus.send(
            payload.from_agent, name, payload.kind,
            payload.content, priority=payload.priority,
        )
        return {"id": msg.id, "to": msg.to_agent, "kind": msg.kind}

    # ------------------------------------------------------------ messages
    @app.get("/api/messages")
    async def message_history(
        agent: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        limit: int = Query(default=50, le=200),
    ) -> list[dict[str, Any]]:
        hive = get_hive()
        msgs = await hive.bus.history(agent=agent, task_id=task_id, limit=limit)
        return [
            {"id": m.id, "from": m.from_agent, "to": m.to_agent,
             "kind": m.kind, "content": m.content,
             "created_at": str(m.created_at)}
            for m in msgs
        ]

    # -------------------------------------------------------------- memory
    @app.get("/api/memory/{scope}")
    async def read_memory(
        scope: str,
        agent: str | None = Query(default=None),
        q: str | None = Query(default=None),
        limit: int = Query(default=50, le=200),
    ) -> Any:
        hive = get_hive()
        if scope not in ("individual", "shared", "history"):
            raise HTTPException(status_code=422, detail="scope must be individual|shared|history")
        if q:
            rows = await hive.memory.search(q, scope=scope, agent=agent, limit=limit)
        else:
            rows = await hive.memory.list_scope(scope, agent=agent, limit=limit)
        return [
            {"key": m.key, "value": m.value, "version": m.version,
             "agent": m.agent_name, "scope": m.scope,
             "updated_at": str(m.updated_at)}
            for m in rows
        ]

    @app.post("/api/memory/shared")
    async def write_shared(payload: SharedMemoryWrite) -> dict[str, Any]:
        hive = get_hive()
        entry = await hive.memory.share(
            payload.key, payload.value, author=payload.author, tags=payload.tags
        )
        return {"key": entry.key, "version": entry.version}

    # --------------------------------------------------------------- issues
    def _issue_dict(issue: Any, include_comments: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": issue.id,
            "number": issue.number,
            "title": issue.title,
            "description": issue.description,
            "status": issue.status,
            "priority": issue.priority,
            "labels": issue.labels,
            "reporter": issue.reporter,
            "assignee": issue.assignee,
            "related_task_id": issue.related_task_id,
            "created_at": str(issue.created_at),
            "updated_at": str(issue.updated_at),
            "closed_at": str(issue.closed_at) if issue.closed_at else None,
        }
        if include_comments:
            data["comments"] = [
                {"id": c.id, "author": c.author, "body": c.body,
                 "meta": c.meta, "created_at": str(c.created_at)}
                for c in issue.comments
            ]
        return data

    @app.post("/api/issues")
    async def create_issue(payload: IssueCreate) -> dict[str, Any]:
        hive = get_hive()
        issue = await hive.issues.create(
            payload.title, payload.description, labels=payload.labels,
            priority=payload.priority, reporter=payload.reporter,
            assignee=payload.assignee,
        )
        return _issue_dict(issue)

    @app.get("/api/issues/stats/summary")
    async def issue_stats() -> dict[str, Any]:
        return await get_hive().issues.stats()

    @app.get("/api/issues")
    async def list_issues(
        status: str | None = Query(default=None),
        assignee: str | None = Query(default=None),
        label: str | None = Query(default=None),
        limit: int = Query(default=50, le=200),
    ) -> list[dict[str, Any]]:
        hive = get_hive()
        issues = await hive.issues.list(status=status, assignee=assignee,
                                        label=label, limit=limit)
        return [_issue_dict(i) for i in issues]

    @app.get("/api/issues/{issue_id}")
    async def issue_detail(issue_id: str) -> dict[str, Any]:
        hive = get_hive()
        issue = await hive.issues.get(issue_id) or await hive.issues.get_by_number(
            int(issue_id) if issue_id.isdigit() else -1
        )
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        return _issue_dict(issue, include_comments=True)

    @app.post("/api/issues/{issue_id}/comments")
    async def comment_issue(issue_id: str, payload: IssueCommentCreate) -> dict[str, Any]:
        hive = get_hive()
        try:
            row = await hive.issues.comment(
                issue_id, payload.body, author=payload.author, meta=payload.meta
            )
        except AgentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"id": row.id, "issue_id": row.issue_id, "author": row.author}

    @app.post("/api/issues/{issue_id}/assign")
    async def assign_issue(issue_id: str, payload: IssueAssign) -> dict[str, Any]:
        hive = get_hive()
        try:
            if payload.agent_name:
                if payload.agent_name not in hive.runtime.agents:
                    raise HTTPException(
                        status_code=404, detail="Agent not found in the roster"
                    )
                issue = await hive.issues.assign(issue_id, payload.agent_name)
            else:
                issue = await hive.issues.assign_best(issue_id, hive.runtime)
        except AgentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _issue_dict(issue)

    @app.post("/api/issues/{issue_id}/status")
    async def transition_issue(issue_id: str, payload: IssueStatus) -> dict[str, Any]:
        hive = get_hive()
        try:
            issue = await hive.issues.set_status(issue_id, payload.status)
        except AgentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _issue_dict(issue)

    # ---------------------------------------------------------- pull requests
    def _pr_dict(pr: Any, include_reviews: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": pr.id,
            "number": pr.number,
            "title": pr.title,
            "description": pr.description,
            "source_branch": pr.source_branch,
            "target_branch": pr.target_branch,
            "author": pr.author,
            "status": pr.status,
            "files_changed": pr.files_changed,
            "related_issue_ids": pr.related_issue_ids,
            "task_id": pr.task_id,
            "created_at": str(pr.created_at),
            "merged_at": str(pr.merged_at) if pr.merged_at else None,
            "merged_by": pr.merged_by,
        }
        if include_reviews:
            data["reviews"] = [
                {"id": r.id, "reviewer": r.reviewer, "verdict": r.verdict,
                 "score": r.score, "summary": r.summary,
                 "created_at": str(r.created_at)}
                for r in pr.reviews
            ]
        return data

    @app.post("/api/pulls")
    async def create_pull(payload: PullRequestCreate) -> dict[str, Any]:
        hive = get_hive()
        pr = await hive.pulls.open_pr(
            payload.title, payload.source_branch,
            description=payload.description, target_branch=payload.target_branch,
            author=payload.author, files_changed=payload.files_changed,
            related_issue_ids=payload.related_issue_ids,
        )
        return _pr_dict(pr)

    @app.get("/api/pulls/stats/summary")
    async def pull_stats() -> dict[str, Any]:
        return await get_hive().pulls.stats()

    @app.get("/api/pulls")
    async def list_pulls(
        status: str | None = Query(default=None),
        author: str | None = Query(default=None),
        limit: int = Query(default=50, le=200),
    ) -> list[dict[str, Any]]:
        hive = get_hive()
        pulls = await hive.pulls.list(status=status, author=author, limit=limit)
        return [_pr_dict(p) for p in pulls]

    @app.get("/api/pulls/{pr_id}")
    async def pull_detail(pr_id: str) -> dict[str, Any]:
        hive = get_hive()
        pr = await hive.pulls.get(pr_id) or await hive.pulls.get_by_number(
            int(pr_id) if pr_id.isdigit() else -1
        )
        if pr is None:
            raise HTTPException(status_code=404, detail="Pull request not found")
        return _pr_dict(pr, include_reviews=True)

    @app.post("/api/pulls/{pr_id}/review")
    async def review_pull(pr_id: str, payload: PullRequestReviewCreate) -> dict[str, Any]:
        hive = get_hive()
        if payload.reviewer == "agent":  # delegate to the hive reviewer agent
            try:
                pr = await hive.pulls.agent_review(pr_id, hive.runtime)
            except AgentError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return _pr_dict(pr, include_reviews=True)
        if payload.verdict is None:
            raise HTTPException(
                status_code=422,
                detail="verdict is required unless reviewer='agent'",
            )
        try:
            pr = await hive.pulls.review(
                pr_id, payload.reviewer, payload.verdict,
                score=payload.score, summary=payload.summary,
                comments=payload.comments,
            )
        except AgentError as exc:
            code = 404 if "not found" in str(exc) else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return _pr_dict(pr, include_reviews=True)

    @app.post("/api/pulls/{pr_id}/merge")
    async def merge_pull(pr_id: str, payload: PullRequestMerge) -> dict[str, Any]:
        hive = get_hive()
        try:
            pr = await hive.pulls.merge(pr_id, payload.merged_by)
        except AgentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _pr_dict(pr)

    @app.post("/api/pulls/{pr_id}/close")
    async def close_pull(pr_id: str) -> dict[str, Any]:
        hive = get_hive()
        try:
            pr = await hive.pulls.close(pr_id)
        except AgentError as exc:
            code = 404 if "not found" in str(exc) else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return _pr_dict(pr)

    @app.post("/api/pulls/{pr_id}/reopen")
    async def reopen_pull(pr_id: str) -> dict[str, Any]:
        hive = get_hive()
        try:
            pr = await hive.pulls.reopen(pr_id)
        except AgentError as exc:
            code = 404 if "not found" in str(exc) else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return _pr_dict(pr)

    # ------------------------------------------------------- agent management
    @app.post("/api/agents/{name}/enable")
    async def enable_agent(name: str) -> dict[str, Any]:
        hive = get_hive()
        try:
            return await hive.agents_manager.enable(name)
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/agents/{name}/disable")
    async def disable_agent(name: str) -> dict[str, Any]:
        hive = get_hive()
        try:
            return await hive.agents_manager.disable(name)
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agents/{name}/health")
    async def agent_health(name: str) -> dict[str, Any]:
        hive = get_hive()
        try:
            return await hive.agents_manager.health(name)
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/agents/{name}/stats")
    async def agent_stats(name: str) -> dict[str, Any]:
        hive = get_hive()
        if name not in hive.runtime.agents:
            raise HTTPException(status_code=404, detail="Agent not found")
        return await hive.agents_manager.stats(name)

    # ------------------------------------------------------------ websocket
    @app.websocket("/ws")
    async def websocket_feed(websocket: WebSocket) -> None:
        await websocket.accept()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def _forward(event: Any) -> None:
            queue.put_nowait(event)

        hive = get_hive()
        hive.events.subscribe(_forward)
        try:
            while True:
                event = await queue.get()
                await websocket.send_text(json.dumps({
                    "kind": event.kind, "actor": event.actor,
                    "ts": event.ts, "data": event.data,
                }, default=str))
        except WebSocketDisconnect:
            pass
        finally:
            hive.events.unsubscribe(_forward)

    # =====================================================================
    # Universal AI Platform endpoints (gateway / memory / MCP / connectors)
    # =====================================================================
    app.include_router(build_openai_router(_AppState))
    app.include_router(build_ollama_router(_AppState))
    app.include_router(build_ws_router(_AppState))

    async def _mcp_ctx_factory(session):
        return ToolContext(
            hive=get_hive(), umemory=get_hive().umemory,
            identity=session.identity, client="mcp",
        )

    async def _mcp_identity_resolver(request):
        """Bearer-token identity for MCP-over-HTTP (local-trust fallback)."""
        security = get_security()
        return await security.resolve(request)

    from agent_hive.mcp.tools import get_registry

    _mcp_core = MCPServerCore(
        registry=get_registry(),
        ctx_factory=_mcp_ctx_factory,
        server_version=__version__,
    )
    app.include_router(build_mcp_router(_mcp_core, _mcp_identity_resolver))

    @app.exception_handler(PermissionDenied)
    async def permission_handler(_req: Any, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    # ------------------------------------------------- universal gateway API
    @app.post("/api/universal/request", response_model=None)
    async def universal_request(request: Request) -> Response | dict[str, Any]:
        """Provider-agnostic natural-language entry point (any client)."""
        hive = get_hive()
        payload = await request.json()
        response = await hive.gateway.handle(
            UniversalRequest(
                instruction=str(payload.get("instruction") or ""),
                client_id=str(payload.get("client_id") or "rest"),
                client_kind="rest",
                session_id=str(payload.get("session_id") or "global"),
                user_id=str(payload.get("user_id") or "default"),
                project_id=str(payload.get("project_id") or "default"),
                mode=payload.get("mode"),
                title=payload.get("title"),
                timeout_s=payload.get("timeout_s"),
            ),
            identity=getattr(request.state, "identity", None),
        )
        status = 200 if response.ok else _error_status(response.error)
        return JSONResponse(
            status_code=status,
            content={
                "ok": response.ok, "request_id": response.request_id,
                "session_id": response.session_id,
                "data": response.data, "error": response.error,
            },
        )

    @app.post("/api/universal/resume", response_model=None)
    async def universal_resume(request: Request) -> Response | dict[str, Any]:
        hive = get_hive()
        payload = await request.json()
        session_id = str(payload.get("session_id") or "")
        instruction = str(payload.get("instruction") or "")
        if not session_id or not instruction:
            return JSONResponse(status_code=422, content={
                "detail": "session_id and instruction are required"})
        response = await hive.gateway.resume(
            session_id, instruction,
            client_id=str(payload.get("client_id") or "rest"),
            client_kind="rest",
            identity=getattr(request.state, "identity", None),
            user_id=str(payload.get("user_id") or "default"),
            project_id=str(payload.get("project_id") or "default"),
        )
        status = 200 if response.ok else _error_status(response.error)
        return JSONResponse(status_code=status, content={
            "ok": response.ok, "request_id": response.request_id,
            "session_id": response.session_id,
            "data": response.data, "error": response.error,
        })

    @app.post("/api/universal/tool", response_model=None)
    async def universal_tool(request: Request) -> Response | dict[str, Any]:
        """Execute one of the 18 tools over REST (for non-MCP clients)."""
        hive = get_hive()
        payload = await request.json()
        outcome = await hive.gateway.tool_call(
            str(payload.get("name") or ""),
            payload.get("arguments") or {},
            identity=getattr(request.state, "identity", None),
            client="rest",
        )
        return JSONResponse(status_code=200 if outcome.get("ok") else 400,
                            content=outcome)

    @app.get("/api/universal/tools")
    async def universal_tools() -> dict[str, Any]:
        from agent_hive.connectors.generic import tool_manifest

        return {
            "tools": tool_manifest(get_hive().tool_registry),
            "count": len(get_hive().tool_registry.names()),
            "transports": ["mcp-streamable-http", "mcp-stdio", "rest",
                           "websocket", "openai-compatible", "ollama-compatible",
                           "generic-tool-calling"],
        }

    @app.get("/api/universal/session/{session_id}/context")
    async def universal_session_context(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await get_hive().umemory.history(session_id=session_id, limit=limit)

    @app.get("/api/universal/memory/stats")
    async def universal_memory_stats() -> dict[str, Any]:
        return await get_hive().umemory.stats()

    @app.get("/api/universal/memory")
    async def universal_memory_search(
        q: str | None = Query(default=None),
        memory_type: str | None = Query(default=None),
        user_id: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
        session_id: str | None = Query(default=None),
        limit: int = Query(default=20, le=100),
    ) -> list[dict[str, Any]]:
        hive = get_hive()
        if q:
            return await hive.umemory.search(
                q, memory_type=memory_type, user_id=user_id,
                project_id=project_id, session_id=session_id, limit=limit)
        return await hive.umemory.list_records(
            memory_type=memory_type, user_id=user_id,
            project_id=project_id, session_id=session_id, limit=limit)

    @app.post("/api/universal/memory", response_model=None)
    async def universal_memory_write(request: Request) -> Response | dict[str, Any]:
        hive = get_hive()
        payload = await request.json()
        try:
            record = await hive.umemory.save(
                memory_type=str(payload.get("memory_type") or "episodic"),
                key=str(payload.get("key") or ""),
                content=str(payload.get("content") or ""),
                value=payload.get("value") or {},
                user_id=str(payload.get("user_id") or "default"),
                project_id=str(payload.get("project_id") or "default"),
                session_id=str(payload.get("session_id") or "global"),
                tags=[str(t) for t in (payload.get("tags") or [])],
                access=str(payload.get("access") or "project"),
                ttl_seconds=payload.get("ttl_seconds"),
                created_by_client="rest",
            )
        except AgentError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        return record

    # ------------------------------------------------------- security API
    @app.post("/api/security/tokens", response_model=None)
    async def issue_token(request: Request) -> Response | dict[str, Any]:
        identity = getattr(request.state, "identity", None)
        if identity is None or not identity.has_scope("security:manage"):
            return JSONResponse(status_code=403, content={"detail": "security:manage scope required"})
        payload = await request.json()
        from agent_hive.security.rbac import role_scopes

        role = str(payload.get("role") or "client")
        scopes = payload.get("scopes") or role_scopes(role)
        ident, raw = await get_security().tokens.issue(
            subject=str(payload.get("subject") or "client"),
            scopes=[str(s) for s in scopes],
            role=role,
            ttl_s=payload.get("ttl_s"),
        )
        get_security().invalidate_cache()
        await get_security().audit.log(identity.subject, "token.issued", ident.token_id, "ok", "rest")
        return {"token": raw, "id": ident.token_id, "role": ident.role,
                "scopes": ident.scopes, "note": "store this token now — it is not recoverable"}

    @app.get("/api/security/tokens")
    async def list_tokens() -> list[dict[str, Any]]:
        return await get_security().tokens.list_tokens()

    @app.post("/api/security/tokens/{token_id}/revoke", response_model=None)
    async def revoke_token(token_id: str, request: Request) -> Response | dict[str, Any]:
        identity = getattr(request.state, "identity", None)
        if identity is None or not identity.has_scope("security:manage"):
            return JSONResponse(status_code=403, content={"detail": "security:manage scope required"})
        ok = await get_security().tokens.revoke(token_id)
        return {"revoked": bool(ok), "token_id": token_id}

    @app.post("/api/security/rotate", response_model=None)
    async def rotate_token(request: Request) -> Response | dict[str, Any]:
        payload = await request.json()
        result = await get_security().tokens.rotate(str(payload.get("token") or ""))
        if result is None:
            return JSONResponse(status_code=404, content={"detail": "token unknown or already revoked"})
        ident, raw = result
        return {"token": raw, "id": ident.token_id, "scopes": ident.scopes}

    @app.get("/api/security/audit", response_model=None)
    async def audit_recent(
        request: Request, limit: int = Query(default=50, le=200)
    ) -> Response | list[dict[str, Any]]:
        identity = getattr(request.state, "identity", None)
        if identity is None or not identity.has_scope("security:manage"):
            return JSONResponse(status_code=403, content={"detail": "security:manage scope required"})
        return await get_security().audit.recent(limit=limit)

    # ---------------------------------------------------- GitHub integration
    @app.get("/api/github/status", response_model=None)
    async def github_status() -> Response | dict[str, Any]:
        from agent_hive.github_integration.client import GitHubClient

        client = GitHubClient()
        try:
            status = {
                "mode": client.mode,
                "token_present": bool(client.token),
                "repo": f"{client.owner}/{client.repo}" if client.owner and client.repo else None,
                "reported_scopes": client.reported_scopes,
            }
            return status
        finally:
            await client.aclose()

    @app.post("/api/github/scan", response_model=None)
    async def github_scan(request: Request) -> Response | dict[str, Any]:
        from agent_hive.github_integration.client import GitHubClient

        payload = await request.json()
        files = payload.get("files") or {}
        if not isinstance(files, dict) or not files:
            return JSONResponse(status_code=422, content={"detail": "files map required"})
        client = GitHubClient()
        try:
            return await client.security_scan({str(k): str(v) for k, v in files.items()})
        finally:
            await client.aclose()

    @app.post("/api/github/operation", response_model=None)
    async def github_operation(request: Request) -> Response | dict[str, Any]:
        """Run one GitHub operation under the configured mode gate."""
        from agent_hive.github_integration.client import GitHubClient

        payload = await request.json()
        op = str(payload.get("op") or "")
        params = payload.get("params") or {}
        client = GitHubClient()
        try:
            method = getattr(client, op, None)
            if method is None or not op.startswith(("get_", "list_", "create_", "commit_", "add_", "review_", "merge_", "search_")):
                return JSONResponse(status_code=422, content={"detail": f"unsupported operation '{op}'"})
            result = await method(**params)
            return {"operation": op, "result": result}
        except PermissionDenied as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc)})
        except AgentError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        finally:
            await client.aclose()

    # ------------------------------------------------------------ self-heal
    @app.get("/api/selfheal/report")
    async def selfheal_report() -> dict[str, Any]:
        hive = get_hive()
        if hive.selfheal is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "safe_stop_triggered": hive.selfheal.safe_stop_triggered,
            "consecutive_failures": hive.selfheal._consecutive_failures,
            "last_reports": [r.as_dict() for r in hive.selfheal.reports[-5:]],
        }

    @app.post("/api/selfheal/run")
    async def selfheal_run() -> dict[str, Any]:  # noqa: ANN201
        hive = get_hive()
        if hive.selfheal is None:
            from agent_hive.selfheal.loop import SelfHeal

            hive.selfheal = SelfHeal(hive)
        healer: Any = hive.selfheal
        report = await healer.run_cycle()
        return report.as_dict()

    return app


def _error_status(error: dict[str, Any] | None) -> int:
    code = (error or {}).get("code", "")
    return {
        "rate_limited": 429,
        "injection_blocked": 400,
        "invalid_request": 422,
        "permission_denied": 403,
        "timeout": 504,
        "session_not_found": 404,
    }.get(code, 500)


def _build_registry_fallback():
    from agent_hive.mcp.tools import build_registry

    return build_registry()


app = create_app()
