#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/cte-time"
SERVICE="cte-time"
SERVICE_UNIT_FILE="${APP_DIR}/deploy/cte-time.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (or with sudo)."
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "App directory not found: ${APP_DIR}"
  exit 1
fi

echo "Deploying CTE Time from ${APP_DIR}..."
echo "Note: nginx must forward X-Forwarded-For and X-Forwarded-Proto headers."
echo "Note: Set ADMIN_EMAIL and ADMIN_PASSWORD in .env for first-run admin bootstrap."

echo "Creating pre-deployment backup..."
"${APP_DIR}/backup.sh" || echo "WARNING: Pre-deployment backup failed, continuing..."

cd "${APP_DIR}"

echo "Pulling latest code..."
git pull --ff-only

if [[ ! -d ".venv" ]]; then
  echo "Virtual environment missing at ${APP_DIR}/.venv"
  exit 1
fi

echo "Installing dependencies..."
source "${APP_DIR}/.venv/bin/activate"
pip install --no-input --upgrade -r requirements.txt

if [[ -f "${SERVICE_UNIT_FILE}" ]]; then
  if ! grep -q 'ExecStart=.*--proxy-headers' "${SERVICE_UNIT_FILE}"; then
    echo "ERROR: ${SERVICE_UNIT_FILE} is missing --proxy-headers in ExecStart."
    exit 1
  fi
  if ! grep -q 'ExecStart=.*--forwarded-allow-ips=127.0.0.1' "${SERVICE_UNIT_FILE}"; then
    echo "ERROR: ${SERVICE_UNIT_FILE} is missing --forwarded-allow-ips=127.0.0.1 in ExecStart."
    exit 1
  fi
else
  echo "WARNING: ${SERVICE_UNIT_FILE} not found; ensure service ExecStart includes --proxy-headers and forwarded allow list."
fi

echo "Validating nginx configuration..."
if command -v nginx &>/dev/null; then
    nginx -t || echo "WARNING: nginx configuration test failed; reload skipped."
else
    echo "WARNING: nginx not found on PATH; skipping config validation."
fi

echo "Restarting service..."
systemctl restart "${SERVICE}"

echo "Waiting for service to become active..."
sleep 3
if ! systemctl is-active --quiet "${SERVICE}"; then
    echo "ERROR: ${SERVICE} failed to start after deploy."
    systemctl status "${SERVICE}" --no-pager
    exit 1
fi

echo "Running post-deploy health check..."
for i in 1 2 3; do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo "Health check passed."
        echo "Deployment complete."
        exit 0
    fi
    sleep 2
done

echo "WARNING: Service started but health check failed after 3 attempts."
systemctl status "${SERVICE}" --no-pager
exit 1
