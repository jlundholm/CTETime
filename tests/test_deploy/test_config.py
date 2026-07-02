from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.staff import hash_password
from app.database import run_migrations
from app.main import create_app
from app.config import get_settings


async def _get_admin_csrf(client: AsyncClient) -> str:
    response = await client.get("/admin/login")
    assert response.status_code == 200
    return response.text.split('name="csrf_token" value="')[1].split('"')[0]


@pytest_asyncio.fixture
async def production_client(test_database_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("DATABASE_PATH", test_database_path)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8001")
    monkeypatch.setenv("LOG_DIR", str(Path(test_database_path).parent / "logs"))
    monkeypatch.setenv("BACKUP_DIR", str(Path(test_database_path).parent / "backups"))
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    monkeypatch.setenv("IS_PRODUCTION", "true")
    monkeypatch.setenv("SESSION_MAX_AGE", "28800")
    monkeypatch.setenv("SESSION_SAME_SITE", "lax")
    get_settings.cache_clear()

    await run_migrations(test_database_path)
    import aiosqlite

    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute(
            (
                "INSERT INTO admins (first_name, last_name, email, password_hash) "
                "VALUES (?, ?, ?, ?)"
            ),
            ("Prod", "Admin", "admin@example.com", hash_password("test-password")),
        )
        await connection.commit()

    app_instance = create_app()
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client

    get_settings.cache_clear()


def test_settings_load_display_timezone_from_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "deploy-test-secret")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "America/Denver")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.display_timezone == "America/Denver"
    finally:
        get_settings.cache_clear()


def test_settings_load_security_session_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "b" * 64)
    monkeypatch.setenv("IS_PRODUCTION", "true")
    monkeypatch.setenv("SESSION_MAX_AGE", "28800")
    monkeypatch.setenv("SESSION_SAME_SITE", "lax")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.is_production is True
        assert settings.session_max_age == 28800
        assert settings.session_same_site == "lax"
    finally:
        get_settings.cache_clear()


def test_deployment_artifacts_exist_with_expected_basics():
    repo_root = Path(__file__).resolve().parents[2]

    deploy_script = repo_root / "deploy.sh"
    backup_script = repo_root / "deploy" / "backup.sh"
    service_file = repo_root / "deploy" / "cte-time.service"
    nginx_file = repo_root / "deploy" / "nginx-cte-time.conf"

    assert deploy_script.exists()
    assert backup_script.exists()
    assert service_file.exists()
    assert nginx_file.exists()

    deploy_text = deploy_script.read_text(encoding="utf-8")
    assert "git pull" in deploy_text
    assert "pip install" in deploy_text
    assert "requirements.txt" in deploy_text
    assert "systemctl restart" in deploy_text
    assert "cte-time" in deploy_text

    backup_text = backup_script.read_text(encoding="utf-8")
    assert "sqlite3" in backup_text
    assert "BACKUP_DIR=\"/opt/cte-time/backups\"" in backup_text
    assert "DB_PATH=\"/opt/cte-time/data/cte_time.db\"" in backup_text
    assert "cte_time-" in backup_text

    service_text = service_file.read_text(encoding="utf-8")
    assert "User=www-data" in service_text
    assert "WorkingDirectory=/opt/cte-time" in service_text
    assert "EnvironmentFile=" in service_text
    assert "/opt/cte-time/.env" in service_text
    assert "--host 127.0.0.1 --port 8000" in service_text

    nginx_text = nginx_file.read_text(encoding="utf-8")
    assert "listen 80;" in nginx_text
    assert "return 301 https://$host$request_uri;" in nginx_text
    assert "listen 443 ssl;" in nginx_text
    assert "ssl_certificate /etc/letsencrypt/live/cte-time.example.com/fullchain.pem;" in nginx_text
    assert "ssl_certificate_key /etc/letsencrypt/live/cte-time.example.com/privkey.pem;" in nginx_text
    assert "proxy_pass http://127.0.0.1:8000;" in nginx_text
    assert "proxy_set_header Host $host;" in nginx_text
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx_text
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in nginx_text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in nginx_text


@pytest.mark.asyncio
async def test_session_cookie_flags_default_dev(client):
    token = await _get_admin_csrf(client)
    response = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert response.status_code == 303
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie


@pytest.mark.asyncio
async def test_session_cookie_flags_production_secure(production_client):
    token = await _get_admin_csrf(production_client)
    response = await production_client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert response.status_code == 303
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" in set_cookie
