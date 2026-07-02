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

       git clone <repo-url> /opt/cte-time
       cd /opt/cte-time

2. Create a Python virtual environment and activate it:

       python3 -m venv .venv
       source .venv/bin/activate

3. Install dependencies:

       pip install -r requirements.txt

4. Configure environment variables in /opt/cte-time/.env:

       SECRET_KEY=<64-char-random-hex>
       DATABASE_PATH=/opt/cte-time/data/cte_time.db
       HOST=127.0.0.1
       PORT=8000
       DISPLAY_TIMEZONE=America/Denver
       IS_PRODUCTION=true
       SESSION_MAX_AGE=28800
       SESSION_SAME_SITE=lax

    For first-run admin bootstrap, add these to create the initial admin account:

        ADMIN_EMAIL=admin@example.com
        ADMIN_PASSWORD=<strong-password>

    On first application start, if no admin accounts exist in the database, an admin
    will be created with these credentials. The admin is created with bcrypt-hashed
    password and the event is logged. Once seeded, subsequent startups do not
    overwrite the admin — you can remove or change ADMIN_EMAIL/ADMIN_PASSWORD afterward.

    Generate the SECRET_KEY:

        python3 -c "import secrets; print(secrets.token_hex(32))"

    Lock down .env permissions for production:

        sudo chown www-data:www-data /opt/cte-time/.env
        sudo chmod 600 /opt/cte-time/.env

5. Create the data directory:

       mkdir -p /opt/cte-time/data
       mkdir -p /var/log/cte-time

6. Run database migrations (automatically runs on first start).

Running
-------

Start the application server:

    cd /opt/cte-time
    source .venv/bin/activate
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Production with systemd
-----------------------

Create /etc/systemd/system/cte-time.service:

    [Unit]
    Description=CTE Time Application
    After=network.target

    [Service]
    User=www-data
    WorkingDirectory=/opt/cte-time
    EnvironmentFile=/opt/cte-time/.env
    ExecStart=/opt/cte-time/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target

Enable and start the service:

    sudo systemctl daemon-reload
    sudo systemctl enable cte-time
    sudo systemctl start cte-time

nginx Reverse Proxy
-------------------

Create /etc/nginx/sites-available/cte-time:

    server {
        listen 80;
        server_name cte-time.example.com;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        server_name cte-time.example.com;

        ssl_certificate /etc/letsencrypt/live/cte-time.example.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/cte-time.example.com/privkey.pem;

        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

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

    chmod +x /opt/cte-time/deploy/backup.sh

Run it manually:

    /opt/cte-time/deploy/backup.sh

Add a cron job:

    0 2 * * * /opt/cte-time/deploy/backup.sh

Also rely on a third-party backup solution for full machine recovery.

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
- `deploy/cte-time.service`
- `deploy/nginx-cte-time.conf`

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
