#!/usr/bin/env python3
"""AgentHive — environment diagnostics (standalone, no external deps).

Run from the repository root::

    python scripts/diagnose.py

Checks, in order:

1. Runtime: Python version, platform, ``agent_hive`` version.
2. Settings summary: database URL *scheme* only (never credentials),
   ALLOW_MOCK, CONFIG_DIR, MAX_CONCURRENCY.
3. Database connectivity: ``SELECT 1`` through the async engine.
4. Agent configuration: number of YAML agent files and loadability.
5. Provider health: one probe per unique provider type, 10s timeout each.

Exit code: ``0`` if the core is healthy (DB reachable + agent configs
loadable), ``1`` otherwise. Provider probe failures are reported but do not
fail the run. Never prints API keys or full connection strings.
"""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path

# --- Make the repository's `src/` layout importable when run standalone ------
# Must happen BEFORE any `agent_hive` import below.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

PROBE_TIMEOUT = 10.0  # seconds, per check

ok = "OK"
fail = "FAIL"


def _print_section(title: str) -> None:
    print()
    print(f"== {title} " + "-" * max(0, 62 - len(title)))


def _mask_url(url: str) -> str:
    """Return only the URL scheme (never credentials or host/port)."""
    return url.split("://", 1)[0] if "://" in url else "<unrecognized>"


def _check_runtime() -> None:
    _print_section("Runtime")
    print(f"Python     : {platform.python_version()} ({sys.executable})")
    print(f"Platform   : {platform.system()} {platform.release()} "
          f"({platform.machine()})")
    import agent_hive

    print(f"agent_hive : v{agent_hive.__version__} from "
          f"{Path(getattr(agent_hive, '__file__', '?')).parent}")


def _check_settings() -> None:
    from agent_hive.config.settings import get_settings

    _print_section("Settings (summary)")
    s = get_settings()
    print(f"database_url : {_mask_url(s.database_url)}  (credentials hidden)")
    print(f"allow_mock   : {s.allow_mock}")
    print(f"config_dir   : {s.config_dir}")
    print(f"max_concurrency : {s.max_concurrency}")


async def _check_db() -> bool:
    from sqlalchemy import text

    from agent_hive.db.base import dispose_engine, get_engine

    _print_section("Database connectivity")
    try:
        engine = get_engine()
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        print(f"[{ok}] {_mask_url(str(engine.url))} — SELECT 1 succeeded")
        return True
    except Exception as exc:  # noqa: BLE001 — diagnostics must never crash
        print(f"[{fail}] database probe failed after {PROBE_TIMEOUT:.0f}s: {exc}")
        print("       Check DATABASE_URL in .env and that the server is running.")
        return False
    finally:
        try:
            await dispose_engine()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


def _collect_provider_configs() -> tuple[list[str], dict[str, object], bool]:
    """Load all agent configs; return (names, first ProviderConfig per type, load_ok)."""
    from agent_hive.config.loader import list_agent_names, load_agent_config

    names = list_agent_names()
    _print_section("Agent configuration")
    if not names:
        print(f"(!) No agent configs found in configs/agents/ "
              f"({len(names)} files)")
        return names, {}, True

    print(f"Agents found: {len(names)}")
    per_type: dict[str, object] = {}
    load_ok = True
    for name in names:
        try:
            cfg = load_agent_config(name)
        except Exception as exc:  # noqa: BLE001
            load_ok = False
            print(f"[{fail}] cannot load agent '{name}': {exc}")
            continue
        print(f"  - {cfg.name:20s} role={cfg.role:15s} "
              f"providers={[p.type for p in cfg.providers]}")
        for p in cfg.providers:
            per_type.setdefault(p.type, p)
    return names, per_type, load_ok


async def _probe_provider(ptype: str, pcfg: object) -> tuple[str, bool, str]:
    """Probe one provider type; returns (type, ok, detail). Never prints keys."""
    from agent_hive.providers.factory import resolve_provider

    try:
        provider = resolve_provider(pcfg)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — unknown type / bad config
        return ptype, False, f"cannot construct provider: {exc}"
    try:
        await asyncio.wait_for(provider.health_check(), timeout=PROBE_TIMEOUT)
        return ptype, True, provider.name
    except TimeoutError:
        return ptype, False, f"health_check timed out after {PROBE_TIMEOUT:.0f}s"
    except Exception as exc:  # noqa: BLE001
        return ptype, False, str(exc)
    finally:
        try:
            await provider.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


async def _check_providers(per_type: dict[str, object]) -> bool:
    _print_section("Provider health")
    if not per_type:
        print("(!) No providers configured — skipping probes.")
        return True

    results = await asyncio.gather(
        *(_probe_provider(t, c) for t, c in per_type.items())
    )
    all_ok = True
    for ptype, probe_ok, detail in sorted(results):
        status = ok if probe_ok else fail
        if not probe_ok:
            all_ok = False
        print(f"[{status}] {ptype:20s} ({detail})")
    return all_ok


def main() -> int:
    # Windows consoles default to a non-UTF-8 code page; keep output safe.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

    print("==============================================================")
    print(" AgentHive — environment diagnostics")
    print("==============================================================")

    # All heavy imports happen here so a missing dependency produces one
    # clear message instead of a traceback.
    try:
        _check_runtime()
        _check_settings()
    except ImportError as exc:
        print()
        print(f"[{fail}] Missing dependency: {exc}")
        print("       Dependencies are not installed — run scripts/install "
              "first:")
        print("         - Linux/macOS: bash scripts/install.sh")
        print("         - Windows    : powershell scripts/install.ps1")
        return 1

    try:
        names, per_type, agents_ok = _collect_provider_configs()
    except ImportError as exc:
        print()
        print(f"[{fail}] Missing dependency: {exc}")
        print("       Run scripts/install first.")
        return 1
    except Exception as exc:  # noqa: BLE001 — broken config directory etc.
        print(f"[{fail}] agent configuration could not be read: {exc}")
        return 1

    db_ok = asyncio.run(_check_db())
    providers_ok = asyncio.run(_check_providers(per_type))

    _print_section("Result")
    core_ok = db_ok and agents_ok
    agents_status = (
        f"{ok} ({len(names)} configured)" if agents_ok and names
        else fail if not agents_ok
        else f"{ok} (none configured)"
    )
    print(f"python      : {ok}")
    print(f"database    : {ok if db_ok else fail}")
    print(f"agents      : {agents_status}")
    print(f"providers   : {ok if providers_ok else fail} (informational)")
    print()
    if core_ok:
        print(f"[{ok}] Core environment healthy.")
        if not providers_ok:
            print("(!) One or more providers unreachable — "
                  "agents will use fallbacks or the mock provider "
                  "(if ALLOW_MOCK=true).")
        return 0
    print(f"[{fail}] Core environment NOT healthy — see failures above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
