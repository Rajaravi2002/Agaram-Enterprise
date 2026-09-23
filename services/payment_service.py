"""
services/payment_service.py – EMI / Advance / Penalty collection
logic, extracted from routes/payments.py (audit items 24 & 25).
"""
from datetime import date, datetime

from database import one, run, next_payment_id
from services.financial import split_principal_interest
from services.ledger import record as record_txn
from services import audit_log


class PaymentServiceError(Exception):
    pass


def carry_forward(loan_id: str) -> float:
    row = one("SELECT pending_amount FROM payments WHERE loan_id=? ORDER BY collection_date DESC LIMIT 1", (loan_id,))
    return float(row['pending_amount']) if row else 0.0


def month_number(loan_id: str) -> int:
    return one("SELECT COUNT(*) c FROM payments WHERE loan_id=?", (loan_id,))['c'] + 1


def collect_payment(form, collected_by: str) -> dict:
    """Validate and record an EMI / Advance / Penalty payment. Returns
    dict(payment_id, closed, message)."""
    loan_id = (form.get('loan_id') or '').strip()
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        raise PaymentServiceError('Loan not found.')
    if loan['loan_status'] == 'closed':
        raise PaymentServiceError('This loan is already closed.')

    payment_type = form.get('payment_type', 'EMI')
    if payment_type not in ('EMI', 'Advance', 'Penalty'):
        payment_type = 'EMI'

    paid_amount = float(form.get('paid_amount') or 0)
    if paid_amount < 0:
        raise PaymentServiceError('Payment amount cannot be negative.')

    penalty_amount  = float(form.get('penalty_amount') or 0)
    payment_mode    = form.get('payment_mode', 'Cash')
    collection_date = form.get('collection_date', '') or date.today().isoformat()
    remarks         = (form.get('collection_remarks') or '').strip()
    payment_id      = next_payment_id()
    now_iso         = datetime.now().isoformat(timespec='seconds')

    if payment_type == 'Penalty':
        # Standalone penalty collection: does not touch principal,
        # interest, or balance. Clears whatever penalty was assessed.
        new_balance = loan['balance_agreement']
        carry       = carry_forward(loan_id)
        mo          = month_number(loan_id)

        run("""INSERT INTO payments
               (payment_id,loan_id,customer_name,collection_date,payment_type,payment_mode,
                emi_amount,carry_forward,total_due,paid_amount,pending_amount,outstanding_balance,
                principal_component,interest_component,
                month_number,penalty_amount,collection_remarks,collected_by,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (payment_id, loan_id, loan['customer_name'], collection_date, 'Penalty', payment_mode,
             0, carry, paid_amount, paid_amount, 0.0, new_balance,
             0.0, 0.0, mo, paid_amount, remarks,
             collected_by, now_iso))

        run("UPDATE loans SET penalty_amount=0 WHERE loan_id=?", (loan_id,))
        record_txn(loan_id, 'PENALTY', paid_amount, note=remarks, by=collected_by)
        audit_log.record('PAYMENT_COLLECTED', entity_type='payment', entity_id=payment_id,
                          new_value=f'type=Penalty, amount={paid_amount}, loan={loan_id}')

        return dict(payment_id=payment_id, closed=False,
                    message=f'Penalty payment of Rs.{paid_amount:,.2f} recorded.')

    # ── EMI or Advance ───────────────────────────────────────────────
    carry       = carry_forward(loan_id)
    emi_amount  = float(loan['due_amount'])
    total_due   = round(emi_amount + carry + penalty_amount, 2)
    pending     = round(max(total_due - paid_amount, 0), 2)
    mo          = month_number(loan_id)
    new_balance = round(float(loan['balance_agreement']) - paid_amount, 2)
    principal_part, interest_part = split_principal_interest(
        loan['agreement_value'], loan['principle_amount'], paid_amount)

    run("""INSERT INTO payments
           (payment_id,loan_id,customer_name,collection_date,payment_type,payment_mode,
            emi_amount,carry_forward,total_due,paid_amount,pending_amount,outstanding_balance,
            principal_component,interest_component,
            month_number,penalty_amount,collection_remarks,collected_by,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (payment_id, loan_id, loan['customer_name'], collection_date, payment_type, payment_mode,
         emi_amount, carry, total_due, paid_amount, pending, new_balance,
         principal_part, interest_part, mo, penalty_amount, remarks,
         collected_by, now_iso))

    run("""UPDATE loans SET paid_due=?,paid_amount=?,feature_dues=?,balance_agreement=?
           WHERE loan_id=?""",
        (loan['paid_due'] + 1,
         float(loan['paid_amount']) + paid_amount,
         max(loan['feature_dues'] - 1, 0),
         new_balance, loan_id))

    record_txn(loan_id, 'EMI', paid_amount, note=f'{payment_type} payment', by=collected_by)
    audit_log.record('PAYMENT_COLLECTED', entity_type='payment', entity_id=payment_id,
                      new_value=f'type={payment_type}, amount={paid_amount}, loan={loan_id}')

    closed = new_balance <= 0
    if closed:
        run("UPDATE loans SET loan_status='closed', closed_at=? WHERE loan_id=?",
            (now_iso, loan_id))
        audit_log.record('LOAN_CLOSED', entity_type='loan', entity_id=loan_id,
                          new_value='fully paid via EMI')
        message = f'Payment recorded. Loan {loan_id} FULLY PAID and closed!'
    else:
        message = f'{payment_type} payment of Rs.{paid_amount:,.2f} recorded.'
        if pending > 0:
            message += f' Pending Rs.{pending:,.2f} carries forward.'

    return dict(payment_id=payment_id, closed=closed, message=message)
