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

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from agent_hive.core.errors import AgentError, ConfigError, PermissionDenied
from agent_hive.hive import Hive
from agent_hive.version import __version__

_STATE: Hive | None = None


def get_hive() -> Hive:
    if _STATE is None:
        raise RuntimeError("Hive not initialized")
    return _STATE


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _STATE
    _STATE = Hive()
    await _STATE.startup()
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
    async def api_key_guard(request, call_next):
        import os

        key = os.getenv("AGENT_HIVE_API_KEY")
        if key and request.url.path.startswith("/api"):
            if request.headers.get("x-api-key") != key:
                from fastapi.responses import JSONResponse
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

    @app.exception_handler(PermissionDenied)
    async def permission_handler(_req: Any, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


app = create_app()
