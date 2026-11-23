"""The 18 universal MCP tools — the single capability surface of AgentHive.

Every connector (MCP, OpenAI-compatible, Ollama-compatible, REST, WS,
generic tool-calling) exposes exactly this set. Each tool has:

* a unique name and a precise description;
* a JSON schema validated before execution (:mod:`agent_hive.mcp.schema`);
* a required permission scope checked against the caller identity;
* a configurable execution timeout (registry-enforced);
* structured success/error responses and audit logging.

Tools are thin async wrappers over the Hive subsystems — they contain no
business logic of their own, so REST/MCP/WS behave identically.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_hive.core.errors import AgentError, PermissionDenied
from agent_hive.core.logging import get_logger
from agent_hive.db.models import Task
from agent_hive.mcp.schema import SchemaError, validate_schema
from agent_hive.security.sanitize import sanitize_input
from agent_hive.security.tokens import TokenIdentity

if TYPE_CHECKING:  # pragma: no cover
    from agent_hive.hive import Hive
    from agent_hive.universal_memory.universal import UniversalMemoryManager

log = get_logger("agent_hive.mcp.tools")

Handler = Callable[["ToolContext", dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolContext:
    hive: Hive
    umemory: UniversalMemoryManager
    identity: TokenIdentity | None = None
    client: str = ""


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    scope: str
    timeout_s: int
    handler: Handler
    annotations: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Validates, authorizes, times and executes tool calls."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name '{spec.name}'")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def manifest(self) -> list[dict[str, Any]]:
        """MCP ``tools/list`` payload (name, description, inputSchema)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.schema,
                "annotations": t.annotations,
            }
            for t in sorted(self._tools.values(), key=lambda s: s.name)
        ]

    async def call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        ctx: ToolContext,
        identity: TokenIdentity | None = None,
        client: str = "",
        timeout_override: int | None = None,
    ) -> dict[str, Any]:
        """Execute a tool; always returns a structured envelope."""
        started = time.monotonic()
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False,
                    "error": {"code": "unknown_tool",
                              "message": f"Unknown tool '{name}'"}}
        effective_identity = identity or ctx.identity
        if effective_identity is None:
            return {"ok": False,
                    "error": {"code": "unauthenticated",
                              "message": "No caller identity on this session"}}
        if not effective_identity.has_scope(tool.scope):
            return {"ok": False,
                    "error": {"code": "permission_denied",
                              "message": (
                                  f"scope '{tool.scope}' required for tool "
                                  f"'{name}' — caller '{effective_identity.subject}' "
                                  f"has {effective_identity.scopes}"
                              )}}
        clean_args = sanitize_input(args or {})
        try:
            validate_schema(clean_args, tool.schema)
        except SchemaError as exc:
            return {"ok": False,
                    "error": {"code": "invalid_params", "message": str(exc)}}
        timeout = timeout_override or tool.timeout_s
        exec_ctx = ToolContext(
            hive=ctx.hive, umemory=ctx.umemory,
            identity=effective_identity, client=client or ctx.client,
        )
        try:
            data = await asyncio.wait_for(
                tool.handler(exec_ctx, clean_args), timeout=max(1, timeout)
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            log.info("tool '%s' ok client=%s duration=%dms", name, client, duration_ms)
            return {"ok": True, "data": data, "tool": name,
                    "duration_ms": duration_ms}
        except asyncio.TimeoutError:
            log.warning("tool '%s' timed out after %ss", name, timeout)
            return {"ok": False, "tool": name,
                    "error": {"code": "timeout",
                              "message": f"tool exceeded {timeout}s budget"}}
        except PermissionDenied as exc:
            return {"ok": False, "tool": name,
                    "error": {"code": "permission_denied", "message": str(exc)}}
        except AgentError as exc:
            log.warning("tool '%s' agent error: %s", name, exc)
            return {"ok": False, "tool": name,
                    "error": {"code": "tool_error", "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 — report, never crash session
            log.exception("tool '%s' crashed", name)
            return {"ok": False, "tool": name,
                    "error": {"code": "internal_error", "message": str(exc)[:300]}}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _agent_list(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    runtime = ctx.hive.runtime
    return {
        "agents": runtime.describe(),
        "count": len(runtime.agents),
        "registry": await ctx.hive.agents_manager.registry(),
    }


async def _agent_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args["name"])
    agent = ctx.hive.runtime.agents.get(name)
    if agent is None:
        raise AgentError(f"Agent '{name}' not found")
    entry = next(
        d for d in ctx.hive.runtime.describe() if d["name"] == name
    )
    memories = await ctx.hive.memory.list_scope("individual", agent=name, limit=10)
    entry["recent_memories"] = [
        {"key": m.key, "version": m.version} for m in memories
    ]
    entry["health"] = await ctx.hive.agents_manager.health(name)
    return entry


async def _agent_execute(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    session_id = str(args.get("session_id") or "global")
    report = await ctx.hive.run_mission(
        str(args["instruction"]),
        mode=args.get("mode"),
        title=args.get("title"),
    )
    # Cross-client continuity: the mission is discoverable from shared memory.
    await ctx.umemory.save(
        memory_type="task",
        key=f"mission:{report.get('mission_id')}",
        content=f"{report.get('title', '')}: {str(report.get('deliverable', ''))[:400]}",
        value={
            "mission_id": report.get("mission_id"),
            "status": "completed",
            "quality": report.get("quality"),
            "agents": report.get("agents"),
        },
        session_id=session_id,
        created_by_client=ctx.client or "mcp",
    )
    return report


async def _agent_create_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = await ctx.hive.tasks.create(
        title=str(args["title"]),
        description=str(args.get("description") or ""),
        payload=args.get("payload") or {},
        agent_name=args.get("agent_name"),
        priority=int(args.get("priority") or 5),
        depends_on=args.get("depends_on") or [],
        created_by=ctx.identity.subject if ctx.identity else "tool",
    )
    await ctx.umemory.save(
        memory_type="task",
        key=f"task:{task.id}",
        content=f"created task '{task.title}' (status={task.status})",
        value={"task_id": task.id, "status": task.status, "agent": task.agent_name},
        user_id=str(args.get("user_id") or "default"),
        project_id=str(args.get("project_id") or "default"),
        session_id=str(args.get("session_id") or "global"),
        created_by_client=ctx.client or "mcp",
    )
    return {"task_id": task.id, "status": task.status, "agent": task.agent_name}


async def _agent_assign_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args["task_id"])
    task = await ctx.hive.tasks.get(task_id)
    if task is None:
        raise AgentError(f"Task '{task_id}' not found")
    agent_name = args.get("agent_name")
    if agent_name:
        if agent_name not in ctx.hive.runtime.agents:
            raise AgentError(f"Agent '{agent_name}' not found")
        await ctx.hive.tasks.mark_assigned(task_id, str(agent_name))
        assigned = agent_name
    else:
        assigned = ctx.hive.runtime.best_agent_for()
        if not assigned:
            raise AgentError("No idle agent available for assignment")
        await ctx.hive.tasks.mark_assigned(task_id, assigned)
    return {"task_id": task_id, "assigned_to": assigned}


async def _agent_cancel_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = await ctx.hive.tasks.cancel(str(args["task_id"]))
    if task is None:
        raise AgentError("Task not cancellable (unknown id or terminal state)")
    return {"task_id": task.id, "status": task.status}


async def _agent_monitor_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args["task_id"])
    wait_s = float(args.get("wait_s") or 0)
    deadline = time.monotonic() + min(wait_s, 120.0)
    while True:
        task = await ctx.hive.tasks.get(task_id)
        if task is None:
            raise AgentError(f"Task '{task_id}' not found")
        if task.status in Task.TERMINAL_STATUSES or time.monotonic() >= deadline:
            return {
                "task_id": task.id, "status": task.status,
                "agent": task.agent_name, "attempts": task.attempts,
                "result": task.result, "error": task.error,
            }
        await asyncio.sleep(0.25)


async def _agent_get_result(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = await ctx.hive.tasks.get(str(args["task_id"]))
    if task is None:
        raise AgentError("Task not found")
    return {
        "task_id": task.id, "status": task.status, "result": task.result,
        "error": task.error, "agent": task.agent_name,
        "completed_at": task.completed_at,
    }


async def _agent_get_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    tasks = await ctx.hive.tasks.list(
        status=args.get("status"),
        mission_id=args.get("mission_id"),
        limit=int(args.get("limit") or 50),
    )
    return {
        "tasks": [
            {"id": t.id, "title": t.title, "agent": t.agent_name,
             "status": t.status, "attempts": t.attempts, "mission_id": t.mission_id}
            for t in tasks
        ],
        "count": len(tasks),
    }


async def _agent_search_memory(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    results = await ctx.umemory.search(
        str(args["query"]),
        memory_type=args.get("memory_type"),
        user_id=args.get("user_id"),
        project_id=args.get("project_id"),
        session_id=args.get("session_id"),
        limit=int(args.get("limit") or 10),
    )
    return {"results": results, "count": len(results)}


async def _agent_save_memory(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await ctx.umemory.save(
        memory_type=str(args["memory_type"]),
        key=str(args["key"]),
        content=str(args["content"]),
        value=args.get("value") or {},
        user_id=str(args.get("user_id") or "default"),
        project_id=str(args.get("project_id") or "default"),
        session_id=str(args.get("session_id") or "global"),
        tags=[str(t) for t in (args.get("tags") or [])],
        access=str(args.get("access") or "project"),
        ttl_seconds=args.get("ttl_seconds"),
        created_by_client=ctx.client or "mcp",
    )


async def _agent_update_memory(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await ctx.umemory.update(
        memory_id=args.get("memory_id"),
        key=args.get("key"),
        memory_type=args.get("memory_type"),
        content=str(args["content"]),
        value=args.get("value"),
        user_id=str(args.get("user_id") or "default"),
        project_id=str(args.get("project_id") or "default"),
        session_id=str(args.get("session_id") or "global"),
        tags=[str(t) for t in (args.get("tags") or [])] if args.get("tags") else None,
        created_by_client=ctx.client or "mcp",
    )


async def _agent_get_system_status(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    info = ctx.hive.status()
    info["task_stats"] = await ctx.hive.tasks.stats()
    info["universal_memory"] = await ctx.umemory.stats()
    return info


async def _agent_run_diagnostics(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    from agent_hive.db.base import get_engine

    checks: list[dict[str, Any]] = []

    # 1. database
    try:
        from sqlalchemy import text

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks.append({"check": "database", "ok": True, "detail": "connected"})
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "database", "ok": False, "detail": str(exc)[:160]})

    # 2. agents
    runtime = ctx.hive.runtime
    checks.append({
        "check": "agents", "ok": len(runtime.agents) > 0,
        "detail": f"{len(runtime.agents)} loaded",
    })

    # 3. scheduler
    sched_alive = bool(ctx.hive.scheduler._loop_task and not ctx.hive.scheduler._loop_task.done())
    checks.append({"check": "scheduler", "ok": sched_alive, "detail": "loop task state"})

    # 4. universal memory reachability + TTL hygiene
    try:
        stats = await ctx.umemory.stats()
        purged = await ctx.umemory.purge_expired()
        checks.append({"check": "universal_memory", "ok": True,
                       "detail": f"{stats['total']} records, {purged} expired purged"})
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "universal_memory", "ok": False, "detail": str(exc)[:160]})

    # 5. provider configuration (no secret material shown)
    from agent_hive.config.loader import list_agent_names, load_agent_config

    provider_report: list[str] = []
    try:
        for name in list_agent_names()[:5]:
            cfg = load_agent_config(name)
            for p in cfg.providers:
                env_set = bool(p.api_key_env and os.getenv(p.api_key_env))
                provider_report.append(f"{name}:{p.type}:{'key-ok' if env_set else 'no-key'}")
    except Exception as exc:  # noqa: BLE001
        provider_report.append(f"config-error:{exc}")
    checks.append({"check": "providers", "ok": True,
                   "detail": provider_report[:10] or "no providers configured"})

    # 6. task backlog
    stats = await ctx.hive.tasks.stats()
    backlog = stats.get("queued", 0) + stats.get("pending", 0) + stats.get("blocked", 0)
    checks.append({"check": "task_backlog", "ok": backlog < 100, "detail": str(stats)})

    healthy = all(c["ok"] for c in checks)
    return {"healthy": healthy, "checks": checks}


async def _agent_run_tests(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Run the pytest suite in an isolated subprocess (bounded)."""
    if os.getenv("AGENT_HIVE_ENABLE_TESTS_TOOL", "true").lower() in ("0", "false", "no"):
        raise PermissionDenied("agent_run_tests is disabled by configuration")
    path = str(args.get("path") or "tests")
    timeout = min(int(args.get("timeout_s") or 300), 600)
    cmd = [sys.executable, "-m", "pytest", path, "-q", "--no-header", "-p", "no:cacheprovider"]
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=_project_root(),
            ),
            timeout=timeout,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise
    except asyncio.TimeoutError:
        return {"passed": False, "detail": f"pytest exceeded {timeout}s budget"}
    except FileNotFoundError:
        return {"passed": False, "detail": "pytest not available in this environment"}
    out = (stdout or b"").decode("utf-8", errors="replace")
    tail = out.strip().splitlines()[-15:]
    passed_line = next(
        (ln for ln in reversed(tail) if "passed" in ln or "no tests ran" in ln), ""
    )
    return {
        "passed": proc.returncode == 0,
        "returncode": proc.returncode,
        "summary": passed_line,
        "tail": tail,
    }


def _project_root() -> str:
    # tests/ lives at the repository root (two levels above src/agent_hive).
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


async def _agent_generate_report(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    scope = str(args.get("scope") or "system")
    lines: list[str] = ["# AgentHive Report", ""]
    if scope == "mission":
        mission_id = str(args["mission_id"])
        tasks = await ctx.hive.tasks.list(mission_id=mission_id, limit=200)
        if not tasks:
            raise AgentError(f"Mission '{mission_id}' not found")
        lines.append(f"## Mission {mission_id}")
        lines.append("")
        lines.append("| Task | Agent | Status | Attempts |")
        lines.append("| --- | --- | --- | --- |")
        for t in tasks:
            lines.append(f"| {t.title} | {t.agent_name or '—'} | {t.status} | {t.attempts} |")
    else:
        info = ctx.hive.status()
        tstats = await ctx.hive.tasks.stats()
        mstats = await ctx.umemory.stats()
        lines += [
            "## System",
            f"- Version: {info['version']}",
            f"- Agents loaded: {info['agents_loaded']}",
            f"- Mock allowed: {info['mock_allowed']}",
            f"- Database: {info['database']}",
            "",
            "## Tasks",
            f"- {tstats}",
            "",
            "## Universal memory",
            f"- {mstats}",
        ]
    return {"format": "markdown", "report": "\n".join(lines)}


async def _agent_manage_workflow(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Create / inspect / cancel a multi-task workflow (DAG of tasks)."""
    action = str(args["action"])
    if action == "create":
        steps = args.get("tasks") or []
        if not steps:
            raise AgentError("workflow 'create' requires a non-empty 'tasks' list")
        workflow_id = args.get("workflow_id") or f"wf-{int(time.time())}"
        ids: list[str] = []
        prev: str | None = None
        sequential = bool(args.get("sequential", True))
        for i, step in enumerate(steps):
            depends = [prev] if (sequential and prev) else list(step.get("depends_on") or [])
            task = await ctx.hive.tasks.create(
                title=str(step.get("title") or f"{workflow_id} step {i + 1}"),
                description=str(step.get("description") or ""),
                agent_name=step.get("agent_name"),
                priority=int(step.get("priority") or 5),
                depends_on=depends,
                created_by=ctx.identity.subject if ctx.identity else "workflow",
            )
            ids.append(task.id)
            prev = task.id
        await ctx.umemory.save(
            memory_type="operational",
            key=f"workflow:{workflow_id}",
            content=f"workflow with {len(ids)} tasks",
            value={"workflow_id": workflow_id, "task_ids": ids},
            created_by_client=ctx.client or "mcp",
        )
        return {"workflow_id": workflow_id, "task_ids": ids, "count": len(ids)}
    if action == "status":
        wf_id = args.get("workflow_id")
        if not wf_id:
            raise AgentError("workflow 'status' requires 'workflow_id'")
        rec = await ctx.umemory.get(key=f"workflow:{wf_id}", memory_type="operational")
        if not rec:
            raise AgentError(f"Workflow '{wf_id}' not found")
        task_ids = list((rec.get("value") or {}).get("task_ids") or [])
        states = []
        for tid in task_ids:
            t = await ctx.hive.tasks.get(tid)
            states.append({"task_id": tid, "status": t.status if t else "unknown"})
        return {"workflow_id": wf_id, "tasks": states,
                "completed": all(s["status"] == "completed" for s in states)}
    if action == "cancel":
        wf_id = args.get("workflow_id")
        if not wf_id:
            raise AgentError("workflow 'cancel' requires 'workflow_id'")
        rec = await ctx.umemory.get(key=f"workflow:{wf_id}", memory_type="operational")
        if not rec:
            raise AgentError(f"Workflow '{wf_id}' not found")
        cancelled = []
        for tid in (rec.get("value") or {}).get("task_ids", []):
            t = await ctx.hive.tasks.cancel(tid)
            if t:
                cancelled.append(t.id)
        return {"workflow_id": wf_id, "cancelled": cancelled}
    raise AgentError(f"Unknown workflow action '{action}' (create|status|cancel)")


async def _agent_get_capabilities(ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    from agent_hive.providers.presets import provider_presets

    return {
        "tools": MANIFEST_NAMES,
        "transports": ["mcp-streamable-http", "mcp-stdio", "rest", "websocket",
                       "openai-compatible", "ollama-compatible", "generic-tool-calling"],
        "agents": sorted(ctx.hive.runtime.agents),
        "provider_presets": provider_presets(),
        "memory_types": ["episodic", "semantic", "operational", "task", "decision"],
        "github_modes": ["read_only", "assisted", "semi_autonomous", "autonomous"],
    }


MANIFEST_NAMES = [
    "agent_list", "agent_status", "agent_execute", "agent_create_task",
    "agent_assign_task", "agent_cancel_task", "agent_monitor_task",
    "agent_get_result", "agent_get_history", "agent_search_memory",
    "agent_save_memory", "agent_update_memory", "agent_get_system_status",
    "agent_run_diagnostics", "agent_run_tests", "agent_generate_report",
    "agent_manage_workflow", "agent_get_capabilities",
]

_TASK_REF = {"type": "string", "minLength": 1}

# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------


def build_registry() -> ToolRegistry:
    """Register all 18 tools (idempotent: returns a fresh registry)."""
    reg = ToolRegistry()
    R = ToolSpec

    reg.register(R(
        name="agent_list",
        description=("List every specialized agent available in the hive with "
                     "role, capabilities, provider chain and current status."),
        schema={"type": "object", "properties": {}},
        scope="agents:read", timeout_s=15, handler=_agent_list,
    ))
    reg.register(R(
        name="agent_status",
        description=("Detailed status of one agent: health probe of its provider "
                     "chain, busy state, recent individual memories."),
        schema={"type": "object", "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1}}},
        scope="agents:read", timeout_s=30, handler=_agent_status,
    ))
    reg.register(R(
        name="agent_execute",
        description=("Execute a natural-language instruction as a full mission: "
                     "the Master Agent analyzes it, selects agents, plans and "
                     "delegates tasks, runs them (parallel when beneficial), "
                     "verifies quality, revises if needed and returns the "
                     "deliverable. This is the main entry point for AI clients."),
        schema={"type": "object", "required": ["instruction"],
                "properties": {
                    "instruction": {"type": "string", "minLength": 1, "maxLength": 20000},
                    "mode": {"type": "string", "enum": ["A", "B", "C", "simple", "adaptive", "complex"]},
                    "title": {"type": "string", "maxLength": 200},
                    "session_id": {"type": "string", "maxLength": 64},
                }},
        scope="agents:execute", timeout_s=600, handler=_agent_execute,
    ))
    reg.register(R(
        name="agent_create_task",
        description=("Create a single task in the hive queue without going "
                     "through the Master Agent. Supports priority, an explicit "
                     "agent and dependencies on other task ids."),
        schema={"type": "object", "required": ["title"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 256},
                    "description": {"type": "string", "maxLength": 5000},
                    "agent_name": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 9},
                    "depends_on": {"type": "array", "items": _TASK_REF},
                    "payload": {"type": "object"},
                    "user_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "session_id": {"type": "string"},
                }},
        scope="tasks:write", timeout_s=30, handler=_agent_create_task,
    ))
    reg.register(R(
        name="agent_assign_task",
        description=("Assign an existing task to a named agent, or to the best "
                     "available idle agent when agent_name is omitted."),
        schema={"type": "object", "required": ["task_id"],
                "properties": {
                    "task_id": _TASK_REF,
                    "agent_name": {"type": "string"},
                }},
        scope="tasks:write", timeout_s=30, handler=_agent_assign_task,
    ))
    reg.register(R(
        name="agent_cancel_task",
        description="Cancel a pending/queued/assigned task by id (running tasks cannot be cancelled).",
        schema={"type": "object", "required": ["task_id"],
                "properties": {"task_id": _TASK_REF}},
        scope="tasks:cancel", timeout_s=15, handler=_agent_cancel_task,
    ))
    reg.register(R(
        name="agent_monitor_task",
        description=("Monitor a task: returns immediately with current state, or "
                     "polls up to wait_s seconds until it reaches a terminal "
                     "status (completed/failed/cancelled)."),
        schema={"type": "object", "required": ["task_id"],
                "properties": {
                    "task_id": _TASK_REF,
                    "wait_s": {"type": "number", "minimum": 0, "maximum": 120},
                }},
        scope="tasks:read", timeout_s=150, handler=_agent_monitor_task,
    ))
    reg.register(R(
        name="agent_get_result",
        description="Fetch the structured result (and error, if any) of a task.",
        schema={"type": "object", "required": ["task_id"],
                "properties": {"task_id": _TASK_REF}},
        scope="tasks:read", timeout_s=15, handler=_agent_get_result,
    ))
    reg.register(R(
        name="agent_get_history",
        description="List historical tasks filtered by status and/or mission id.",
        schema={"type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "mission_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                }},
        scope="tasks:read", timeout_s=30, handler=_agent_get_history,
    ))
    reg.register(R(
        name="agent_search_memory",
        description=("Search the universal shared memory (episodic/semantic/"
                     "operational/task/decision) with blended full-text + vector "
                     "ranking, optionally scoped to user/project/session. This "
                     "is how a client picks up work another client started."),
        schema={"type": "object", "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "memory_type": {"type": "string",
                                    "enum": ["episodic", "semantic", "operational", "task", "decision"]},
                    "user_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                }},
        scope="memory:read", timeout_s=30, handler=_agent_search_memory,
    ))
    reg.register(R(
        name="agent_save_memory",
        description=("Persist a record to the universal shared memory so any "
                     "connected client can retrieve it later. Deduplicates "
                     "identical content, versions changes, supports TTL and "
                     "access levels (private/project/public)."),
        schema={"type": "object",
                "required": ["memory_type", "key", "content"],
                "properties": {
                    "memory_type": {"type": "string",
                                    "enum": ["episodic", "semantic", "operational", "task", "decision"]},
                    "key": {"type": "string", "minLength": 1, "maxLength": 256},
                    "content": {"type": "string", "minLength": 1, "maxLength": 100000},
                    "value": {"type": "object"},
                    "user_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "access": {"type": "string", "enum": ["private", "project", "public"]},
                    "ttl_seconds": {"type": "integer", "minimum": 0},
                }},
        scope="memory:write", timeout_s=30, handler=_agent_save_memory,
    ))
    reg.register(R(
        name="agent_update_memory",
        description=("Update an existing memory record by id or namespaced key; "
                     "the version counter increments on real changes."),
        schema={"type": "object", "required": ["content"],
                "properties": {
                    "memory_id": {"type": "string"},
                    "key": {"type": "string"},
                    "memory_type": {"type": "string",
                                    "enum": ["episodic", "semantic", "operational", "task", "decision"]},
                    "content": {"type": "string", "minLength": 1, "maxLength": 100000},
                    "value": {"type": "object"},
                    "user_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                }},
        scope="memory:write", timeout_s=30, handler=_agent_update_memory,
    ))
    reg.register(R(
        name="agent_get_system_status",
        description="Aggregate system status: version, agents, tasks, universal memory, database.",
        schema={"type": "object", "properties": {}},
        scope="system:read", timeout_s=30, handler=_agent_get_system_status,
    ))
    reg.register(R(
        name="agent_run_diagnostics",
        description=("Run health diagnostics: database, agents, scheduler, "
                     "universal memory (with TTL purge), provider configuration "
                     "and task backlog. Returns per-check ok/detail."),
        schema={"type": "object", "properties": {}},
        scope="system:diagnose", timeout_s=60, handler=_agent_run_diagnostics,
    ))
    reg.register(R(
        name="agent_run_tests",
        description=("Run the project's pytest suite in an isolated subprocess "
                     "with a hard time budget. Returns pass/fail, the pytest "
                     "summary line and the output tail."),
        schema={"type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "timeout_s": {"type": "integer", "minimum": 5, "maximum": 600},
                }},
        scope="system:tests", timeout_s=600, handler=_agent_run_tests,
    ))
    reg.register(R(
        name="agent_generate_report",
        description=("Generate a markdown report: 'system' scope aggregates "
                     "agents/tasks/memory; 'mission' scope tabulates one "
                     "mission's tasks."),
        schema={"type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["system", "mission"]},
                    "mission_id": {"type": "string"},
                }},
        scope="reports:read", timeout_s=60, handler=_agent_generate_report,
    ))
    reg.register(R(
        name="agent_manage_workflow",
        description=("Manage multi-step workflows: 'create' builds an ordered "
                     "task DAG (sequential by default), 'status' reports every "
                     "task state, 'cancel' cancels all non-terminal tasks."),
        schema={"type": "object", "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["create", "status", "cancel"]},
                    "workflow_id": {"type": "string"},
                    "sequential": {"type": "boolean"},
                    "tasks": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "agent_name": {"type": "string"},
                            "priority": {"type": "integer", "minimum": 1, "maximum": 9},
                            "depends_on": {"type": "array", "items": _TASK_REF},
                        },
                    }},
                }},
        scope="workflows:manage", timeout_s=60, handler=_agent_manage_workflow,
    ))
    reg.register(R(
        name="agent_get_capabilities",
        description=("Discovery: the 18 tool names, supported transports, agent "
                     "roster, provider presets (cloud + local), memory types and "
                     "GitHub integration modes."),
        schema={"type": "object", "properties": {}},
        scope="system:read", timeout_s=15, handler=_agent_get_capabilities,
    ))

    missing = set(MANIFEST_NAMES) - set(reg.names())
    if missing:
        raise RuntimeError(f"tool registry incomplete: missing {sorted(missing)}")
    return reg


_REGISTRY_SINGLETON: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Process-wide registry singleton (Hive, API and CLI share it)."""
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = build_registry()
    return _REGISTRY_SINGLETON
