# Agaram Finance — Stage 1: Production Code Cleanup

This is Stage 1 of the 5-stage plan from the production audit, covering:
`config.py`, `database.py`, `app.py`, `run.py`, `requirements.txt`,
`seed_data.py`, plus the deployment scaffolding needed to actually run
the result (systemd unit, Nginx config, backup cron script).

**Nothing in `routes/*.py` or `templates/*.html` was touched in this
stage.** That is intentional — see "What's NOT done yet" below.

## What changed and why

- **`config.py`** — `SECRET_KEY` and `DATABASE_URL` are now required
  environment variables with no insecure fallback; the app refuses to
  start without them. Session cookies get `Secure` (in production),
  `HttpOnly`, `SameSite=Lax`. Upload size is capped at `MAX_UPLOAD_MB`
  (default 10MB).

- **`database.py`** — Rewritten on SQLAlchemy Core, works against both
  SQLite (dev) and PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`)
  via the same engine code.
  - **One transaction per request.** `get_db()` opens a transaction on
    first use; `close_db()` commits it at the end of the request, or
    rolls it back if the request raised. This is what fixes the
    "customer inserted but loan insert failed" class of bug — no route
    code had to change to get this.
  - **`?`-placeholder shim.** Every route still uses the exact same
    `query("... WHERE x=?", (val,))` calls they always did. A small
    translator (`_qmark_to_named`) rewrites `?` into SQLAlchemy bind
    params internally, so **no route file needed touching** to move
    off raw sqlite3.
  - **Money columns are `NUMERIC(12,2)`**, not floating point. Because
    routes still do plain float arithmetic, `query()`/`one()`
    auto-convert any `Decimal` the DB returns back into `float` before
    handing rows to route code — storage is exact, in-memory math is
    unchanged for now. **Stage 2 (finance services) should replace this
    bridge** with proper Decimal-safe calculation objects, per audit
    items 7–10 (float money, formula duplication, rounding
    inconsistency).
  - **Loan/payment IDs come from a Postgres `SEQUENCE`**, not
    "max + 1", removing the race condition audit item 6 flagged. On
    SQLite (dev only) it still falls back to max+1 — fine for a single
    local dev DB, never for production.
  - **No more auto-seeded `admin`/`staff` accounts.** Schema creation
    (`flask init-db`) makes tables only. Use `flask create-admin` to
    interactively create the first real account with a password you
    choose (12+ chars, confirmed, hashed).

- **`app.py`** — Schema creation and the old background-thread scheduler
  no longer run automatically at every worker boot (they'd race across
  Gunicorn's multiple workers). Schema is created once via `flask
  init-db`; backups move to `deploy/backup.sh` on a systemd timer/cron.
  Added generic error pages for 400/403/404/413/429/500 so Flask never
  shows a raw traceback, SQL, or file path to a user.

- **`run.py`** — No longer runs `app.run(host='0.0.0.0', port=5000)`.
  Production entrypoint is `gunicorn -w 3 -b 127.0.0.1:8000 run:app`
  behind Nginx (see `deploy/`); the dev fallback binds to `127.0.0.1`
  only.

- **`requirements.txt`** — Added SQLAlchemy, `psycopg[binary]`,
  gunicorn, python-dotenv, Flask-WTF (installed but not yet wired up —
  see below), removed nothing you were using.

- **`seed_data.py`** — Refuses to run when `APP_ENV=production`; sample
  phone numbers are now obviously fake (`9000000001`...) instead of
  real-looking numbers.

- **`deploy/`** — `agaram-finance.service` (systemd + Gunicorn),
  `nginx.conf` (HTTPS redirect, HSTS/X-Content-Type-Options/X-Frame-
  Options headers, login rate-limit hook, static file serving),
  `backup.sh` (nightly `pg_dump`, retention cleanup, off-site upload
  stub for you to fill in with S3/rsync/etc).

## Tested

Ran against a real SQLite dev DB in this environment:
`flask init-db` equivalent (`create_schema`) creates all tables
including the new `audit_logs` table; a full login POST persists
`last_login` inside the new per-request transaction; a multi-field
loan insert round-trips correctly through the `?`→named-param shim.
PostgreSQL-specific paths (the `SEQUENCE`-based ID generator, the
`Decimal`→`float` bridge under real NUMERIC columns) are written for
psycopg3 but **could not be exercised end-to-end here** — there's no
Postgres server in this environment. Run `flask init-db` then
`flask create-admin` against your actual Postgres instance and
smoke-test loan creation before trusting it with real data.

## What's NOT done yet (later stages, on purpose)

- **CSRF is installed but not enabled.** `Flask-WTF` is in
  requirements and `CSRFProtect` is imported in `app.py`, but
  `csrf.init_app(app)` is commented out. Turning it on today would
  400 every POST form in the app — none of the 13 templates
  (login, loan create/edit/topup, payment collect, settlement,
  backup/restore, Excel import) carry a `{{ csrf_token() }}` field
  yet. That's Stage 3 work, done as one pass so nothing breaks
  mid-way.
- Financial calculations still live inside `routes/loans.py`,
  `routes/payments.py`, `routes/settlement.py` rather than a
  `services/` layer; the interest-rate and monthly-due formula
  inconsistencies (audit items 9–10) are still there.
- User-supplied financial fields (`paid_due`, `balance_agreement`,
  etc.) can still be overwritten from the browser on loan edit —
  audit item 19B.
- No audit-log writes yet (table exists, nothing populates it).
- `routes/backup.py` restore flow is unchanged — still the
  dangerous DELETE-then-restore pattern (audit item 27).
- Excel import validation is unchanged (audit item 28).
- XSS (`innerHTML` in `static/js/main.js`), CSP, and security headers
  at the app level are unchanged — the Nginx headers in `deploy/nginx.conf`
  cover the transport layer only.

## Deploying this stage

```bash
cp .env.example .env        # fill in SECRET_KEY, DATABASE_URL, etc.
pip install -r requirements.txt
flask --app run init-db     # create tables + sequences on Postgres
flask --app run create-admin
sudo cp deploy/agaram-finance.service /etc/systemd/system/
sudo systemctl enable --now agaram-finance
# configure deploy/nginx.conf with your real domain + TLS cert
crontab -e   # add: 0 2 * * * /opt/agaram_finance/deploy/backup.sh
```

## Suggested next step

**Stage 2 — Finance engine**: pull the loan/payment/settlement math out
of the routes into `services/loan_service.py`, `payment_service.py`,
`settlement_service.py`, fix the interest-rate and monthly-due formula
duplication, stop the top-up dead-code overwrite, and add the
`loan_transactions` ledger table. That unblocks a clean Decimal
migration and gives you something testable in isolation from Flask.
