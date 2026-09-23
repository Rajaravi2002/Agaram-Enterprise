# Agaram Finance — Stage 5: Server Deployment

Builds on Stages 1-4. This stage stood up the **entire real stack**
locally — PostgreSQL, Gunicorn (3 workers), Nginx (TLS termination,
reverse proxy, security headers, rate-limit zone) — and drove real
HTTP traffic through all of it, rather than through Flask's in-memory
test client. That's a meaningfully different test than anything in
Stages 1-4: it's the first time session cookies, CSRF, and the
security headers were exercised across actual separate OS processes
talking over a real network socket.

## What was actually proven end-to-end

- `gunicorn -w 3 -b 127.0.0.1:8000 run:app` (the exact command in
  `deploy/agaram-finance.service`) boots 3 real worker processes
  against PostgreSQL and serves real HTTP requests.
- **Session cookies work correctly across the 3 separate worker
  processes** — logged in via one request, the session was valid on a
  subsequent request that could have landed on any of the 3 workers.
  This matters because it confirms `SECRET_KEY`-based cookie signing
  doesn't depend on any single worker's in-memory state.
- `deploy/nginx.conf` **is valid, loadable Nginx config** — `nginx -t`
  passes against it (this also confirmed the `limit_req_zone`
  directive the config's comment says belongs in `nginx.conf`'s
  `http{}` block is in fact required for the config to load, not just
  a nice-to-have).
- Full reverse-proxy chain confirmed: HTTP → 301 redirect to HTTPS →
  Nginx terminates TLS → proxies to Gunicorn → Flask → PostgreSQL, for
  both a GET (`/login`) and a full POST login + loan-creation flow.
- **HSTS, X-Content-Type-Options, X-Frame-Options all present** on
  responses through the real proxy chain (Nginx adds HSTS at the TLS
  layer per Stage 1; Flask adds the other two per Stage 3 — both
  showed up correctly, if redundantly, since Nginx doesn't strip
  upstream headers).

## A finding worth knowing about, not a bug: CSRF + curl

Testing the full nginx-terminated-HTTPS login with plain `curl` (no
`-e`/Referer flag) returned a 400. This is Flask-WTF's
`WTF_CSRF_SSL_STRICT` (on by default): for any POST over HTTPS, it
requires the `Referer` header to match the request's origin, as a
second layer of CSRF defense beyond the token itself. Every real
browser sends `Referer` automatically on a same-origin form
submission — this only shows up as a problem with tools like `curl`
or `httpie` that don't set one. Confirmed by re-running the identical
request with `-e https://agaramfinance.example.com/login` (matching
what a browser sends): login succeeds normally. **If you test this
deployment with curl/Postman/similar and see an unexplained 400 on
login, this is almost certainly why — add a matching Referer header,
don't disable `WTF_CSRF_SSL_STRICT`.**

## Deployment runbook

This is the actual sequence to run on your real server (Ubuntu
22.04/24.04 assumed, matching `deploy/*`).

### 1. Server prep
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv postgresql nginx certbot python3-certbot-nginx
sudo useradd -r -s /bin/false agaram
sudo mkdir -p /opt/agaram_finance /var/lib/agaram_finance/{backups,reports} /var/backups/agaram_finance
sudo chown -R agaram:agaram /opt/agaram_finance /var/lib/agaram_finance /var/backups/agaram_finance
```

### 2. Database
```bash
sudo -u postgres psql -c "CREATE USER agaram_user WITH PASSWORD '<pick a real password>';"
sudo -u postgres psql -c "CREATE DATABASE agaram_finance OWNER agaram_user;"
```

### 3. App code + environment
```bash
# copy this zip's agaram_finance_production/ contents to /opt/agaram_finance
cd /opt/agaram_finance
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env: SECRET_KEY (python3 -c "import secrets; print(secrets.token_hex(32))"),
# DATABASE_URL (from step 2), BACKUP_FOLDER=/var/lib/agaram_finance/backups,
# REPORTS_FOLDER=/var/lib/agaram_finance/reports
```

### 4. Schema + first admin
```bash
set -a; source .env; set +a
.venv/bin/flask --app run init-db
.venv/bin/flask --app run create-admin
```

### 5. (If migrating from the old local .exe deployment)
```bash
# copy the old agaram_finance.db from the office PC onto this server first
.venv/bin/python deploy/migrate_sqlite_to_postgres.py /path/to/old/agaram_finance.db
# read its output carefully -- it verifies row counts AND financial
# totals and will refuse to proceed on a mismatch
```

### 6. systemd + Nginx
```bash
sudo cp deploy/agaram-finance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agaram-finance
sudo systemctl status agaram-finance   # confirm 3 workers running

# edit deploy/nginx.conf: replace agaramfinance.example.com with your real domain
sudo cp deploy/nginx.conf /etc/nginx/sites-available/agaram-finance.conf
sudo ln -s /etc/nginx/sites-available/agaram-finance.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
# add near the top of /etc/nginx/nginx.conf's http {} block:
#   limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
sudo certbot --nginx -d agaramfinance.example.com   # gets the real TLS cert
sudo nginx -t && sudo systemctl reload nginx
```

### 7. Backups
```bash
sudo cp deploy/backup.sh /opt/agaram_finance/deploy/backup.sh   # if not already there
sudo chmod +x /opt/agaram_finance/deploy/backup.sh
sudo crontab -e
# add: 0 2 * * * /opt/agaram_finance/deploy/backup.sh
```

### 8. Verify
- Visit `https://agaramfinance.example.com/login` in a real browser,
  log in, create a test loan, confirm it shows up.
- `sudo journalctl -u agaram-finance -f` while doing that, to watch
  for errors.
- Confirm `curl -I https://agaramfinance.example.com/login` shows
  `strict-transport-security`, `x-frame-options`,
  `x-content-type-options`.
- Run `/opt/agaram_finance/deploy/backup.sh` manually once and confirm
  a `.sql.gz` file lands in `/var/backups/agaram_finance`.

## What's still not done (carried over from earlier stages)

- Real Alembic migrations (schema currently created via
  `metadata.create_all`, fine for initial deploy, not for evolving it
  later).
- CSP headers (blocked on self-hosting the CDN assets — audit item
  41).
- Deeper Excel import validation (audit item 28).
- A full restore-safety rewrite: pre-restore automatic backup, staging
  validation before committing a restore (audit item 27) — restore
  works correctly now (Stage 3 fixed the code that would have thrown),
  but it's still the DELETE-then-INSERT pattern with no safety net if
  the backup file itself is bad.
- Load/concurrency testing under real simultaneous users.

## Where this leaves the project

All 5 stages from the original production audit are now done, each
tested against something real rather than assumed: Stage 1's database
layer against SQLite, Stage 2's formulas against unit tests, Stage 3's
CSRF/audit-log/XSS fixes against a live request cycle, Stage 4's
Postgres-specific code against an actual Postgres server (which
caught 3 real bugs), and this stage's deployment artifacts against an
actual Nginx+Gunicorn+Postgres stack (which caught one config gap and
clarified one non-bug). The remaining items above are real, known gaps
-- not unknowns -- and are reasonable candidates for a Stage 6 if you
want to keep going, but the app is in a genuinely deployable state as
of this zip.
