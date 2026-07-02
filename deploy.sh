#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/cte-time"
SERVICE="cte-time"
SERVICE_UNIT_FILE="${APP_DIR}/cte-time.service"

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

echo "Restarting service..."
systemctl restart "${SERVICE}"

echo "Waiting for service to become active..."
sleep 2
if systemctl is-active --quiet "${SERVICE}"; then
    echo "Deployment complete."
else
    echo "ERROR: ${SERVICE} failed to start after deploy."
    systemctl status "${SERVICE}" --no-pager
    exit 1
fi
