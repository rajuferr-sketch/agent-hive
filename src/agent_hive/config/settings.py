"""Runtime settings, driven by environment variables (12-factor style).

All secrets come from the environment (``.env`` file, never committed).
All structural configuration lives in ``configs/*.yaml``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global system settings."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./data/agent_hive.db"

    # Behaviour
    allow_mock: bool = True
    log_level: str = "WARNING"
    config_dir: Path = Path("./configs")
    workspace_dir: Path = Path("./workspace")
    data_dir: Path = Path("./data")
    max_concurrency: int = 8
    default_task_timeout: int = 120
    default_max_retries: int = 2
    memory_max_versions: int = 20          # per key, older versions pruned
    memory_retention_days: int = 90        # historical memory retention
    heartbeat_interval: int = 15           # seconds
    scheduler_interval: float = 1.0        # seconds

    # API server
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Security switches for sensitive tool families
    enable_file_tools: bool = False
    enable_http_tools: bool = False

    # ---- Universal AI Platform (MCP / Gateway / connectors / security) ----
    # Master token: when set, it acts as an implicit admin token (hash is
    # computed at verify time; the raw value only lives in the environment).
    api_master_token: str = ""
    # Token lifetime (seconds) for tokens issued without explicit TTL.
    token_default_ttl: int = 86400 * 7
    # Rate limiting (requests per window per token/IP).
    rate_limit_requests: int = 120
    rate_limit_window: int = 60
    # Gateway
    gateway_max_concurrent: int = 16
    gateway_request_timeout: int = 300
    # MCP
    mcp_server_name: str = "agent-hive"
    mcp_tool_timeout: int = 120          # default per-tool execution timeout
    mcp_max_sessions: int = 256
    # Self-heal
    selfheal_enabled: bool = True
    selfheal_interval: float = 30.0
    selfheal_max_retries: int = 3
    selfheal_budget_s: float = 60.0
    selfheal_fail_limit: int = 5         # consecutive failing cycles → safe stop
    # Universal memory
    universal_memory_dims: int = 128     # hashed-embedding dimensions
    universal_memory_ttl_default: int = 0  # 0 = no expiry
    # GitHub integration: read_only | assisted | semi_autonomous | autonomous
    github_mode: str = "read_only"

    def ensure_dirs(self) -> None:
        """Create runtime directories if missing.

        Falls back to a writable temporary directory when the current working
        directory is read-only, so the system still boots in sandboxes.
        """
        import tempfile

        for attr in ("data_dir", "workspace_dir"):
            p = Path(getattr(self, attr))
            try:
                p.mkdir(parents=True, exist_ok=True)
                # probe writability
                probe = p / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except OSError:
                fallback = Path(tempfile.gettempdir()) / "agent-hive" / attr.split("_")[0]
                fallback.mkdir(parents=True, exist_ok=True)
                setattr(self, attr, fallback)
                if attr == "data_dir":
                    self.database_url = f"sqlite+aiosqlite:///{fallback / 'agent_hive.db'}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
