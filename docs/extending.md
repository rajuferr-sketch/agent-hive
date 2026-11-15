# Extending AgentHive

AgentHive is designed so that the most common extensions require **no core changes**:

| Extension | Files to touch |
|---|---|
| Add agent #21 | 1 role module + 1 YAML |
| Modify an agent | 1 YAML (and optionally 1 role module) |
| Add a tool | 1 new function + registry call + YAML grant |
| Add a provider type | 1 provider class + `register_provider_type` |
| Tune orchestration | `configs/system.yaml` and/or `.env` |

---

## Add agent #21 (step by step)

The role registry is **auto-discovered**: every module in `src/agent_hive/agents/roles/` that defines a `BaseAgent` subclass with a distinct `ROLE` attribute is registered at import. Adding an agent therefore requires exactly two files.

### Step 1 — Role module

Create `src/agent_hive/agents/roles/data_engineer.py`:

```python
"""Data Engineer Agent — builds ETL pipelines and data models."""

from __future__ import annotations

import json
from typing import Any

from agent_hive.agents.base import BaseAgent
from agent_hive.db.models import Task
from agent_hive.providers.base import CompletionResult


class DataEngineerAgent(BaseAgent):
    ROLE = "data_engineer"
    CAPABILITIES = ["etl", "data_modeling", "pipelines"]

    def system_prompt(self) -> str:
        return (
            super().system_prompt()
            + "\nAs the Data Engineer you must:\n"
            "- return pipeline stages as explicit, ordered steps;\n"
            "- state idempotency and failure-handling for every stage;\n"
            "- emit SQL/Python artifacts in fenced code blocks.\n"
        )

    async def specialize(
        self, task: Task, completion: CompletionResult
    ) -> CompletionResult:
        # optional post-processing of the raw completion
        return completion

    async def self_check(self, task: Task, text: str) -> dict[str, Any]:
        check = await super().self_check(task, text)
        # optional role-specific validation
        return check
```

Rules the discovery loop enforces:

- The class must subclass `BaseAgent` and live in a module under `agents/roles/`.
- `ROLE` must be a non-empty string different from `"generic"` — it is the registry key.
- The first registered class wins for a given `ROLE` (duplicate roles are ignored with no error).

### Step 2 — Agent YAML

Create `configs/agents/data_engineer.yaml`:

```yaml
name: data_engineer
title: "Data Engineering Agent"
role: data_engineer
description: "Builds ETL pipelines, data models and batch/stream ingestion jobs."
capabilities: [etl, data_modeling, pipelines]
tools: [code_lint_py, file_read, json_validate]
memory:
  individual: true
  shared_access: true
  shared_write: true
providers:
  - type: openai_compatible
    model: gpt-4o-mini
    base_url_env: OPENAI_BASE_URL
    api_key_env: OPENAI_API_KEY
    params: {temperature: 0.2}
  - type: ollama
    model: llama3.2
    params: {temperature: 0.2}
  - type: mock
```

That's it. On the next startup the runtime logs:

```text
Role registry: 21 roles — [analyst, api, ..., data_engineer, ...]
Loaded 21 agents: [..., 'data_engineer', ...]
```

Verify:

```bash
agent-hive agents          # data_engineer appears in the roster
agent-hive diagnose        # "configuration: OK — 21 agents, unresolved roles: none"
curl http://127.0.0.1:8000/api/agents | jq '.[] | select(.name=="data_engineer")'
```

If the YAML declares a `role` with no matching class, startup fails fast with:

```text
ConfigError: Agent 'x' declares role 'y' but no role class is registered. Available: [...]
```

---

## Modify an existing agent

**Config-only changes** (no code):

- edit `configs/agents/<name>.yaml` — description, capabilities, tools, memory permissions, provider chain, sampling `params` — then restart the process (configs are read at startup; `configs/system.yaml` is operator-owned and read-only at runtime for the Master).

**Behaviour changes** — edit the role module in `src/agent_hive/agents/roles/<name>.py`:

| Hook | Effect |
|---|---|
| `system_prompt()` | Injected as the system message for every task |
| `specialize(task, completion)` | Post-process the raw completion (normalize JSON, extract artifacts) |
| `self_check(task, text)` | Add role-specific validation; returning `passed: False` feeds the Master's conflict detection and can trigger revision rounds |
| `ROLE` / `CAPABILITIES` | Registry key and capability matching — keep in sync with the YAML |

After changes: `make lint && make typecheck && pytest -q`, then restart.

---

## Add a tool

Tools are small async functions registered in the permission-controlled `ToolRegistry` (`tools/registry.py`). Registry keys are granted per agent via YAML `tools`.

```python
# src/agent_hive/tools/my_tools.py
from __future__ import annotations

from typing import Any

from agent_hive.tools.registry import REGISTRY


async def slugify(text: str) -> dict[str, Any]:
    """Convert text to a URL slug."""
    slug = "-".join(w for w in __import__("re").findall(r"\w+", (text or "").lower()))
    return {"slug": slug}


REGISTRY.register("slugify", "Convert text to a URL slug", "text", slugify)
```

