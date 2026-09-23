"""
deploy/migrate_sqlite_to_postgres.py – One-time migration of an
existing agaram_finance.db (SQLite, from the old local .exe deployment
or a dev database) into a PostgreSQL database, with row-count and
financial-total verification (audit item — "migration script with
record-count and financial-balance verification").

Usage:

    export SECRET_KEY=...                 # required by config.py
    export DATABASE_URL=postgresql+psycopg://user:pass@host/agaram_finance
    python deploy/migrate_sqlite_to_postgres.py /path/to/agaram_finance.db

What it does:
  1. Creates the Postgres schema (same as `flask init-db`) if not
     already present.
  2. Copies every row from every table, oldest table first
     (users -> customers -> loans -> payments -> backups ->
     loan_transactions -> audit_logs) so foreign-key-shaped
     relationships (by name, not an actual FK constraint in this
     schema) land in a sane order.
  3. Verifies row counts match between SQLite and Postgres for every
     table.
  4. Verifies the SUM of loan_amount, agreement_value, and
     balance_agreement across all loans matches between source and
     destination, to one rupee -- the one thing that must not silently
     drift during a money-table migration.
  5. Refuses to touch a non-empty Postgres database, so this can't be
     run twice by accident and double-insert everything.

This is a one-time operational script, not something the app imports.
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLES_IN_ORDER = [
    'users', 'customers', 'loans', 'payments',
    'backups', 'loan_transactions', 'audit_logs',
]

BOOLEAN_COLUMNS = {
    'users': {'is_active', 'must_change_password'},
    'customers': {'is_active'},
    'loans': {'guarantor_enabled'},
}


def _sqlite_rows(sqlite_path, table):
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"SELECT * FROM {table}")
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []  # table doesn't exist in the source (older schema version)
    finally:
        conn.close()


def main():
    if len(sys.argv) != 2:
        sys.exit(f'Usage: python {sys.argv[0]} /path/to/agaram_finance.db')
    sqlite_path = sys.argv[1]
    if not os.path.exists(sqlite_path):
        sys.exit(f'File not found: {sqlite_path}')

    os.environ.setdefault('APP_ENV', 'production')
    from app import create_app
    from database import create_schema, run, query, is_sqlite

    app = create_app()
    with app.app_context():
        if is_sqlite(app):
            sys.exit('DATABASE_URL points at SQLite -- set it to your '
                      'PostgreSQL connection string before running this.')

        create_schema(app)

        existing = query("SELECT COUNT(*) c FROM loans")[0]['c']
        if existing:
            sys.exit(f'Refusing to migrate: destination already has {existing} '
                      f'loan rows. This script only runs against an empty '
                      f'database, to avoid double-inserting.')

        print(f'Migrating {sqlite_path} -> {app.config["DATABASE_URL"]}\n')

        source_counts = {}
        for table in TABLES_IN_ORDER:
            rows = _sqlite_rows(sqlite_path, table)
            source_counts[table] = len(rows)
            if not rows:
                print(f'  {table:20s}  0 rows (skipped)')
                continue

            bool_cols = BOOLEAN_COLUMNS.get(table, set())
            cols = list(rows[0].keys())
            col_list = ', '.join(cols)
            placeholders = ', '.join('?' * len(cols))
            for r in rows:
                values = []
                for c in cols:
                    v = r[c]
                    if c in bool_cols and v is not None:
                        v = bool(v)
                    values.append(v)
                run(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", tuple(values))
            print(f'  {table:20s}  {len(rows)} rows migrated')

        print('\nVerifying...')
        all_ok = True
        for table, expected in source_counts.items():
            actual = query(f"SELECT COUNT(*) c FROM {table}")[0]['c']
            status = 'OK' if actual == expected else 'MISMATCH'
            if actual != expected:
                all_ok = False
            print(f'  {table:20s}  expected {expected:5d}  got {actual:5d}  [{status}]')

        # Financial-total check: the one number that must not drift.
        src_conn = sqlite3.connect(sqlite_path)
        try:
            src_totals = src_conn.execute(
                "SELECT ROUND(SUM(loan_amount),2), ROUND(SUM(agreement_value),2), "
                "ROUND(SUM(balance_agreement),2) FROM loans").fetchone()
        finally:
            src_conn.close()
        dst_row = query(
            "SELECT ROUND(SUM(loan_amount)::numeric,2) a, ROUND(SUM(agreement_value)::numeric,2) b, "
            "ROUND(SUM(balance_agreement)::numeric,2) c FROM loans")[0]
        dst_totals = (float(dst_row['a'] or 0), float(dst_row['b'] or 0), float(dst_row['c'] or 0))
        src_totals = tuple(float(x or 0) for x in src_totals)

        print(f'\n  Loan totals (loan_amount, agreement_value, balance_agreement):')
        print(f'    source:      {src_totals}')
        print(f'    destination: {dst_totals}')
        if src_totals != dst_totals:
            all_ok = False
            print('    MISMATCH -- do not trust this migration, investigate before using it.')
        else:
            print('    OK -- totals match exactly.')

        if not all_ok:
            sys.exit('\nMigration completed with MISMATCHES. Do not cut over -- investigate first.')
        print('\nMigration verified OK.')


if __name__ == '__main__':
    main()
