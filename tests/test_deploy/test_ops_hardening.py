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


def test_service_enables_proxy_headers() -> None:
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
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in nginx_text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in nginx_text


def test_backup_script_handles_same_day_double_run(tmp_path: Path) -> None:
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
        "db=\"$1\"\n"
        "cmd=\"$2\"\n"
        "target=\"${cmd#.backup }\"\n"
        "cp \"$db\" \"$target\"\n",
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
