import os
import stat
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_ops_artifacts_exist() -> None:
    repo_root = _repo_root()

    assert (repo_root / "cte-time.nginx.conf").exists()
    assert (repo_root / "cte-time.service").exists()
    assert (repo_root / "backup.sh").exists()


def test_uvicorn_proxy_headers_in_deploy_script() -> None:
    service_text = (_repo_root() / "cte-time.service").read_text(encoding="utf-8")

    assert "--proxy-headers" in service_text
    assert "--forwarded-allow-ips=127.0.0.1" in service_text


def test_nginx_config_has_required_hardening_directives() -> None:
    nginx_text = (_repo_root() / "cte-time.nginx.conf").read_text(encoding="utf-8")

    assert "client_max_body_size 1M;" in nginx_text
    assert "proxy_connect_timeout 30s;" in nginx_text
    assert "proxy_read_timeout 30s;" in nginx_text
    assert "proxy_send_timeout 30s;" in nginx_text
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx_text
    assert 'add_header X-Frame-Options "DENY" always;' in nginx_text
    assert 'add_header X-XSS-Protection "0" always;' in nginx_text
    assert 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;' in nginx_text
    assert "add_header Content-Security-Policy \"default-src 'self'\" always;" in nginx_text
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx_text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in nginx_text


def test_nginx_config_tls_hardening() -> None:
    nginx_text = (_repo_root() / "cte-time.nginx.conf").read_text(encoding="utf-8")

    assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx_text
    assert "ssl_prefer_server_ciphers off;" in nginx_text
    assert "ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:" in nginx_text
    assert "ssl_session_cache shared:SSL:10m;" in nginx_text
    assert "ssl_session_timeout 1d;" in nginx_text
    assert "ssl_session_tickets off;" in nginx_text


def test_nginx_config_has_http_https_redirect() -> None:
    nginx_text = (_repo_root() / "cte-time.nginx.conf").read_text(encoding="utf-8")

    assert "listen 80;" in nginx_text
    assert "return 301 https://$host$request_uri;" in nginx_text


def test_nginx_config_uses_map_for_proxy_redirect() -> None:
    nginx_text = (_repo_root() / "cte-time.nginx.conf").read_text(encoding="utf-8")

    assert "map $http_x_forwarded_proto $should_https_redirect" in nginx_text
    assert "if ($should_https_redirect)" in nginx_text


def test_backup_script_handles_duplicate_run(tmp_path: Path) -> None:
    repo_root = _repo_root()
    script = repo_root / "backup.sh"

    backup_dir = tmp_path / "backups"
    db_path = tmp_path / "cte_time.db"
    db_path.write_text("db", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sqlite3 = fake_bin / "sqlite3"
    fake_sqlite3.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'db="$1"\n'
        'cmd="$2"\n'
        'if [[ "$cmd" == ".backup "* ]]; then\n'
        '  target="${cmd#.backup }"\n'
        '  cp "$db" "$target"\n'
        'fi\n',
        encoding="utf-8",
    )
    fake_sqlite3.chmod(fake_sqlite3.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["BACKUP_DIR"] = str(backup_dir)
    env["DB_PATH"] = str(db_path)

    subprocess.run([str(script)], check=True, env=env, cwd=repo_root)
    subprocess.run([str(script)], check=True, env=env, cwd=repo_root)

    backups = sorted(backup_dir.glob("cte_time-*.db"))
    assert len(backups) == 2
    assert backups[0].name != backups[1].name


def test_backup_script_has_wal_checkpoint() -> None:
    script_text = (_repo_root() / "backup.sh").read_text(encoding="utf-8")

    assert "PRAGMA wal_checkpoint(TRUNCATE)" in script_text


def test_backup_script_has_retention_cleanup() -> None:
    script_text = (_repo_root() / "backup.sh").read_text(encoding="utf-8")

    assert "BACKUP_RETENTION_DAYS" in script_text
    assert "mtime" in script_text or "-mtime" in script_text


def test_backup_script_has_date_guard() -> None:
    script_text = (_repo_root() / "backup.sh").read_text(encoding="utf-8")

    assert 'STAMP=""' in script_text
    assert 'if [[ -z "$STAMP" ]]' in script_text


def test_backup_script_date_failure_exits_with_error(tmp_path: Path) -> None:
    script = _repo_root() / "backup.sh"
    backup_dir = tmp_path / "backups"
    db_path = tmp_path / "cte_time.db"
    db_path.write_text("db", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_date = fake_bin / "date"
    fake_date.write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    fake_date.chmod(fake_date.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["BACKUP_DIR"] = str(backup_dir)
    env["DB_PATH"] = str(db_path)

    result = subprocess.run([str(script)], capture_output=True, text=True, env=env, cwd=_repo_root())
    assert result.returncode != 0
    assert "Failed to generate timestamp" in result.stderr


def test_deploy_script_has_pre_deployment_backup() -> None:
    script_text = (_repo_root() / "deploy.sh").read_text(encoding="utf-8")

    assert "backup.sh" in script_text


def test_deploy_script_documents_admin_env() -> None:
    script_text = (_repo_root() / "deploy.sh").read_text(encoding="utf-8")

    assert "ADMIN_EMAIL" in script_text
    assert "ADMIN_PASSWORD" in script_text


def test_config_has_admin_settings() -> None:
    config_text = (_repo_root() / "app" / "config.py").read_text(encoding="utf-8")

    assert "admin_email" in config_text
    assert "admin_password" in config_text


def test_main_py_has_admin_bootstrap() -> None:
    main_text = (_repo_root() / "app" / "main.py").read_text(encoding="utf-8")

    assert "_seed_admin" in main_text
    assert "hash_password" in main_text
    assert "INSERT INTO admins" in main_text
    assert "SELECT COUNT(*) FROM admins" in main_text
