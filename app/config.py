from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    secret_key: str = Field(min_length=16)
    database_path: str = "cte_time.db"
    host: str = "127.0.0.1"
    port: int = 8000
    display_timezone: str = "America/Denver"
    session_max_age: int = Field(default=28800, gt=0)
    is_production: bool = False
    session_same_site: Literal["lax", "strict", "none"] = "lax"
    backup_dir: str = "/opt/cte-time/backups"
    log_dir: str = "/var/log/cte-time"
    app_version: str = "1.0.0"
    rate_limit_max_requests: int = Field(default=60, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    week_start_day: int = Field(default=0, ge=0, le=6)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
