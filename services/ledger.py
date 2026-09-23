"""
services/ledger.py – Append-only financial transaction ledger for a
loan (audit items 23 & 49). Every loan-affecting event -- the original
loan, a top-up, an EMI/advance payment, a penalty, a settlement --
gets one row here, in addition to whatever it already does to the
`loans`/`payments` tables.

This does not replace those tables (that would be a bigger, riskier
rewrite than Stage 2 should attempt at once) -- it gives you the
auditable "why does this loan's balance say what it says" trail that
the production audit called out as the single most valuable change
for a finance company:

    2026-01-01  ORIGINAL     +50,000
    2026-02-01  EMI          -5,000
    2026-06-01  TOPUP        +10,000
    2026-08-01  SETTLEMENT   -25,000
"""
from datetime import datetime

from database import run

VALID_TYPES = {'ORIGINAL', 'EMI', 'TOPUP', 'PENALTY', 'SETTLEMENT'}


def record(loan_id: str, txn_type: str, amount: float, note: str = '', by: str = '') -> None:
    if txn_type not in VALID_TYPES:
        raise ValueError(f'Unknown loan_transactions type: {txn_type}')
    run("""INSERT INTO loan_transactions
           (loan_id, txn_type, amount, note, created_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        (loan_id, txn_type, round(float(amount), 2), note or '', by or '',
         datetime.now().isoformat(timespec='seconds')))
