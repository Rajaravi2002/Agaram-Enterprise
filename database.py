"""
database.py – SQLAlchemy-backed data-access layer for Agaram Finance.

Design goals for this stage:

1.  Routes keep using the same `query()` / `one()` / `run()` functions
    with the same `?`-style placeholders they already use. Nothing in
    routes/*.py has to change to get a real, transactional, Postgres-
    or SQLite-backed engine underneath. (The `?` placeholders are
    translated to SQLAlchemy bind parameters internally — see
    `_qmark_to_named`.)

2.  Every request runs inside ONE database transaction. It is opened
    in `get_db()` on first use and committed in `close_db()` at the
    end of the request — or rolled back if the request raised. This
    is what fixes the "customer created but loan creation failed"
    class of bug (audit item 5) without every route having to manage
    BEGIN/COMMIT/ROLLBACK itself.

3.  Money columns are NUMERIC(12,2), not floating point (audit item 7).
    Because the existing route code still does plain float arithmetic
    (`loan_amount * tenure`, etc.) and a full rewrite of that math into
    Decimal-safe service objects is Stage 2 work, `query()`/`one()`
    auto-convert any `Decimal` value coming back from the database into
    `float` before handing rows to route code. Storage is exact;
    in-memory arithmetic in routes is unchanged for now. Stage 2 should
    replace this bridge with Decimal-aware service objects.

4.  Loan/payment IDs are generated from a database SEQUENCE (Postgres)
    instead of "select max, add one" (audit item 6 — race condition).
    On SQLite (dev only) there is no sequence support, so it falls back
    to the old max+1 behaviour, which is fine for a single-user local
    dev database but must never be used in production.

5.  No default admin/staff accounts are created here anymore (audit
    item — default credentials). See `manage.py create-admin`.
"""
import os
import re
import decimal
from datetime import datetime
from contextlib import contextmanager

from flask import g, current_app
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Numeric,
    Boolean, DateTime, Text, Sequence, text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

# ── Sequences (used on PostgreSQL; ignored/no-op on SQLite) ────────────────
# Must be bound to `metadata` explicitly -- a bare Sequence(...) is NOT
# created by metadata.create_all(); this was only caught by testing
# against a real Postgres instance, since SQLite's dev fallback path
# never touches these.
loan_id_seq    = Sequence('loan_id_seq', start=1, metadata=metadata)
payment_id_seq = Sequence('payment_id_seq', start=1, metadata=metadata)

# ── Schema ───────────────────────────────────────────────────────────────
users = Table(
    'users', metadata,
    Column('id', Integer, primary_key=True),
    Column('username', String(80), nullable=False, unique=True),
    Column('password_hash', String(255), nullable=False),
    Column('role', String(20), nullable=False, server_default='staff'),
    Column('full_name', String(120), nullable=False),
    Column('email', String(120), nullable=False, server_default=''),
    Column('is_active', Boolean, nullable=False, server_default='1'),
    Column('must_change_password', Boolean, nullable=False, server_default='1'),
    Column('created_at', DateTime, nullable=False),
    Column('last_login', DateTime),
)

customers = Table(
    'customers', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(120), nullable=False, unique=True),
    Column('phone', String(20), nullable=False, server_default=''),
    Column('alt_phone', String(20), nullable=False, server_default=''),
    Column('address', Text, nullable=False, server_default=''),
    Column('aadhaar', String(20), nullable=False, server_default=''),
    Column('occupation', String(120), nullable=False, server_default=''),
    Column('date_added', DateTime, nullable=False),
    Column('added_by', String(80), nullable=False, server_default=''),
    Column('is_active', Boolean, nullable=False, server_default='1'),
)

