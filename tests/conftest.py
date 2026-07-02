import logging
from contextlib import asynccontextmanager

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pathlib import Path

from app.auth.staff import hash_password
from app.config import get_settings
from app.database import run_migrations
from app.main import create_app


@pytest.fixture
def test_database_path(tmp_path) -> str:
    return str(tmp_path / "cte-time-test.db")


@pytest.fixture(autouse=True)
def clear_settings_cache_between_tests():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _apply_base_test_env(monkeypatch, test_database_path: str, extra_env: dict[str, str] | None = None) -> None:
    temp_root = str(Path(test_database_path).parent)
    env_values = {
        "SECRET_KEY": "test-secret-16-chars",
        "DATABASE_PATH": test_database_path,
        "HOST": "127.0.0.1",
        "PORT": "8001",
        "LOG_DIR": f"{temp_root}/logs",
        "BACKUP_DIR": f"{temp_root}/backups",
        "APP_VERSION": "1.0.0",
    }
    if extra_env:
        env_values.update(extra_env)

    for key, value in env_values.items():
        monkeypatch.setenv(key, value)


async def _seed_admin(test_database_path: str, first_name: str = "Test", last_name: str = "Admin") -> None:
    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute(
            (
                "INSERT INTO admins (first_name, last_name, email, password_hash) "
                "VALUES (?, ?, ?, ?)"
            ),
            (first_name, last_name, "admin@example.com", hash_password("test-password")),
        )
        await connection.commit()


@pytest.fixture
def app_factory(test_database_path, monkeypatch):
    @asynccontextmanager
    async def factory(*, extra_env: dict[str, str] | None = None, admin_name: tuple[str, str] = ("Test", "Admin")):
        if len(admin_name) != 2:
            raise ValueError(f"admin_name must be (first, last), got {admin_name}")
        initial_handler_count = len(logging.getLogger().handlers)
        try:
            _apply_base_test_env(monkeypatch, test_database_path, extra_env)
            get_settings.cache_clear()
            await run_migrations(test_database_path)
            await _seed_admin(test_database_path, *admin_name)
            app_instance = create_app()
            yield app_instance
        finally:
            del logging.getLogger().handlers[initial_handler_count:]
            get_settings.cache_clear()
            try:
                Path(test_database_path).unlink(missing_ok=True)
            except OSError:
                pass

    return factory


@pytest_asyncio.fixture
async def app(app_factory):
    async with app_factory() as app_instance:
        yield app_instance


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
