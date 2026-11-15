"""AgentHive — advanced multi-agent orchestration system.

Architecture layers (fully decoupled):

- ``agent_hive.config``   — settings and YAML configuration loader.
- ``agent_hive.core``     — ids, logging, events, errors (shared kernel).
- ``agent_hive.db``       — SQLAlchemy models and session factory.
- ``agent_hive.providers``— pluggable LLM providers (OpenAI-compatible,
                            Ollama, mock) with per-agent fallback chains.
- ``agent_hive.memory``   — individual / shared / historical memory manager.
- ``agent_hive.communication`` — persistent message bus between agents.
- ``agent_hive.tasks``    — task manager: queue, dependencies, retries,
                            timeouts, recovery and monitoring.
- ``agent_hive.tools``    — permission-controlled tool registry.
- ``agent_hive.agents``   — BaseAgent runtime + 20 specialized role agents.
- ``agent_hive.orchestrator`` — Master Agent: analysis, planning, delegation,
                            monitoring, integration and quality control.
- ``agent_hive.api``      — FastAPI application (REST + WebSocket).
- ``agent_hive.cli``      — Typer command line interface.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
