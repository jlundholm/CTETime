from pathlib import Path

from app.config import get_settings


def test_settings_load_display_timezone_from_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "deploy-test-secret")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "America/Denver")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.display_timezone == "America/Denver"
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
    assert "proxy_pass http://127.0.0.1:8000;" in nginx_text
    assert "proxy_set_header Host $host;" in nginx_text
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx_text
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in nginx_text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in nginx_text
