"""Environment diagnostics shared by the CLI and scripts/diagnose.py.

Checks:
1. interpreter & package importability;
2. configuration integrity (system.yaml + all agent YAMLs);
3. database connectivity (without leaking the URL);
4. agent role resolution (every YAML role has a class);
5. provider health probes (best-effort, 10 s timeout each).

Returns True when the core is healthy. Never prints secrets.
"""

from __future__ import annotations

import asyncio
import platform
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from agent_hive.version import __version__

console = Console()


async def _db_check() -> tuple[bool, str]:
    try:
        from sqlalchemy import text

        from agent_hive.db.base import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True, "connected"
    except Exception as exc:  # noqa: BLE001 — diagnostics must not raise
        return False, str(exc)[:160]


async def _provider_checks() -> list[tuple[str, bool, str]]:
    from agent_hive.config.loader import list_agent_names, load_agent_config
    from agent_hive.providers.factory import resolve_provider

    seen: dict[str, Any] = {}
    results: list[tuple[str, bool, str]] = []
    for name in list_agent_names():
        cfg = load_agent_config(name)
        for p in cfg.providers:
            key = f"{p.type}"
            if key in seen:
                continue
            try:
                provider = resolve_provider(p)
                healthy = await asyncio.wait_for(provider.health_check(), timeout=10)
                await provider.aclose()
                results.append((f"{p.type} ({p.model})", healthy,
                                "reachable" if healthy else "unreachable"))
            except Exception as exc:  # noqa: BLE001
                results.append((f"{p.type} ({p.model})", False, str(exc)[:120]))
            seen[key] = True
    return results


async def run_diagnostics() -> bool:
    table = Table(title=f"AgentHive {__version__} — diagnostics")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    ok_all = True

    # 1. interpreter
    py_ok = sys.version_info >= (3, 11)
    ok_all &= py_ok
    table.add_row("python", "OK" if py_ok else "FAIL",
                  f"{platform.python_version()} on {platform.system()}")

    # 2. package imports
    try:
        import agent_hive  # noqa: F401
        import_ok, import_detail = True, "importable"
    except Exception as exc:  # noqa: BLE001
        import_ok, import_detail = False, str(exc)[:160]
    ok_all &= import_ok
    table.add_row("package", "OK" if import_ok else "FAIL", import_detail)

    # 3. configuration integrity
    try:
        from agent_hive.config.loader import list_agent_names, load_agent_config, load_system_config
        load_system_config()
        names = list_agent_names()
        from agent_hive.agents.roles import ROLE_REGISTRY
        unresolved = [
            n for n in names
            if load_agent_config(n).role not in ROLE_REGISTRY
        ]
        cfg_ok, cfg_detail = not unresolved, f"{len(names)} agents, unresolved roles: {unresolved or 'none'}"
    except Exception as exc:  # noqa: BLE001
        cfg_ok, cfg_detail = False, str(exc)[:160]
    ok_all &= cfg_ok
    table.add_row("configuration", "OK" if cfg_ok else "FAIL", cfg_detail)

    # 4. database
    db_ok, db_detail = await _db_check()
    ok_all &= db_ok
    table.add_row("database", "OK" if db_ok else "FAIL", db_detail)

    console.print(table)

    # 5. providers (informational, not fatal)
    providers = await _provider_checks()
    ptable = Table(title="Providers")
    ptable.add_column("Provider")
    ptable.add_column("Health")
    ptable.add_column("Detail")
    for label, healthy, detail in providers:
        ptable.add_row(label, "OK" if healthy else "DOWN", detail)
    console.print(ptable)
    console.print("[dim]Note: DOWN providers are non-fatal when ALLOW_MOCK=true "
                  "(deterministic mock fallback).[/dim]")
    return bool(ok_all)
