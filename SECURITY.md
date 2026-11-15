# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: yes |
| < 1.0   | :x: no             |

Only the latest minor release receives security fixes. Please keep your
installation up to date.

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems.**

Preferred channel: open a **GitHub private security advisory** via the
repository's *Security → Report a vulnerability* flow. This allows private
discussion, coordinated fix development, and credit.

Alternative channel: email **security@agenthive.local**
*(placeholder address — replace with the project's real security contact
before publishing this policy)*. Please include:

- A description of the vulnerability and its impact.
- Step-by-step reproduction instructions or a proof of concept.
- The affected version(s) and, if possible, a suggested fix.
- Whether you wish to be credited and under which name.

We aim to acknowledge reports within **72 hours** and to publish a fix or a
mitigation within **30 days** for critical issues. Please allow a reasonable
window for a fix before any public disclosure; coordinated disclosure is the
default.

## Scope

In scope:

- The `agent_hive` package (API server, orchestrator, agents, memory, tasks).
- The bundled CLI (`agent-hive`) and helper scripts in `scripts/`.
- The provided container/deployment files (`Dockerfile`,
  `docker-compose.yml`) and their default configurations.
- Default configuration files under `configs/`.

Out of scope:

- Vulnerabilities in third-party LLM providers or their endpoints (report to
  the respective vendor), except where AgentHive misuses their APIs.
- Attacks requiring write access to the server's filesystem or environment
  (an attacker with shell access is assumed to have already won).
- Social engineering, brute-force attacks, or denial of service of the
  deployment host itself.
- Issues in deployments that ignore the documented hardening guidance (e.g.
  exposing the API directly to the internet without authentication).

## Security design notes

AgentHive is built with the following security-relevant decisions:

- **No secrets in the repository.** API keys and database credentials are
  read from environment variables only (`OPENAI_API_KEY`,
  `DATABASE_URL`, ...). YAML files reference credentials by env-var *name*;
  `.env` is git-ignored and only `.env.example` is tracked.
- **Env-based key injection.** Providers receive credentials at construction
  time from the environment; configuration and logs never carry secrets, and
  diagnostics print connection *schemes*, never connection strings.
- **Permission-controlled tools.** Tool families are opt-in through explicit
  switches (`ENABLE_FILE_TOOLS`, `ENABLE_HTTP_TOOLS`), both **disabled by
  default**. Agents can only use tools granted by their configuration.
- **Sandboxed file access.** File tools are restricted to the configured
  `WORKSPACE_DIR`; path traversal outside the workspace is rejected.
- **Least-privilege container.** The Docker image runs as the non-root user
  `hive`; the compose file keeps state in named volumes and never bakes
  secrets into images.
- **Mock-safe operation.** `ALLOW_MOCK=true` keeps the whole system
  testable without any external provider or key; mock responses are clearly
  tagged `[MOCK]` so they cannot be mistaken for real output.
