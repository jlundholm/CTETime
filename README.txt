CTE Time — Deployment Guide
=============================

Prerequisites
-------------
- Ubuntu 26.04 LTS VM (on-prem or cloud)
- Python 3.14+
- nginx
- Git

Installation
------------

1. Clone the repository:

       git clone https://github.com/jlundholm/CTETime /opt/cte-time
       cd /opt/cte-time

2. Create a Python virtual environment and activate it:

       python3 -m venv .venv
       source .venv/bin/activate

3. Install dependencies:

       pip install -r requirements.txt

4. Create the environment configuration from the template:

       cp .env.example .env

    This copies all available settings with documented defaults. Then edit .env:

       nano .env

    At minimum, generate and set a strong SECRET_KEY:

        python3 -c "import secrets; print(secrets.token_hex(32))"

    IMPORTANT — Admin bootstrap (first run only):
    These are commented out in .env.example. Uncomment and set them BEFORE
    starting the app:

        ADMIN_EMAIL=admin@example.com
        ADMIN_PASSWORD=<your-chosen-password>

    On first startup, if ADMIN_EMAIL and ADMIN_PASSWORD are set and no admin
    account exists in the database, an admin is created with those exact
    credentials (bcrypt-hashed, logged to file). These are your login
    credentials for the admin panel — they are not displayed on screen.

    If you skip this step (leave both commented out), no admin account is
    created. You can add them to .env later and restart the service.

    Once seeded, subsequent startups do not overwrite the admin — you can
    remove or change ADMIN_EMAIL/ADMIN_PASSWORD afterward.

    WARNING: .env is in .gitignore — it will never be committed. Keep it that way.

 5. Set ownership and permissions for all deployed files.
    The app runs as ``www-data`` but only needs read access to the code.
    Secrets and writable directories need specific ownership:

        sudo chown -R root:root /opt/cte-time
        sudo chown root:www-data /opt/cte-time/.env
        sudo chmod 640 /opt/cte-time/.env
        sudo mkdir -p /opt/cte-time/data
        sudo chown www-data:www-data /opt/cte-time/data
        sudo chmod 750 /opt/cte-time/data
        sudo mkdir -p /var/log/cte-time
        sudo chown www-data:www-data /var/log/cte-time

    After first startup, the database file is created. Lock down its permissions
    so the app can read/write it but only root can change ownership:

        sudo chown www-data:www-data /opt/cte-time/data/cte_time.db
        sudo chmod 644 /opt/cte-time/data/cte_time.db

    The backup script creates backups in /opt/cte-time/backups. Create the
    directory and restrict access:

        sudo mkdir -p /opt/cte-time/backups
        sudo chown root:root /opt/cte-time/backups
        sudo chmod 750 /opt/cte-time/backups

 6. Run database migrations (automatically runs on first start).

Running
-------

Start the application server or use systemcd below:

    cd /opt/cte-time
    source .venv/bin/activate
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Production with systemd
-----------------------

Copy the systemd service unit from the repository:

    sudo cp /opt/cte-time/deploy/cte-time.service /etc/systemd/system/cte-time.service
    sudo chmod 644 /etc/systemd/system/cte-time.service

Enable and start the service:

    sudo systemctl daemon-reload
    sudo systemctl enable cte-time
    sudo systemctl start cte-time

Verify the service is running:

    systemctl status cte-time --no-pager

nginx Reverse Proxy
-------------------

Copy the hardened nginx config from the repository:

    sudo cp /opt/cte-time/deploy/nginx-cte-time.conf /etc/nginx/sites-available/cte-time

Enable the site:

    sudo ln -s /etc/nginx/sites-available/cte-time /etc/nginx/sites-enabled/
    sudo nginx -t
    sudo systemctl reload nginx

For HTTPS certificate provisioning via Certbot:

    sudo apt install certbot python3-certbot-nginx
    sudo certbot --nginx -d cte-time.example.com

Database Backup
---------------

Use the backup script for daily SQLite dumps:

    chmod +x /opt/cte-time/backup.sh

Run it manually:

    /opt/cte-time/backup.sh

Add a cron job:

    0 2 * * * /opt/cte-time/backup.sh

Also rely on a third-party backup solution for full machine recovery.

Health Check
------------

The application exposes a health check endpoint at ``/health``:

    curl http://127.0.0.1:8000/health

Response: ``{"status":"ok","version":"1.0.0","database":"connected"}``

Use this for load balancer health checks or monitoring (e.g., Prometheus blackbox exporter).

Logging
-------

Logs are written to /var/log/cte-time/ with automatic rotation.

Deployment Updates
------------------

Use the deployment script:

    sudo /opt/cte-time/deploy.sh

The script performs:
- `git pull`
- dependency install via `.venv/bin/pip install --no-input --upgrade -r requirements.txt`
- `systemctl restart cte-time`

System deployment templates are stored in this repository:
- `deploy/cte-time.service` — systemd unit
- `deploy/nginx-cte-time.conf` — nginx reverse proxy with TLS hardening and security headers
- `backup.sh` — automated backup with WAL checkpoint, retention, and lock safety (also at `deploy/backup.sh`)

Development
-----------

For local development with hot reload:

    cd /opt/cte-time
    source .venv/bin/activate
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

Testing
-------

Run the full test suite:

    source .venv/bin/activate
    pytest -v
