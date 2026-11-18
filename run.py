#!/usr/bin/env python3
"""One-command entry point for AgentHive.

Usage:
    python run.py "your mission request"
    python run.py --mode B "complex request"
    python run.py --chat "request that the host AI will answer"
    python run.py demo logistica
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEMOS = {
    "logistica": (
        "Pianifica il tracking di una spedizione intermodale da Milano a Rotterdam: "
        "costi di trasporto, tempi, nodi logistici e rischi. Fornisci un piano completo."
    ),
    "codice": (
        "Scrivi una funzione Python che valida un codice fiscale italiano e "
        "aggiungi test pytest per i casi limite."
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="run.py")
    parser.add_argument("text", nargs="*", help="Mission request or 'demo <name>'")
    parser.add_argument("--mode", "-m", choices=["A", "B", "C"], default=None)
    parser.add_argument("--chat", action="store_true", help="Use the host (chat) AI provider")
    parser.add_argument("--format", choices=["text", "md", "json"], default="md")
    args = parser.parse_args()

    if args.chat:
        os.environ["AGENT_HIVE_HOST_MODE"] = "1"

    if args.text and args.text[0] == "demo":
        name = args.text[1] if len(args.text) > 1 else "logistica"
        text = DEMOS.get(name, DEMOS["logistica"])
    else:
        text = " ".join(args.text).strip()
        if not text:
            parser.print_help()
            return 1

    from agent_hive.cli import _run
    from agent_hive.hive import Hive

    async def _mission() -> int:
        hive = Hive()
        await hive.startup()
        try:
            report = await hive.run_mission(text, mode=args.mode)
        finally:
            await hive.shutdown()

        if args.format == "json":
            import json as _json
            print(_json.dumps(report, default=str, ensure_ascii=False, indent=2))
        elif args.format == "md":
            print(f"# Mission {report['mission_id'][:8]} — mode {report['mode']}")
            print()
            print(f"**Quality:** {report['quality']['score']:.2f} "
                  f"({'PASSED' if report['quality']['passed'] else 'FAILED'})")
            print()
            print("## Agents")
            for a in report["agents"]:
                print(f"- {a}")
            print()
            print("## Tasks")
            print("| Title | Agent | Status | Attempts |")
            print("|---|---|---|---|")
            for t in report["tasks"]:
                print(f"| {t['title']} | {t['agent']} | {t['status']} | {t['attempts']} |")
            print()
            print("## Deliverable")
            print(report["deliverable"])
        else:
            print(report["deliverable"])
        return 0

    return _run(_mission())


if __name__ == "__main__":
    raise SystemExit(main())
