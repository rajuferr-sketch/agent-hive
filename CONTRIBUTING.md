# Contributing to AgentHive

Thank you for considering a contribution to **AgentHive** — an advanced
multi-agent orchestration system (1 Master Agent, 20 specialized AI agents).
This document explains how to set up a development environment, follow the
project conventions, and submit high-quality pull requests.

## Getting started

Prerequisites: Python **3.11+** (3.12 recommended), Git, and a POSIX shell or
PowerShell on Windows.

```bash
# 1. Clone your fork
git clone https://github.com/agent-hive/agent-hive.git
cd agent-hive

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1

# 3. Install dev dependencies and the package (editable)
pip install -r requirements-dev.txt
pip install -e .

# 4. Create your local environment file (never committed)
cp .env.example .env               # fill in real values locally only
```

Alternatively, run `scripts/install.sh` (Linux/macOS) or
`scripts/install.ps1` (Windows) to perform steps 2–4 automatically.

## Project layout

```
src/agent_hive/        application package (src layout)
configs/               YAML configuration (system.yaml, master.yaml, agents/*.yaml)
tests/                 pytest suite
scripts/               helper scripts (install, start, diagnostics)
```

## Code style

- Formatter/linter: **ruff** (configuration in `pyproject.toml`).
- Maximum line length: **100** characters.
- Before committing, run:

```bash
ruff check src tests
ruff format --check src tests   # or run `ruff format src tests` to auto-format
```

- Type hints are expected on new public code; `mypy src` should stay clean.

## Running tests

```bash
pytest -q                    # full suite (SQLite backend, no infra required)
pytest -q tests/test_tasks   # single directory/module
```

`pytest-asyncio` runs in auto mode — async test functions work out of the box.
Tests never require PostgreSQL or live LLM providers: use the mock provider
(`ALLOW_MOCK=true`, the default) and SQLite.

## Adding a new agent

Agents are configuration-driven: each agent is one module plus one YAML file.

1. **Create the role module** in `src/agent_hive/agents/roles/`
   (e.g. `roles/translator.py`), subclassing `BaseAgent` and implementing the
   role-specific behaviour. Register the role class in
   `src/agent_hive/agents/roles/__init__.py` if roles are exported there.
2. **Create the agent YAML** in `configs/agents/` with the *same file stem as
   the agent name* (e.g. `configs/agents/translator.yaml`):

   ```yaml
   name: translator
   title: "Translation Agent"
   role: translator            # must match the module/class in agents/roles/
   description: "Translates text across languages with terminology control."
   capabilities: [translation, terminology]
   tools: []                   # subset of the tools registry
   memory:
     individual: true
     shared_access: false
     shared_write: false
   providers:                  # ordered fallback chain; keys by env-name only
     - type: openai_compatible
       model: gpt-4o-mini
       api_key_env: OPENAI_API_KEY   # env var NAME, never the secret itself
     - type: mock
   ```

3. **Add tests** covering the new role (unit test the agent logic; use the
   mock provider) and verify with:

   ```bash
   agent-hive agents           # lists all configured agents
   ```

Never put API keys, passwords, or endpoints with credentials in YAML —
reference environment variables by name.

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(agents): add translator role agent
fix(tasks): recover orphaned running tasks on startup
docs(readme): document docker-compose deployment
chore(deps): bump httpx to 0.28
```

Keep commits small and focused; each commit should pass lint and tests.

## Pull request checklist

Before opening a PR, make sure that:

- [ ] The branch is up to date with `main` and rebased/merged cleanly.
- [ ] `ruff check src tests` passes with no findings.
- [ ] `pytest -q` passes on Python 3.11 *and* 3.12.
- [ ] New public functions/classes have type hints and docstrings.
- [ ] New agents include both a role module and a validated YAML config.
- [ ] No secrets, credentials, or generated `.env` files are committed.
- [ ] Documentation (README/docs) is updated for user-visible changes.
- [ ] The PR description explains the *what* and *why*, and links related
      issues.

## Reporting issues

For bugs, open a GitHub issue with reproduction steps, expected vs. actual
behaviour, and the output of `agent-hive diagnose`. For security
vulnerabilities, **do not** open a public issue — follow
[SECURITY.md](SECURITY.md).

## Licensing

By contributing, you agree that your contributions are licensed under the
MIT License that covers the project.
