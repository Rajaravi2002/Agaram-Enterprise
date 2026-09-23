"""
services/settlement_service.py – Settlement calculation and
collection, extracted from routes/settlement.py (audit item 22).

Formula is unchanged from the original spec (it was already isolated
and well documented) -- it's just relocated here so it can be
imported and tested without spinning up Flask. See
tests/test_settlement.py for the scenarios the audit asked for:
0 months paid, 1 month paid, advance payment, overdue payment, fully
paid loan, expired tenure, settlement on/after the due date.

    completed_months  = min(months_between(agreement_date, today), tenure)
    future_dues       = tenure - completed_months
    advance_dues      = max(0, paid_months - completed_months)
    future_due_count  = future_dues - advance_dues
    principal_per_month = loan_amount / tenure
    future_principal  = future_due_count * principal_per_month
    overdue_count     = max(0, completed_months - paid_months)
    total_overdue     = overdue_count * emi
    fc_charges        = future_principal * 0.05
    settlement_amount = future_principal + total_overdue + fc_charges
"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from database import one, run, fmt_date, to_dt, next_payment_id
from services.ledger import record as record_txn
from services import audit_log


class SettlementServiceError(Exception):
    pass


def months_between(d1, d2) -> int:
    """Number of full months from d1 to d2."""
    if d1 is None or d2 is None:
        return 0
    if not isinstance(d1, (date, datetime)):
        d1 = to_dt(d1)
    if not isinstance(d2, (date, datetime)):
        d2 = to_dt(d2)
    if d1 is None or d2 is None:
        return 0
    if isinstance(d1, datetime):
        d1 = d1.date()
    if isinstance(d2, datetime):
        d2 = d2.date()
    delta = relativedelta(d2, d1)
    return delta.years * 12 + delta.months


def calc_settlement(loan: dict, as_of_date=None) -> dict:
    if as_of_date is None:
        as_of_date = date.today()
    if isinstance(as_of_date, str):
        try:
            as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()
        except Exception:
            as_of_date = date.today()

    tenure         = int(loan['tenure'] or 0)
    loan_amount    = float(loan['loan_amount'] or 0)
    paid_months    = int(loan['paid_due'] or 0)
    emi            = float(loan['due_amount'] or 0)
    agreement_date = to_dt(loan.get('loan_date'))
    if agreement_date and isinstance(agreement_date, datetime):
        agreement_date = agreement_date.date()

    expiry_date = agreement_date + relativedelta(months=tenure) if agreement_date else None

    completed_months    = min(months_between(agreement_date, as_of_date), tenure) if agreement_date else 0
    future_dues         = max(tenure - completed_months, 0)
    advance_dues        = max(0, paid_months - completed_months)
    future_due_count    = max(future_dues - advance_dues, 0)
    principal_per_month = round(loan_amount / tenure, 2) if tenure else 0
    future_principal    = round(future_due_count * principal_per_month)
    overdue_count        = max(0, completed_months - paid_months)
    total_overdue        = round(overdue_count * emi)
    fc_charges           = round(future_principal * 0.05)
    settlement_amount    = round(future_principal + total_overdue + fc_charges)

    interest_per_month = round(float(loan.get('interest_amount') or 0) / tenure, 2) if tenure else 0
    balance_due        = round(float(loan.get('balance_agreement') or 0), 2)
    future_total_dues  = round(future_due_count * emi, 2)

    return {
        'loan_id': loan['loan_id'],
        'customer_name': loan['customer_name'],
        'agreement_date': fmt_date(loan.get('loan_date')),
        'expiry_date': expiry_date.strftime('%d %b %Y') if expiry_date else '-',
        'as_of_date': as_of_date.strftime('%d %b %Y'),
        'loan_amount': loan_amount,
        'tenure': tenure,
        'due_amount': emi,
        'interest_amount': float(loan.get('interest_amount') or 0),
        'paid_months': paid_months,
        'principal_per_month': principal_per_month,
        'interest_per_month': interest_per_month,
        'completed_months': completed_months,
        'advance_dues': advance_dues,
        'future_dues': future_dues,
        'future_due_count': future_due_count,
        'future_principal': future_principal,
        'overdue_count': overdue_count,
        'total_overdue': total_overdue,
        'fc_charges': fc_charges,
        'settlement_amount': settlement_amount,
        'balance_due': balance_due,
        'future_total_dues': future_total_dues,
    }


def collect_settlement(form, collected_by: str) -> str:
    loan_id         = (form.get('loan_id') or '').strip()
    settlement_amt  = float(form.get('settlement_amount') or 0)
    collected_amt   = float(form.get('collected_amount') or 0)
    collection_date = form.get('collection_date') or date.today().isoformat()
    payment_mode    = form.get('payment_mode', 'Cash')
    remarks         = (form.get('remarks') or '').strip()

    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        raise SettlementServiceError('Loan not found.')
    if loan['loan_status'] == 'closed':
        raise SettlementServiceError('This loan is already closed.')

    payment_id = next_payment_id()
    now_iso = datetime.now().isoformat(timespec='seconds')

    run("""INSERT INTO payments
           (payment_id, loan_id, customer_name, collection_date, payment_type, payment_mode,
            settlement_amount, paid_amount, outstanding_balance,
            collection_remarks, collected_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (payment_id, loan_id, loan['customer_name'], collection_date, 'Settlement', payment_mode,
         settlement_amt, collected_amt, 0,
         remarks, collected_by, now_iso))

    run("""UPDATE loans SET
           loan_status='closed',
           balance_agreement=0,
           closed_at=?,
           remarks=remarks || ?
           WHERE loan_id=?""",
        (now_iso,
         f"\n[Settlement Completed on {collection_date}: Collected Rs.{collected_amt:,.2f}]",
         loan_id))

    record_txn(loan_id, 'SETTLEMENT', collected_amt, note=remarks, by=collected_by)

    audit_log.record('SETTLEMENT_COLLECTED', entity_type='loan', entity_id=loan_id,
                      new_value=f'settlement={settlement_amt}, collected={collected_amt}')
    audit_log.record('LOAN_CLOSED', entity_type='loan', entity_id=loan_id, new_value='settled')

    return payment_id
