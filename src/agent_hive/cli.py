"""Typer CLI — the operator's interface to AgentHive.

Commands:
  init-db     create the database schema
  start       run the API server (and the whole hive)
  run         delegate a one-shot mission and print the deliverable
  status      show system status
  agents      list the agent roster
  diagnose    run environment diagnostics
  recover     reset tasks orphaned by a previous crash
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from agent_hive.hive import Hive
from agent_hive.version import __version__

app = typer.Typer(
    name="agent-hive",
    help="Advanced multi-agent orchestration system: 1 Master Agent + 20 specialized agents.",
    no_args_is_help=True,
)
console = Console()


def _run(coro) -> Any:
    return asyncio.run(coro)


@app.command()
def init_db() -> None:
    """Create all database tables."""
    from agent_hive.db.base import create_all

    _run(create_all())
    console.print("[green]Database schema created[/green]")


@app.command()
def start(
    host: str | None = typer.Option(None, help="Bind host (default: API_HOST env)"),
    port: int | None = typer.Option(None, help="Bind port (default: API_PORT env)"),
) -> None:
    """Start the AgentHive API server."""
    import uvicorn

    from agent_hive.config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "agent_hive.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def run(
    text: str = typer.Argument(..., help="The mission request"),
    mode: str | None = typer.Option(
        None, "--mode", "-m", help="Force mode: A (simple), C (adaptive), B (collective)"
    ),
    title: str | None = typer.Option(None, "--title", help="Mission title"),
    output_json: bool = typer.Option(False, "--json", help="Full JSON report"),
    output_format: str = typer.Option("text", "--format", help="Output format: text|md|json"),
) -> None:
    """Delegate a mission to the Master Agent and print the deliverable."""

    async def _mission() -> None:
        hive = Hive()
        await hive.startup()
        try:
            report = await hive.run_mission(text, mode=mode, title=title)
        finally:
            await hive.shutdown()
        if output_json or output_format == "json":
            console.print_json(json.dumps(report, default=str, ensure_ascii=False))
            return
        if output_format == "md":
            console.print(f"# Mission {report['mission_id'][:8]} — mode {report['mode']}")
            console.print()
            console.print(f"**Quality:** {report['quality']['score']:.2f} "
                          f"({'PASSED' if report['quality']['passed'] else 'FAILED'})")
            console.print()
            console.print("## Agents")
            for a in report["agents"]:
                console.print(f"- {a}")
            console.print()
            console.print("## Tasks")
            console.print("| Title | Agent | Status | Attempts |")
            console.print("|---|---|---|---|")
            for t in report["tasks"]:
                console.print(f"| {t['title']} | {t['agent']} | {t['status']} | {t['attempts']} |")
            console.print()
            console.print("## Deliverable")
            console.print(report["deliverable"])
            return
        console.rule(f"[bold]Mission {report['mission_id'][:8]} — mode {report['mode']}")
        console.print(f"Agents involved: {', '.join(report['agents'])}")
        console.print(f"Quality score: {report['quality']['score']:.2f} "
                      f"({'[green]PASSED[/green]' if report['quality']['passed'] else '[red]FAILED[/red]'})")
        console.rule("[bold]Deliverable")
        console.print(report["deliverable"])

    _run(_mission())


@app.command()
def status() -> None:
    """Show a compact system status."""

    async def _status() -> None:
        hive = Hive()
        await hive.startup()
        try:
            info = hive.status()
            stats = await hive.tasks.stats()
            roster = hive.runtime.describe()
        finally:
            await hive.shutdown()
        table = Table(title=f"AgentHive {__version__} — {info['agents_loaded']} agents, "
                            f"db={info['database']}, mock={info['mock_allowed']}")
        table.add_column("Agent")
        table.add_column("Role")
        table.add_column("Providers")
        for a in roster:
            table.add_row(
                a["name"], a["role"],
                " → ".join(f"{p['provider']}:{p['model']}" for p in a["providers"]),
            )
        console.print(table)
        stats_table = Table(title="Task statistics")
        stats_table.add_column("Status")
        stats_table.add_column("Count")
        for status_name, count in sorted(stats.items()):
            stats_table.add_row(status_name, str(count))
        console.print(stats_table)

    _run(_status())


@app.command()
def agents() -> None:
    """List all configured agents."""

    async def _agents() -> None:
        hive = Hive()
        await hive.startup()
        try:
            roster = hive.runtime.describe()
        finally:
            await hive.shutdown()
        table = Table(title=f"{len(roster)} agents")
        table.add_column("Name")
        table.add_column("Role")
        table.add_column("Capabilities")
        table.add_column("Providers")
        for a in roster:
            table.add_row(
                a["name"], a["role"],
                ", ".join(a["capabilities"][:4]) + ("…" if len(a["capabilities"]) > 4 else ""),
                " → ".join(f"{p['provider']}:{p['model']}" for p in a["providers"]),
            )
        console.print(table)

    _run(_agents())


@app.command()
def recover() -> None:
    """Reset tasks orphaned by a crash/restart."""

    async def _recover() -> None:
        hive = Hive()
        await hive.startup()
        try:
            count = await hive.tasks.recover()
        finally:
            await hive.shutdown()
        console.print(f"[green]Recovered {count} orphaned task(s)[/green]")

    _run(_recover())


@app.command()
def diagnose() -> None:
    """Run environment diagnostics (same checks as scripts/diagnose.py)."""
    from agent_hive.diagnostics import run_diagnostics

    ok = _run(run_diagnostics())
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def demo(name: str = typer.Argument("logistica", help="Demo scenario: logistica | codice")) -> None:
    """Run a built-in demo mission."""
    scenarios = {
        "logistica": "Pianifica il tracking di una spedizione intermodale da Milano a Rotterdam: "
        "costi di trasporto, tempi, nodi logistici e rischi. Fornisci un piano completo.",
        "codice": "Scrivi una funzione Python che valida un codice fiscale italiano e "
        "aggiungi test pytest per i casi limite.",
    }
    text = scenarios.get(name, scenarios["logistica"])

    async def _demo() -> None:
        hive = Hive()
        await hive.startup()
        try:
            report = await hive.run_mission(text, mode=None)
        finally:
            await hive.shutdown()
        console.rule(f"[bold]Demo {name} — mode {report['mode']}")
        console.print(report["deliverable"])

    _run(_demo())


@app.command("repo-import")
def repo_import_cmd(url: str = typer.Argument(..., help="GitHub repository URL")) -> None:
    """Import and analyse a GitHub repository."""

    async def _run_import() -> None:
        from agent_hive.repository.intelligence import analyze_repository, import_github_repo

        info = await import_github_repo(url)
        report = analyze_repository(info["path"])
        console.print_json(json.dumps({**info, "analysis": report}, default=str, ensure_ascii=False))

    _run(_run_import())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
