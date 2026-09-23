# Agaram Finance — Stage 2: Finance Engine

Builds on Stage 1 (see `MIGRATION_NOTES.md`). This stage pulls the
loan/payment/settlement math out of `routes/*.py` into `services/`,
fixes the formula and rounding inconsistencies, kills the top-up
dead-code bug, and adds the `loan_transactions` ledger — audit items
8, 9, 10, 19, 22, 23, 24, 25, 49.

## New: `services/`

- **`financial.py`** — the one place interest-rate, monthly-due, and
  the principal/interest payment split are computed. Previously
  `routes/loans.py`'s save path and its own `/calculate` AJAX preview
  used two different formulas (one based on `loan_amount`, one on
  `principle`; one rounding with `ceil()`, one with `round()`) — the
  live preview a staff member saw while filling the form did not
  necessarily match what got saved. Both paths now call the same
  functions, on `principle` (money actually disbursed after the
  document charge), rounding EMIs **up** to the nearest rupee so the
  company is never short a few paise on the last installment.
  `tests/test_financial.py` proves the rate→amount and amount→rate
  directions are true inverses of each other.
- **`loan_service.py`** — `create_loan`, `update_loan`, `topup_loan`.
  - **Top-up dead-code bug fixed**: the old code computed
    `new_balance` once with a convoluted expression, then immediately
    overwrote that variable with a second, different calculation
    before the first was ever used. There's one calculation now.
  - **Server-controlled financial fields (audit 19B)**: `loan_amount`
    / `document_charge` / `interest_amount` / `tenure` always drive a
    fresh server-side recompute of principal/rate/agreement/due — a
    tampered request can't just POST a different `agreement_value`
    and have it saved. `paid_due` / `paid_amount` / `feature_dues` /
    `balance_agreement` can only be directly overridden by an
    **admin** (a data-correction escape hatch); a non-admin's
    submission of those fields is silently ignored and the loan's
    existing values are kept. Verified in this environment: a staff
    login POSTing `balance_agreement=0` and `paid_amount=999999` via
    the edit form left both fields unchanged.
- **`payment_service.py`** — `collect_payment` (EMI/Advance/Penalty),
  same behavior as before, now testable without Flask.
- **`settlement_service.py`** — `calc_settlement` / `collect_settlement`,
  relocated with the formula untouched (it was already well isolated).
  `tests/test_settlement.py` covers the scenarios the audit asked for:
  0 months paid, 1 month paid, advance payment, overdue payment, a
  fully paid loan, a loan past its tenure end date, and settlement on
  the tenure end date.
- **`ledger.py`** — `record(loan_id, txn_type, amount, note, by)`
  writes to the new `loan_transactions` table. Every loan-affecting
  event now leaves an append-only row: `ORIGINAL` on create, `TOPUP`
  on top-up, `EMI`/`PENALTY` on payment collection, `SETTLEMENT` on
  settlement. This is the auditable "why does this loan's balance say
  what it says" trail the audit called the single most valuable
  change — verified end-to-end in this environment (create → topup →
  EMI collect produced exactly `ORIGINAL, TOPUP, EMI` rows with the
  right amounts).

## `routes/loans.py`, `routes/payments.py`, `routes/settlement.py`

Rewritten to be thin: parse the request, call the matching service
function, flash the result, redirect. No financial math or direct
multi-field INSERT/UPDATE lives in routes anymore. Route→Service→
Database, as the audit asked for.

`routes/loans.py`'s `/calculate` AJAX endpoint (the live preview while
filling the create form) now calls the exact same
`services/financial.py` function the actual save uses, so the number
on screen can never again disagree with what gets persisted.

## `database.py`

Added the `loan_transactions` table (id, loan_id, txn_type, amount,
note, created_by, created_at).

## Tested

Ran a full request-level smoke test in this environment against
SQLite: login → create loan (₹25,000 + ₹5,000 top-up) → collect a
₹3,000 EMI → settlement calculation → verified `loan_transactions`
has the right `ORIGINAL`/`TOPUP`/`EMI` rows and the loan's
`balance_agreement` matches by hand (29,300 + 5,000 − 3,000 = 31,300).
Also verified the server-controlled-fields protection: a staff-role
edit attempting to zero out `balance_agreement` and inflate
`paid_amount` was silently rejected. `tests/test_financial.py` (7
tests) and `tests/test_settlement.py` (8 tests) both pass:

```
python -m unittest tests.test_financial tests.test_settlement -v
```

PostgreSQL-specific behavior (Decimal columns flowing through the new
`NUMERIC` fields under real psycopg) is unchanged from Stage 1's
caveat — still worth a smoke test against your actual Postgres
instance before trusting it with real money.

## What's NOT done yet

- CSRF still installed but not enabled (Stage 3, together with the 13
  templates that need `{{ csrf_token() }}`).
- No audit-log writes yet (`audit_logs` table exists, unused) — that's
  Stage 3 too.
- `routes/backup.py` restore flow, Excel import validation, and the
  `static/js/main.js` XSS (`innerHTML`) issues are all still
  unchanged.
- `routes/loans.py`'s `paid_due`/`feature_dues`/`balance_agreement`
  admin-override path is a pragmatic compromise, not a full fix: the
  audit's stricter reading (item 19B) is that those fields shouldn't
  be directly editable *at all*, only ever changed by payment/topup/
  settlement events. If you want that, Stage 3 or 4 should also strip
  those inputs from `templates/loans/edit.html` entirely rather than
  just gating them server-side.

## Suggested next step

**Stage 3 — Security**: CSRF across all 13 forms, audit-log writes
from the service layer you now have, login rate limiting/lockout,
XSS fixes in `static/js/main.js`, security headers, Aadhaar masking.