Make sure the module is imported at startup so registration happens (e.g. add `import agent_hive.tools.my_tools` to `src/agent_hive/tools/__init__.py`), then grant it:

```yaml
# configs/agents/documenter.yaml (excerpt)
tools: [summarize, word_count, file_write, slugify]
```

**Families and gating** — the third `register` argument is the family:

| Family | Examples | Global gate |
|---|---|---|
| `text` | summarize, word_count, regex_extract, json_validate, dedupe_lines | none |
| `code` | code_lint_py, secret_scan | none |
| `file` | file_read, file_write | `ENABLE_FILE_TOOLS` (default `false`) |
| `http` | *(none built-in — reserved for your own tools)* | `ENABLE_HTTP_TOOLS` (default `false`) |

Safety expectations for tools: never import agent/orchestration code, never execute arbitrary code, keep them auditable and side-effect-sandboxed (see `file_read`/`file_write` for the `WORKSPACE_DIR` containment pattern).

> Note: no HTTP-family tool ships by default. `ENABLE_HTTP_TOOLS=true` merely unlocks the family for tools *you* register; agents cannot make network calls unless you add and grant such a tool.

---

## Add a provider type

Full walkthrough with a working `AnthropicProvider` example: see [providers.md](providers.md#adding-a-custom-provider-type). In short:

1. Subclass `LLMProvider` (`providers/base.py`): implement `async complete(messages, **params) -> CompletionResult`; optionally override `health_check()`, `configured()`, `aclose()`.
2. Register it: `register_provider_type("anthropic", AnthropicProvider)` from `providers/factory.py`.
3. Reference `type: anthropic` in any agent YAML chain.

`ProviderConfig` fields available to `from_config`: `type`, `model`, `base_url`, `base_url_env`, `api_key_env`, `params`. Respect the security rule: read secrets from environment variables by *name*.

---

## Tune orchestration thresholds

`configs/system.yaml`:

```yaml
simple_threshold: 0.25      # below: Mode A — one agent, independent
adaptive_threshold: 0.55    # below: Mode C — 2-10 agents
complex_threshold: 0.75     # informational; mode selection uses the two above
adaptive_min_agents: 3
adaptive_max_agents: 10
allow_cross_review: true
qa_required_score: 0.7
qa_code_check: true
qa_secret_scan: true
qa_requirement_check: true
```

| Knob | Effect |
|---|---|
| `simple_threshold` ↑ | More requests run in cheap single-agent Mode A |
| `adaptive_threshold` ↓ | More requests get the full collective pipeline (all 20 agents) |
| `adaptive_min_agents` | Minimum roster size for Mode C (verification + quality workstreams are added when the detected domains produce fewer) |
| `qa_required_score` ↑ | Stricter delivery bar → more revision rounds (max 2) |
| `qa_*_check` switches | Enable/disable completeness-adjacent checks (code AST, secret scan, requirement coverage) individually |

Complexity itself is computed in `orchestrator/planner.py` (`analyze()`): length factor (÷400 words, ×0.25), domain breadth (+0.05 per detected domain, cap 6), multi-part structure (+0.12), big-mission keywords (+0.15). You can extend `DOMAIN_KEYWORDS`/`DOMAIN_CAPABILITIES` there to teach the planner new domains — e.g. map `"data"` to your new `data_engineer` capabilities.

Task-runtime knobs live in `.env`: `MAX_CONCURRENCY`, `DEFAULT_TASK_TIMEOUT`, `DEFAULT_MAX_RETRIES`, `MEMORY_MAX_VERSIONS` (20), `MEMORY_RETENTION_DAYS` (90), `HEARTBEAT_INTERVAL` (15 s), `SCHEDULER_INTERVAL` (1 s).

---

## Scaling notes (read before deploying wide)

- **Concurrency is in-process.** The scheduler's `MAX_CONCURRENCY` semaphore bounds how many tasks execute concurrently *in one process*. Raise it (e.g. `MAX_CONCURRENCY=16`) to use more of a local LLM server's parallel capacity or more API throughput.
- **One runtime per database.** The queue is DB-backed (the `tasks` table), which makes it *crash-safe*, but the scheduler, mailboxes and event bus are **in-process**: two hive processes pointed at the same database would both poll and dispatch the same queued tasks (no row-level lease is claimed at dispatch time), and WebSocket/mailbox delivery is per-process. **Run exactly one hive per database/machine** in the current release.
- **Multiple machines / HA** — honest status: not supported yet. The queue would need cross-process coordination (e.g. `SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL, or a `LISTEN/NOTIFY`-based dispatcher) — this is the natural future work if you want to scale out. Scaling up on one box (bigger `MAX_CONCURRENCY`, faster model backend) is the supported path today.
- **Long missions.** The Master monitors with a 1800 s budget and each task has its own timeout/retry budget; for very large missions prefer Mode C with focused domains over forcing Mode B.
- **Memory growth.** History is append-only; schedule `MemoryManager.prune()` (see [memory.md](memory.md)) if you run long-lived deployments.
