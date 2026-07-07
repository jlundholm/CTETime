#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/cte-time"
REPO_URL="https://github.com/jlundholm/CTETime"
SERVICE="cte-time"
SYSTEMD_SRC="deploy/cte-time.service"
NGINX_SRC_TLS="deploy/nginx-cte-time.conf"
NGINX_SRC_HTTP="deploy/nginx-cte-time_http.conf"
NGINX_TARGET="cte-time"
BACKUP_SCRIPT="backup.sh"

info()  { echo -e "\033[1;34m* $1\033[0m"; }
ok()    { echo -e "\033[1;32m\u2713 $1\033[0m"; }
warn()  { echo -e "\033[1;33m! $1\033[0m"; }
fail()  { echo -e "\033[1;31m\u2717 $1\033[0m"; exit 1; }

if [[ $EUID -ne 0 ]]; then fail "Run as root: sudo ./install.sh"; fi

if [[ ! -f /etc/os-release ]]; then fail "Unsupported OS (no /etc/os-release)"; fi
source /etc/os-release
if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    fail "Unsupported OS: $ID. Ubuntu or Debian required."
fi
info "Installing CTE Time on $NAME $VERSION_ID"

info "Updating package lists..."
apt-get update -qq

info "Installing system packages..."
apt-get install -y -qq nginx git sqlite3 python3 python3-venv python3-pip

read -p "Enter the domain for this server (default: cte-time.example.com): " DOMAIN
DOMAIN="${DOMAIN:-cte-time.example.com}"

info "Checking port 80 reachability for $DOMAIN..."
PORT_80_OK=false
if curl -s -o /dev/null --connect-timeout 5 "http://$DOMAIN" 2>/dev/null; then
    PORT_80_OK=true
    ok "Port 80 is reachable"
else
    warn "Port 80 on $DOMAIN does not appear reachable from the internet"
    warn "The standard certbot HTTP-01 challenge likely won't work"
    warn "See https://eff.org/dns-01 for DNS-01 challenge setup"
fi

USE_HTTPS=false
RUN_CERTBOT=false
read -p "Set up HTTPS with Let's Encrypt? (y/N): " HTTPS_ANSWER
if [[ "$HTTPS_ANSWER" =~ ^[Yy]$ ]]; then
    USE_HTTPS=true
    RUN_CERTBOT=true
    apt-get install -y -qq certbot python3-certbot-nginx
    if ! $PORT_80_OK; then
        warn "Port 80 unreachable; certbot will likely fail."
        warn "After install, run: sudo certbot --nginx -d $DOMAIN"
        warn "Or use DNS-01: https://eff.org/dns-01"
    fi
fi

