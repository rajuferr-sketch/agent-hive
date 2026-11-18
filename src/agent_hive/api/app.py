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
* GET  /api/messages?agent=             message history
* GET  /api/memory/{scope}?q=&agent=    read/search memory
* POST /api/memory/shared               write to shared memory
* POST /api/system/settings             toggle mock mode
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
    DirectMessage,
    MissionRequest,
    SettingsUpdate,
    SharedMemoryWrite,
    TaskCreate,
)
from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.hive import Hive

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
        version="1.0.0",
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
