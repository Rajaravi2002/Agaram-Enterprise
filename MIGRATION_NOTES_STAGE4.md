# Agaram Finance — Stage 4: PostgreSQL Migration

Builds on Stages 1-3. This stage is different from the others: instead
of writing new code against an assumption, it actually stood up a real
PostgreSQL 16 server and ran everything from Stages 1-3 against it.
That surfaced three real bugs that SQLite-only testing could not have
caught, all now fixed and re-verified.

## Real bugs found by testing against real Postgres

Everything below passed every test in Stages 1-3 because those tests
ran against SQLite, which is loosely typed enough to paper over these
problems. None of them are hypothetical — each one reproduces
immediately against a real Postgres instance and would have broken
the app on first deploy.

**1. The custom ID sequences were never actually created.**
`services`/`database.py`'s `loan_id_seq` / `payment_id_seq` were
defined as bare `Sequence(...)` objects. `metadata.create_all()` does
not create standalone sequences unless they're bound to the metadata
— so `flask init-db` silently created every table but neither
sequence, and the very first loan creation would have thrown
`UndefinedTable: relation "loan_id_seq" does not exist`. Fixed by
passing `metadata=metadata` to both `Sequence(...)` calls.

**2. `conn.execute(sequence)` is deprecated and returns something
different than expected.** Once the sequences existed, `next_loan_id()`
/ `next_payment_id()` called `.scalar()` on the result of
`conn.execute(sequence)`, which is deprecated in this SQLAlchemy
version and, worse, `conn.execute()` on a `Sequence` now returns a
plain `int` directly — so `.scalar()` on an `int` raised
`AttributeError`. Fixed by switching to `conn.scalar(sequence)`, the
non-deprecated call.

**3. Boolean columns: SQLite accepts `1`/`0` for anything; Postgres's
real `boolean` type does not — anywhere.** This was the big one. Every
`is_active`, `must_change_password`, and `guarantor_enabled` write or
comparison throughout `routes/*.py` and `services/*.py` was written as
plain `1`/`0`, either as a bound parameter or as a literal baked into
the SQL text (`... VALUES (?,?,?,1)`, `WHERE is_active = 1`). SQLite
silently accepts both forms for any column. Postgres rejects both:
`DatatypeMismatch: column "is_active" is of type boolean but
expression is of type integer` for the INSERT/UPDATE case, and
`UndefinedFunction: operator does not exist: boolean = integer` for
comparisons. This broke **login, loan creation, loan top-up (via
`guarantor_enabled`), the loan-create page's customer dropdown, the
dashboard, the customers list, and customer deactivation** — in other
words, most of the app.

Rewriting every call site would have broken Stage 1's core design
promise ("routes don't need to change for the engine underneath to be
Postgres"), so the fix lives in `database.py`'s compatibility layer
instead: `_coerce_boolean_params()` inspects the target table's schema
(already known via `metadata`, from Stage 1) and, for any column typed
`Boolean`,
- coerces a bound `:pN` parameter to a real Python `bool`,
- rewrites a bare `col = 1` / `col = 0` comparison anywhere in the SQL
  text to `col = TRUE` / `col = FALSE`, and
- rewrites a positional `1`/`0` literal inside an `INSERT ... VALUES
  (...)` list the same way.

No route or service file needed to change. Verified by re-running the
exact same login → create → top-up → collect → settle → customers-list
→ dashboard → backup-create → backup-restore → customer-deactivate
sequence from Stages 2-3 against the real Postgres server — all green.

## `deploy/migrate_sqlite_to_postgres.py`

A one-time script for moving an existing `agaram_finance.db` (from the
old local `.exe` deployment, or a dev database with real data in it)
into Postgres:

```bash
export SECRET_KEY=...
export DATABASE_URL=postgresql+psycopg://user:pass@host/agaram_finance
python deploy/migrate_sqlite_to_postgres.py /path/to/agaram_finance.db
```

- Creates the Postgres schema if it doesn't exist yet.
- Copies every table (users, customers, loans, payments, backups,
  loan_transactions, audit_logs), coercing the same boolean columns on
  the way in.
- **Verifies row counts match** between source and destination for
  every table.
- **Verifies the SUM of `loan_amount`, `agreement_value`, and
  `balance_agreement`** across all loans matches to the rupee between
  source and destination — the one number that must not silently
  drift during a money-table migration, and the check the audit
  specifically asked for ("record-count and financial-balance
  verification").
- Refuses to run against a non-empty destination, so it can't be
  accidentally run twice and double-insert everything.

Ran this for real: seeded a SQLite database (`seed_data.py` — 5 loans,
57 payments, 1 admin user), migrated it, and got:

```
Loan totals (loan_amount, agreement_value, balance_agreement):
  source:      (151500.0, 184090.0, 28021.01)
  destination: (151500.0, 184090.0, 28021.01)
  OK -- totals match exactly.
```

Then logged in as the migrated admin user and confirmed a migrated
loan's payment history, view page, and settlement calculation all work
correctly post-migration.

## Tested

Everything in this stage was tested against a real, locally-installed
PostgreSQL 16 server (not SQLite) — schema creation, sequence-based ID
generation, the full request-level flow from Stage 2/3 (login → loan
create with a guarantor → top-up → EMI collection → settlement calc),
the customers list and dashboard (both use `is_active=1` literal
queries), backup create and restore, customer deactivation, the
`manage.py create-admin` CLI, `seed_data.py`, and the migration script
itself with its verification step. The 15 unit tests still pass
unchanged (they don't touch the database). This closes out the
caveat that's been in every prior stage's notes: "PostgreSQL-specific
paths could not be exercised end-to-end here."

## What's NOT done yet

- Real Alembic migrations still aren't set up — `flask init-db` uses
  `metadata.create_all(checkfirst=True)`, fine for the initial deploy
  but not for evolving the schema later without a migration tool.
- The financial-total verification in the migration script only
  checks `loans` totals, not a full reconciliation against `payments`
  — good enough to catch a migration that dropped or corrupted rows,
  not a substitute for an accountant checking the numbers before
  cutover.
- No load/concurrency testing of the sequence-based ID generator under
  real concurrent writers (the whole point of moving off "max+1", but
  unverified under actual concurrent load in this environment).

## Suggested next step

**Stage 5 — Server deployment**: this is now genuinely ready to point
`deploy/agaram-finance.service` + `deploy/nginx.conf` (from Stage 1) at
a real Ubuntu box with Postgres installed, run the migration script
against production data, and cut over.
