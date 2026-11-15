"""Development smoke test: full mission lifecycle in mock mode.

Run: .venv/Scripts/python.exe scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/smoke.db"
os.environ["ALLOW_MOCK"] = "true"

from agent_hive.hive import Hive  # noqa: E402


async def main() -> None:
    hive = Hive()
    await hive.startup()
    try:
        print(f"Agents loaded: {len(hive.runtime.agents)}")

        # Mode A — simple
        report = await hive.run_mission("Analyze the request: add a login endpoint to the API")
        print(f"[A] mode={report['mode']} agents={report['agents']} "
              f"tasks={len(report['tasks'])} quality={report['quality']['score']:.2f} "
              f"passed={report['quality']['passed']}")

        # Mode C — adaptive
        report = await hive.run_mission(
            "Design a small project management web application with a database, "
            "a REST API and unit tests",
            mode="C",
        )
        print(f"[C] mode={report['mode']} agents={report['agents']} "
              f"tasks={len(report['tasks'])} quality={report['quality']['score']:.2f} "
              f"passed={report['quality']['passed']} "
              f"completed={report['outcome'].get('completed')}")

        stats = await hive.tasks.stats()
        print("task stats:", stats)
        assert report["quality"]["score"] > 0
    finally:
        await hive.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