ADMIN_EMAIL=""
ADMIN_PASSWORD=""
read -p "Admin email for initial account (leave blank to skip): " ADMIN_EMAIL
if [[ -n "$ADMIN_EMAIL" ]]; then
    while true; do
        read -s -p "Admin password: " ADMIN_PASSWORD
        echo
        read -s -p "Confirm password: " ADMIN_PASSWORD_CONFIRM
        echo
        if [[ -z "$ADMIN_PASSWORD" ]]; then
            warn "Password cannot be empty"
        elif [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
            warn "Passwords do not match"
        else
            break
        fi
    done
fi

BACKUP_CRON=false
read -p "Add daily backup at 2 AM? (Y/n): " CRON_ANSWER
if [[ ! "$CRON_ANSWER" =~ ^[Nn]$ ]]; then
    BACKUP_CRON=true
fi

EDIT_ENV=false
read -p "Edit .env now to tweak settings? (y/N): " EDIT_ANSWER
if [[ "$EDIT_ANSWER" =~ ^[Yy]$ ]]; then
    EDIT_ENV=true
fi

info "Cloning repository to $APP_DIR..."
if [[ -d "$APP_DIR/.git" ]]; then
    ok "Repository already exists at $APP_DIR"
else
    git clone "$REPO_URL" "$APP_DIR"
    ok "Repository cloned"
fi

cd "$APP_DIR"

info "Creating Python virtual environment..."
python3 -m venv .venv
ok "Virtual environment created"

info "Installing Python dependencies..."
.venv/bin/pip install --no-input -q -r requirements.txt
ok "Dependencies installed"

info "Configuring .env from template..."
if [[ -f ".env" ]]; then
    warn ".env already exists, skipping"
else
    cp .env.example .env

    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env

    sed -i "s|^DATABASE_PATH=.*|DATABASE_PATH=$APP_DIR/data/cte_time.db|" .env

    if $USE_HTTPS; then
        sed -i "s/^IS_PRODUCTION=true/IS_PRODUCTION=true/" .env
    else
        sed -i "s/^IS_PRODUCTION=true/IS_PRODUCTION=false/" .env
    fi

    if [[ -n "$ADMIN_EMAIL" ]]; then
        sed -i "s/^ADMIN_EMAIL=.*/ADMIN_EMAIL=$ADMIN_EMAIL/" .env
        sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$ADMIN_PASSWORD/" .env
    fi

    ok ".env configured"
fi

info "Creating directories and setting permissions..."
mkdir -p "$APP_DIR/data"
chown www-data:www-data "$APP_DIR/data"
chmod 750 "$APP_DIR/data"

mkdir -p /var/log/cte-time
chown www-data:www-data /var/log/cte-time

mkdir -p "$APP_DIR/backups"
chown root:root "$APP_DIR/backups"
chmod 750 "$APP_DIR/backups"

chown root:www-data "$APP_DIR/.env"
chmod 640 "$APP_DIR/.env"

chmod +x "$APP_DIR/$BACKUP_SCRIPT"
chmod +x "$APP_DIR/deploy.sh"
ok "Directories and permissions set"

info "Installing systemd service unit..."
cp "$APP_DIR/$SYSTEMD_SRC" /etc/systemd/system/cte-time.service
chmod 644 /etc/systemd/system/cte-time.service
systemctl daemon-reload
systemctl enable "$SERVICE"
ok "systemd unit installed and enabled"

info "Configuring nginx..."
if $USE_HTTPS; then
    NGINX_SOURCE="$APP_DIR/$NGINX_SRC_TLS"
else
    NGINX_SOURCE="$APP_DIR/$NGINX_SRC_HTTP"
fi
sed "s/__DOMAIN__/$DOMAIN/g" "$NGINX_SOURCE" > /etc/nginx/sites-available/"$NGINX_TARGET"

if [[ -f /etc/nginx/sites-enabled/default ]]; then
    rm /etc/nginx/sites-enabled/default
fi
if [[ ! -L /etc/nginx/sites-enabled/"$NGINX_TARGET" ]]; then
    ln -s /etc/nginx/sites-available/"$NGINX_TARGET" /etc/nginx/sites-enabled/"$NGINX_TARGET"
fi

info "Validating nginx configuration..."
if nginx -t; then
    ok "nginx configuration is valid"
else
    fail "nginx configuration test failed — check /etc/nginx/sites-available/$NGINX_TARGET"
fi

systemctl reload nginx
ok "nginx reloaded"

info "Starting $SERVICE service..."
systemctl start "$SERVICE"

info "Waiting for service to become active..."
for i in 1 2 3 4 5; do
    if systemctl is-active --quiet "$SERVICE"; then
        ok "Service is running"
        break
    fi
    if [[ $i -eq 5 ]]; then
        fail "Service failed to start — run: systemctl status $SERVICE"
    fi
    sleep 2
done

info "Running health check..."
for i in 1 2 3; do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
        ok "Health check passed"
        break
    fi
    if [[ $i -eq 3 ]]; then
        warn "Health check failed after 3 attempts"
        warn "Run: systemctl status $SERVICE --no-pager"
    fi
    sleep 2
done

if $USE_HTTPS && $RUN_CERTBOT; then
    info "Attempting Let's Encrypt certificate issuance..."
    info "Running: certbot --nginx -d $DOMAIN"
    if certbot --nginx -d "$DOMAIN"; then
        ok "HTTPS certificate obtained and configured"
    else
        warn "certbot encountered an issue"
        warn "Manual steps:"
        warn "  1. sudo certbot --nginx -d $DOMAIN"
        warn "  2. DNS-01 instructions: https://eff.org/dns-01"
    fi
fi

if $BACKUP_CRON; then
    info "Installing backup cron job..."
    if crontab -l 2>/dev/null | grep -qF "$APP_DIR/$BACKUP_SCRIPT"; then
        ok "Backup cron job already exists"
    else
        (crontab -l 2>/dev/null; echo "0 2 * * * $APP_DIR/$BACKUP_SCRIPT") | crontab -
        ok "Daily backup cron installed at 2 AM"
    fi
fi

if $EDIT_ENV; then
    EDITOR="${EDITOR:-nano}"
    info "Opening .env in $EDITOR..."
    "$EDITOR" "$APP_DIR/.env"
    ok ".env editing complete"
fi

echo
echo "========================================"
echo "  CTE Time installation complete"
echo "========================================"
echo
systemctl status "$SERVICE" --no-pager
echo
echo "App URL:      http${USE_HTTPS:+s}://$DOMAIN"
echo "Config:       $APP_DIR/.env"
echo "Data dir:     $APP_DIR/data"
echo "Backups:      $APP_DIR/backups"
echo "Logs:         /var/log/cte-time"
echo
if ! $USE_HTTPS; then
    echo "Next steps:"
    echo "  1. Edit $APP_DIR/.env for any additional settings"
    echo "  2. For HTTPS setup: sudo certbot --nginx -d $DOMAIN"
fi
echo "Deploy updates:  sudo $APP_DIR/deploy.sh"
echo
