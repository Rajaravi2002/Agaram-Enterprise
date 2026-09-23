# Agaram Finance — Stage 3: Security

Builds on Stages 1-2. CSRF, audit logging, XSS fixes, login hardening,
Aadhaar masking, security headers — audit items 15, 16, 17, 31, 38,
39, 42, 43 (partially).

## CSRF — now actually enabled

All 13 POST templates carry `{{ csrf_token() }}`:
`auth/login`, `loans/create`, `loans/edit`, `loans/topup`,
`loans/penalty`, `loans/view` (mark-overdue + close), `customers/add`,
`customers/edit`, `customers/view` (delete), `payments/collect`,
`settlement/index`, `backup/index` (create x2 + restore),
`backup/import_excel`. `csrf.init_app(app)` is now called in
`app.py`. Verified end-to-end: a request with a valid token succeeds,
a request with a garbage token gets a 400.

## A real bug this caught: `routes/backup.py` restore was broken

While wiring up audit logging I found `routes/backup.py`'s `restore()`
was still calling the **old raw sqlite3 connection API**
(`db.execute("PRAGMA foreign_keys=OFF")`, `db.executemany(...)`,
`db.commit()`) that Stage 1 replaced with the SQLAlchemy-backed
`run()`/`query()` layer. That file wasn't touched in Stage 1 or 2, and
nothing caught it because nothing had exercised restore end-to-end
until now — it would have thrown `ObjectNotExecutableError` (SQLAlchemy
connections don't accept bare SQL strings) the first time anyone
actually clicked "Restore" in production. Rewrote it to use
`run()`/`query()` like the rest of the app, dropped the SQLite-only
`INSERT OR REPLACE` (plain `INSERT` after `DELETE` is portable to
Postgres), and verified a full backup → restore round-trip preserves
row counts. **This is still the audit's flagged-dangerous restore
pattern otherwise** (DELETE-then-INSERT with no pre-restore safety
backup, no staging validation) — item 27's full rewrite is not done,
just made to actually function on the new database layer.

## Audit logging — `services/audit_log.py`

`record(action, entity_type, entity_id, old_value, new_value)` writes
to `audit_logs`, auto-filling `user_id`/`username` from
`flask_login.current_user` and `ip_address` from the request. Wired
into: login/login-failed/logout, loan create/edit/topup, payment
collection, settlement collection + the resulting loan closure,
customer create/edit/deactivate, backup create/restore, Excel import.
Verified in this environment: a login → loan create → payment collect
sequence produced exactly the right `LOGIN`, `LOAN_CREATED`,
`PAYMENT_COLLECTED` rows with the correct username.

## Login hardening (`routes/auth.py`)

- **Open redirect fixed** (audit item 16): `next=` is now validated
  to be a same-site path (`_safe_next_url`) — an absolute URL or
  protocol-relative `//evil.example.com` is rejected and falls back to
  the dashboard.
- **Basic lockout**: 5 failed attempts per username locks that
  username out for 15 minutes. Verified: the 6th attempt in a row
  returns the lockout message. **This is in-process memory only** —
  with Gunicorn's `-w 3` workers each has its own counter, and it
  resets on every deploy/restart. The real defense is
  `deploy/nginx.conf`'s `limit_req zone=login` (Stage 1) plus, for
  anything beyond a single worker, Flask-Limiter with a shared Redis
  backend — this in-process check is a cheap second layer, not a
  replacement for either.
- **Forced password change**: `must_change_password` (already a
  column, previously unused) now actually redirects to a new
  `/change-password` page after login. `manage.py create-admin`
  leaves it unset since you typed your own password there.

## XSS fixes (`static/js/main.js`, `templates/dashboard/index.html`, and others)

Added `escapeHtml()` and used it everywhere a DB-sourced string
(customer name, loan ID, payment ID, loan status) was interpolated
into `innerHTML` without escaping: the global search dropdown, the
loan-ID duplicate checker, the autocomplete widget, the dashboard's
recent-activity table, the guarantor-surety preview, and the
settlement/payment-collect AJAX previews. A crafted customer name
containing e.g. `<img src=x onerror=...>` would previously have
executed in any staff member's browser who searched for it or viewed
the dashboard.

**Also fixed audit item 37 along the way**: the search dropdown linked
to `/customers/view/<name>`, which matches no real route
(`/customers/<int:cid>` is the actual one) — clicking a customer from
search 404'd. Now links to `/customers/<id>`, which the API already
returned but the frontend wasn't using.

## Aadhaar masking (audit item 31)

`routes/customers.py._mask_aadhaar()` — non-admins see `XXXX-XXXX-1234`
everywhere: the customer view page, the customer edit page, and a
non-admin submitting a changed Aadhaar value on edit is silently
ignored (same server-controlled-field pattern as loan financial
fields in Stage 2). The bulk customer Excel export
(`routes/reports.py`) also masks for non-admins. Verified: a staff
login sees the masked value and the full 12-digit number does not
appear anywhere in that response; an admin login sees the full value.

## Security headers

`app.py` now sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: SAMEORIGIN`, `Referrer-Policy:
strict-origin-when-cross-origin` on every response.
`Strict-Transport-Security` stays in `deploy/nginx.conf` (Stage 1) —
that's the TLS-terminating layer, the right place for it.
**Content-Security-Policy is deliberately not added yet**: the
templates load Bootstrap/Bootstrap Icons/Google Fonts/Chart.js from
CDNs (audit item 41), and a CSP tight enough to matter would break all
of that until those assets are self-hosted or pinned — shipping a
no-op or broken CSP isn't worth it. That's real follow-up work, not
done here.

## Tested

15 unit tests still pass unchanged. Full request-level smoke test
re-run with CSRF actually enforced this time: login (valid token
succeeds) → loan create (valid token succeeds, garbage token gets
400) → payment collect → verified `audit_logs` has the right
LOGIN/LOAN_CREATED/PAYMENT_COLLECTED rows → backup create → **backup
restore** (the fixed code path) verified to preserve row counts →
fresh unauthenticated client locked out after 6 failed logins →
staff-role customer view confirmed masked Aadhaar with no full number
in the response, admin-role view confirmed the full number.

## What's NOT done yet

- `routes/backup.py` restore is *functional* now but still the
  audit's flagged-dangerous pattern otherwise: no pre-restore safety
  backup, no staging/validation step, not wrapped as one atomic
  operation the way Stage 1's per-request transaction would make
  trivial to add. Worth doing properly rather than as a rushed part of
  this stage.
- Excel import validation is still shallow (extension check only) —
  audit item 28.
- No rate limiting on `/api/search`, `/api/suggest/*` at the
  application level (Nginx config from Stage 1 only covers `/login`).
- CSP not added (see above).
- Login lockout is in-process only, as noted — fine for a single
  Gunicorn worker, not sufficient beyond that without Flask-Limiter +
  Redis.

## Suggested next step

**Stage 4 — PostgreSQL migration**: write and test the SQLite → Postgres
migration script with record-count and financial-balance verification,
smoke-test everything in this stage's own PostgreSQL-specific code
paths (the `SEQUENCE`-based ID generator, `Decimal` handling) against
a real Postgres instance rather than SQLite, since that still hasn't
happened in this sandboxed environment.
