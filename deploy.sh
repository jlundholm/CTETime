#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/cte-time"
SERVICE="cte-time"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (or with sudo)."
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "App directory not found: ${APP_DIR}"
  exit 1
fi

echo "Deploying CTE Time from ${APP_DIR}..."

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
