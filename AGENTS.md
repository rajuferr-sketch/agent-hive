# AgentHive — guide for an AI agent

AgentHive is a multi-agent orchestration system: 1 Master Agent + 20 specialized agents with shared memory, task DAGs, quality control and multi-provider LLM support.

## Quick start (30 seconds)
```bash
python run.py "your request"
```
First install dependencies once: `pip install -r requirements.txt`
Then run: `python run.py "your request"` (creates the database and runs the mission).

## Commands
- `python run.py "request"` — run a mission (Markdown output).
- `python run.py --mode B "request"` — force collective mode (all agents).
- `python run.py --chat "request"` — use the chat AI as the brain (host provider).
- `python run.py demo logistica` / `demo codice` — built-in demos.
- `python -m agent_hive.cli diagnose` — environment diagnostics.
- `python -m agent_hive.cli recover` — reset orphaned tasks.

## What to expect
- With no API key and no Ollama, agents use the deterministic mock provider and results are tagged `[MOCK]`.
- Output: mission id, mode, quality score, agent list, task table, deliverable.
- Database: SQLite in `./data/agent_hive.db` (created automatically).
- Logs are quiet by default.

## Providers
- `openai_compatible` (env `OPENAI_API_KEY`, `OPENAI_BASE_URL`)
- `ollama` (env `OLLAMA_BASE_URL`)
- `host` (chat AI writes/reads files in `./host_requests` and `./host_responses`)
- `mock` (always available fallback)

## Adding an agent
Drop a YAML file in `configs/agents/` and (optionally) a role class in `src/agent_hive/agents/roles/`. Role classes are auto-discovered.