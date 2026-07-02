from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    secret_key: str
    database_path: str = "cte_time.db"
    host: str = "127.0.0.1"
    port: int = 8000
    display_timezone: str = "America/Denver"
    session_max_age: int = 28800
    is_production: bool = False
    session_same_site: str = "lax"
    backup_dir: str = "/opt/cte-time/backups"
    log_dir: str = "/var/log/cte-time"
    app_version: str = "1.0.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
