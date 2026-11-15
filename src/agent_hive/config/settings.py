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
    log_level: str = "INFO"
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

    def ensure_dirs(self) -> None:
        """Create runtime directories if missing."""
        for p in (self.data_dir, self.workspace_dir):
            Path(p).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
