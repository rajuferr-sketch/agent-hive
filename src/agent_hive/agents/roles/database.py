"""Database Agent — schema design, migrations, indexes and SQL."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class DatabaseAgent(BaseAgent):
    """Designs relational schemas, migrations and access paths."""

    ROLE = "database"
    CAPABILITIES = ["database", "optimization", "architecture"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Database agent you must:\n"
            '- return "tables": a list of {"name", "columns", "indexes"} '
            "objects with columns as field-type descriptions;\n"
            "- define primary and foreign keys for every table;\n"
            "- propose indexes for the stated query patterns only;\n"
            "- emit migrations as idempotent, reversible SQL.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        parsed = self._parse_json(completion.text)
        if isinstance(parsed, dict) and "tables" in parsed:
            tables: list[dict[str, Any]] = []
            for item in parsed.get("tables", []):
                if not isinstance(item, dict):
                    continue
                columns = [
                    str(c) for c in (item.get("columns") or []) if c
                ][:50]
                indexes = [
                    str(i) for i in (item.get("indexes") or []) if i
                ][:20]
                tables.append(
                    {
                        "name": str(item.get("name", ""))[:120],
                        "columns": columns,
                        "indexes": indexes,
                    }
                )
            parsed["tables"] = tables[:30]
            completion.text = json.dumps(parsed, ensure_ascii=False, indent=2)
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        parsed = self._parse_json(text)
        if isinstance(parsed, dict) and not parsed.get("tables"):
            check["notes"].append("schema design missing 'tables' list")
            check["passed"] = False
        return check
