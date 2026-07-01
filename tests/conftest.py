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


@pytest_asyncio.fixture
async def app(test_database_path, monkeypatch):
    temp_root = str(Path(test_database_path).parent)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_PATH", test_database_path)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8001")
    monkeypatch.setenv("LOG_DIR", f"{temp_root}/logs")
    monkeypatch.setenv("BACKUP_DIR", f"{temp_root}/backups")
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    get_settings.cache_clear()

    await run_migrations(test_database_path)
    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute(
            (
                "INSERT INTO admins (first_name, last_name, email, password_hash) "
                "VALUES (?, ?, ?, ?)"
            ),
            ("Test", "Admin", "admin@example.com".lower(), hash_password("test-password")),
        )
        await connection.commit()

    app_instance = create_app()
    yield app_instance
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