loans = Table(
    'loans', metadata,
    Column('id', Integer, primary_key=True),
    Column('loan_id', String(20), nullable=False, unique=True),
    Column('customer_name', String(120), nullable=False),
    Column('phone', String(20), nullable=False, server_default=''),
    Column('ref', String(120), nullable=False, server_default=''),
    Column('follower', String(120), nullable=False, server_default=''),
    Column('loan_date', DateTime, nullable=False),
    Column('due_day', String(10), nullable=False, server_default=''),
    Column('loan_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('document_charge', Numeric(12, 2), nullable=False, server_default='0'),
    Column('principle_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('interest_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('agreement_value', Numeric(12, 2), nullable=False, server_default='0'),
    Column('tenure', Integer, nullable=False, server_default='0'),
    Column('due_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('paid_due', Integer, nullable=False, server_default='0'),
    Column('paid_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('feature_dues', Integer, nullable=False, server_default='0'),
    Column('balance_agreement', Numeric(12, 2), nullable=False, server_default='0'),
    Column('int_pct', String(20), nullable=False, server_default=''),
    Column('interest_rate', Numeric(6, 3), nullable=False, server_default='0'),
    Column('vehicle_model', String(120), nullable=False, server_default=''),
    Column('vehicle_number', String(40), nullable=False, server_default=''),
    Column('document_status', String(60), nullable=False, server_default=''),
    Column('remarks', Text, nullable=False, server_default=''),
    Column('loan_status', String(20), nullable=False, server_default='active'),
    Column('penalty_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('penalty_description', Text, nullable=False, server_default=''),
    Column('topup_history', Text, nullable=False, server_default='[]'),
    Column('father_name', String(120), nullable=False, server_default=''),
    Column('address1', String(200), nullable=False, server_default=''),
    Column('address2', String(200), nullable=False, server_default=''),
    Column('address3', String(200), nullable=False, server_default=''),
    Column('pincode', String(10), nullable=False, server_default=''),
    Column('vehicle_cost', Numeric(12, 2), nullable=False, server_default='0'),
    Column('guarantor_enabled', Boolean, nullable=False, server_default='0'),
    Column('guarantor_name', String(120), nullable=False, server_default=''),
    Column('guarantor_phone', String(20), nullable=False, server_default=''),
    Column('guarantor_address', Text, nullable=False, server_default=''),
    Column('created_at', DateTime, nullable=False),
    Column('created_by', String(80), nullable=False, server_default=''),
    Column('closed_at', DateTime),
)

payments = Table(
    'payments', metadata,
    Column('id', Integer, primary_key=True),
    Column('payment_id', String(30), nullable=False, unique=True),
    Column('loan_id', String(20), nullable=False),
    Column('customer_name', String(120), nullable=False),
    Column('collection_date', DateTime, nullable=False),
    Column('payment_type', String(20), nullable=False, server_default='EMI'),
    Column('payment_mode', String(20), nullable=False, server_default='Cash'),
    Column('emi_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('carry_forward', Numeric(12, 2), nullable=False, server_default='0'),
    Column('total_due', Numeric(12, 2), nullable=False, server_default='0'),
    Column('paid_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('pending_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('outstanding_balance', Numeric(12, 2), nullable=False, server_default='0'),
    Column('settlement_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('principal_component', Numeric(12, 2), nullable=False, server_default='0'),
    Column('interest_component', Numeric(12, 2), nullable=False, server_default='0'),
    Column('month_number', Integer, nullable=False, server_default='1'),
    Column('penalty_amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('collection_remarks', Text, nullable=False, server_default=''),
    Column('collected_by', String(80), nullable=False, server_default=''),
    Column('created_at', DateTime, nullable=False),
)

backups = Table(
    'backups', metadata,
    Column('id', Integer, primary_key=True),
    Column('backup_id', String(40), nullable=False, unique=True),
    Column('backup_type', String(20), nullable=False, server_default='manual'),
    Column('file_path', Text, nullable=False),
    Column('file_name', String(200), nullable=False),
    Column('file_size', Integer, nullable=False, server_default='0'),
    Column('created_at', DateTime, nullable=False),
    Column('created_by', String(80), nullable=False, server_default=''),
    Column('status', String(20), nullable=False, server_default='success'),
)

# Append-only financial ledger (audit items 23/49). Populated by
# services/ledger.py starting in Stage 2.
loan_transactions = Table(
    'loan_transactions', metadata,
    Column('id', Integer, primary_key=True),
    Column('loan_id', String(20), nullable=False),
    Column('txn_type', String(20), nullable=False),  # ORIGINAL/EMI/TOPUP/PENALTY/SETTLEMENT
    Column('amount', Numeric(12, 2), nullable=False, server_default='0'),
    Column('note', Text, nullable=False, server_default=''),
    Column('created_by', String(80), nullable=False, server_default=''),
    Column('created_at', DateTime, nullable=False),
)

# Audit log table (schema only in this stage — routes start writing to it
# in Stage 3 when audit_service.py is introduced).
audit_logs = Table(
    'audit_logs', metadata,
    Column('id', Integer, primary_key=True),
    Column('user_id', Integer),
    Column('username', String(80)),
    Column('action', String(60), nullable=False),
    Column('entity_type', String(40)),
    Column('entity_id', String(40)),
    Column('old_value', Text),
    Column('new_value', Text),
    Column('ip_address', String(64)),
    Column('created_at', DateTime, nullable=False),
)


# ── Engine ───────────────────────────────────────────────────────────────
def _make_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith('sqlite'):
        connect_args = {'check_same_thread': False}
        return create_engine(database_url, connect_args=connect_args, future=True)
    # Postgres: small sane pool for a single-box Gunicorn deployment.
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        future=True,
    )


def init_engine(app):
    """Call once from create_app(). Stores the engine on the app object."""
    app.db_engine = _make_engine(app.config['DATABASE_URL'])
    return app.db_engine


def is_sqlite(app=None) -> bool:
    app = app or current_app
    return app.db_engine.dialect.name == 'sqlite'


# ── Per-request connection + transaction ────────────────────────────────
def get_db():
    """Return the connection for this request, opening a transaction on
    first use. All queries in a single request share one transaction,
    which is committed or rolled back in close_db()."""
    if 'db' not in g:
        g.db = current_app.db_engine.connect()
        g.db_trans = g.db.begin()
    return g.db


def close_db(exc=None):
    trans = g.pop('db_trans', None)
    conn = g.pop('db', None)
    if trans is not None:
        try:
            if exc is None:
                trans.commit()
            else:
                trans.rollback()
        finally:
            pass
    if conn is not None:
        conn.close()


@contextmanager
def transaction():
    """Explicit sub-step marker for service code (Stage 2). Because the
    whole request already runs in one transaction, this is a no-op savepoint
    boundary today, kept so service code can be written against a stable
    API and later upgraded to real SAVEPOINTs if nested rollback is needed."""
    conn = get_db()
    nested = conn.begin_nested() if conn.in_transaction() else conn.begin()
    try:
        yield conn
        nested.commit()
    except Exception:
        nested.rollback()
        raise


# ── `?`-placeholder compatibility shim ──────────────────────────────────
_QMARK_RE = re.compile(r'\?')


def _qmark_to_named(sql: str, params: tuple):
    """Rewrite `?` positional placeholders (SQLite style, used throughout
    routes/*.py) into SQLAlchemy `:pN` named placeholders, so route code
    doesn't need to change while the engine underneath can be Postgres."""
    if '?' not in sql:
        return sql, {}
    names = []

    def _sub(_match, counter=[0]):
        name = f'p{counter[0]}'
        counter[0] += 1
        names.append(name)
        return f':{name}'

    new_sql = _QMARK_RE.sub(_sub, sql)
    bound = {name: val for name, val in zip(names, params)}
    return new_sql, bound


def _row_to_dict(row):
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, decimal.Decimal):
            d[k] = float(v)
    return d


# ── Boolean-column coercion ──────────────────────────────────────────────
# SQLite's dynamic typing accepts a literal `1`/`0` for ANY column,
# so `?`-style SQL throughout routes/*.py and services/*.py freely
# writes and compares boolean columns (is_active, must_change_password,
# guarantor_enabled) as plain Python ints. PostgreSQL's real `boolean`
# type rejects that outright -- both a bound int parameter and an
# inline `1`/`0` literal raise DatatypeMismatch. This was only caught
# by testing against a real Postgres instance; every SQLite-only test
# in Stages 1-2 passed without ever exercising this path.
#
# Fixing every call site across the app would break Stage 1's "routes
# don't need to change" design, so the fix lives here instead: inspect
# the table's schema (already known via `metadata`) and coerce any
# bound parameter that lines up with a boolean column to a real
# Python bool before it reaches psycopg.
_TABLE_RE    = re.compile(r'\b(?:FROM|INTO|UPDATE)\s+(\w+)', re.IGNORECASE)
_EQ_COL_RE   = re.compile(r'(\w+)\s*(?:=|<>|!=)\s*:(p\d+)\b')
_INSERT_RE   = re.compile(r'INSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)',
                          re.IGNORECASE | re.DOTALL)


def _boolean_columns(table_name):
    tbl = metadata.tables.get(table_name)
    if tbl is None:
        return set()
    return {c.name for c in tbl.columns if isinstance(c.type, Boolean)}


def _coerce_boolean_params(sql: str, bound: dict):
    """Returns (possibly-rewritten sql, possibly-rewritten bound). Handles
    both a bound parameter that lines up with a boolean column, and a
    bare `1`/`0` literal written directly into an INSERT's VALUES list
    (e.g. `... is_active) VALUES (?,?,?,1)`) -- the latter needs the
    SQL text itself rewritten to `TRUE`/`FALSE` since there's no bound
    value to coerce."""
    m = _TABLE_RE.search(sql)
    if not m:
        return sql, bound
    bool_cols = _boolean_columns(m.group(1))
    if not bool_cols:
        return sql, bound

    if bound:
        # UPDATE ... SET col=:pN / WHERE col=:pN / SELECT ... WHERE col=:pN
        for col, pname in _EQ_COL_RE.findall(sql):
            if col in bool_cols and pname in bound and bound[pname] is not None:
                bound[pname] = bool(bound[pname])

    # Bare literal comparisons/assignments anywhere else in the SQL text:
    # `WHERE is_active = 1`, `SET must_change_password=0`, etc. -- these
    # are written directly as SQL text throughout routes/*.py (SQLite
    # accepts 1/0 for any column; Postgres's real boolean type does not).
    for col in bool_cols:
        sql = re.sub(rf'\b{re.escape(col)}\s*=\s*1\b', f'{col} = TRUE', sql)
        sql = re.sub(rf'\b{re.escape(col)}\s*=\s*0\b', f'{col} = FALSE', sql)

    # INSERT INTO tbl (col1,col2,...) VALUES (:p0, 1, ...)
    im = _INSERT_RE.search(sql)
    if im:
        cols = [c.strip() for c in im.group(1).split(',')]
        vals = [v.strip() for v in im.group(2).split(',')]
        new_vals = list(vals)
        changed = False
        for i, (col, val) in enumerate(zip(cols, vals)):
            if col not in bool_cols:
                continue
            if val.startswith(':'):
                pname = val[1:]
                if pname in bound and bound[pname] is not None:
                    bound[pname] = bool(bound[pname])
            elif val in ('0', '1'):
                new_vals[i] = 'TRUE' if val == '1' else 'FALSE'
                changed = True
        if changed:
            new_values_clause = ', '.join(new_vals)
            sql = sql[:im.start(2)] + new_values_clause + sql[im.end(2):]

    return sql, bound


def query(sql, params=()):
    new_sql, bound = _qmark_to_named(sql, params)
    new_sql, bound = _coerce_boolean_params(new_sql, bound)
    result = get_db().execute(text(new_sql), bound)
    return [_row_to_dict(r) for r in result.fetchall()]


def one(sql, params=()):
    new_sql, bound = _qmark_to_named(sql, params)
    new_sql, bound = _coerce_boolean_params(new_sql, bound)
    row = get_db().execute(text(new_sql), bound).fetchone()
    return _row_to_dict(row) if row else None


def run(sql, params=()):
    """Execute a write statement inside the request's transaction and
    return the inserted row's id where applicable."""
    new_sql, bound = _qmark_to_named(sql, params)
    new_sql, bound = _coerce_boolean_params(new_sql, bound)
    conn = get_db()
    is_insert = sql.strip().upper().startswith('INSERT')

    if is_insert and not is_sqlite():
        # Postgres: use RETURNING id to get the new row's primary key.
        stripped = new_sql.rstrip().rstrip(';')
        result = conn.execute(text(f'{stripped} RETURNING id'), bound)
        row = result.fetchone()
        return row[0] if row else None

    result = conn.execute(text(new_sql), bound)
    if is_insert:
        return result.lastrowid
    return result.rowcount


# ── Schema creation (explicit, not run automatically at web-worker
#    startup — see audit item 11). Invoke via `flask init-db`. ───────────
def create_schema(app):
    metadata.create_all(app.db_engine, checkfirst=True)
    if is_sqlite(app):
        with app.db_engine.begin() as conn:
            conn.execute(text('PRAGMA journal_mode=WAL'))
            conn.execute(text('PRAGMA foreign_keys=ON'))


# ── ID generators ─────────────────────────────────────────────────────────
def next_loan_id():
    if not is_sqlite():
        # Already inside the request's open transaction (see get_db()).
        # NOTE: conn.execute(sequence) is deprecated in favor of
        # conn.scalar(sequence) -- caught only by testing against a
        # real Postgres instance, which raised a deprecation warning
        # here and would eventually break outright on a future
        # SQLAlchemy version.
        n = get_db().scalar(loan_id_seq)
        return f"AGM{n:04d}"
    # SQLite dev fallback — NOT safe for concurrent writers.
    row = one("SELECT loan_id FROM loans ORDER BY id DESC LIMIT 1")
    if row and row['loan_id']:
        try:
            n = int(row['loan_id'].replace('AGM', '')) + 1
        except ValueError:
            n = 1
    else:
        n = 1
    return f"AGM{n:04d}"


def next_payment_id():
    if not is_sqlite():
        n = get_db().scalar(payment_id_seq)
        return f"AGR-PAY-{n:04d}"
    row = one("SELECT payment_id FROM payments ORDER BY id DESC LIMIT 1")
    if row and row['payment_id']:
        try:
            n = int(row['payment_id'].split('-')[-1]) + 1
        except ValueError:
            n = 1
    else:
        n = 1
    return f"AGR-PAY-{n:04d}"


# ── Date helpers (unchanged) ────────────────────────────────────────────
def fmt_date(val, fmt='%d %b %Y'):
    if not val:
        return ''
    if isinstance(val, datetime):
        return val.strftime(fmt)
    for f in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(val), f).strftime(fmt)
        except ValueError:
            pass
    return str(val)


def to_dt(val):
    if val is None or isinstance(val, datetime):
        return val
    for f in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(val), f)
        except ValueError:
            pass
    return val
