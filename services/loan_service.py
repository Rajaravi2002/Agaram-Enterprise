"""
services/loan_service.py – Loan creation, editing, and top-up business
logic, extracted out of routes/loans.py (audit items 8 & 19).

routes/loans.py should call these functions and flash whatever message
they produce; it should not compute principal/interest/agreement/due
itself, or write loans/customers rows directly, anymore.

Server-controlled financial fields (audit item 19B): a browser can
still submit `paid_due`, `paid_amount`, `feature_dues`, and
`balance_agreement` on the edit form (removing those fields from the
template is Stage 3 work), but this layer only honours them when the
editor is an admin -- a data-correction escape hatch, not something a
staff user's tampered request can use to zero out a balance. Everyone
else's submission of those fields is ignored and the loan's existing
values are kept. `loan_amount` / `document_charge` / `interest_amount`
/ `tenure` always drive a fresh, server-side recompute of
principal/rate/agreement/due -- never taken from the browser directly.
"""
import json
from datetime import date, datetime

from database import one, run, next_loan_id
from services.financial import compute_loan_fields, compute_loan_fields_from_rate
from services.ledger import record as record_txn
from services import audit_log


class LoanServiceError(Exception):
    pass


def _guarantor_fields(form):
    enabled = 1 if form.get('guarantor_enabled') else 0
    name    = (form.get('guarantor_name') or '').strip()    if enabled else ''
    phone   = (form.get('guarantor_phone') or '').strip()   if enabled else ''
    address = (form.get('guarantor_address') or '').strip() if enabled else ''
    return enabled, name, phone, address


def create_loan(form, created_by: str) -> str:
    """Create a new loan from the raw create-loan form. Returns the new
    loan_id. Raises LoanServiceError on a duplicate manual loan ID."""
    customer_name = form['customer_name'].strip()

    manual_id = (form.get('manual_loan_id') or '').strip().upper()
    if manual_id:
        if not manual_id.startswith('AGM'):
            manual_id = f'AGM{manual_id.zfill(4)}'
        existing = one("SELECT loan_id, customer_name FROM loans WHERE loan_id=?", (manual_id,))
        if existing:
            raise LoanServiceError(
                f'Loan ID {manual_id} already exists for {existing["customer_name"]}. '
                f'Please choose a different loan number or leave it blank for auto-generation.')
        loan_id = manual_id
    else:
        loan_id = next_loan_id()

    if not one("SELECT id FROM customers WHERE name=?", (customer_name,)):
        run("""INSERT INTO customers
               (name,phone,alt_phone,address,aadhaar,occupation,date_added,added_by,is_active)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (customer_name, (form.get('phone') or '').strip(),
             (form.get('alt_phone') or '').strip(), '', '', '',
             datetime.now().isoformat(timespec='seconds'), created_by))

    f = compute_loan_fields(
        loan_amount=float(form.get('loan_amount') or 0),
        document_charge=float(form.get('document_charge') or 0),
        interest_amount=float(form.get('interest_amount') or 0),
        tenure_months=int(form.get('tenure') or 1),
    )
    g_enabled, g_name, g_phone, g_address = _guarantor_fields(form)

    paid_due     = int(form.get('paid_due') or 0)
    paid_amount  = float(form.get('paid_amount') or 0)
    feature_dues = max(f['tenure'] - paid_due, 0) if paid_due else int(form.get('feature_dues') or f['tenure'])
    balance      = float(form.get('balance_agreement') or f['agreement_value'])

    run("""INSERT INTO loans
           (loan_id,customer_name,phone,ref,follower,loan_date,due_day,
            loan_amount,document_charge,principle_amount,interest_rate,interest_amount,agreement_value,
            tenure,due_amount,paid_due,paid_amount,feature_dues,balance_agreement,int_pct,
            vehicle_model,vehicle_number,document_status,remarks,
            penalty_amount,penalty_description,topup_history,
            father_name,address1,address2,address3,pincode,vehicle_cost,
            guarantor_enabled,guarantor_name,guarantor_phone,guarantor_address,
            loan_status,created_at,created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (loan_id, customer_name,
         (form.get('phone') or '').strip(),
         (form.get('ref') or '').strip(),
         (form.get('follower') or '').strip(),
         form.get('loan_date', ''),
         (form.get('due_day') or '').strip(),
         f['loan_amount'], f['document_charge'], f['principle_amount'],
         f['interest_rate'], f['interest_amount'], f['agreement_value'],
         f['tenure'], f['due_amount'],
         paid_due, paid_amount, feature_dues, balance,
         f['int_pct'],
         (form.get('vehicle_model') or '').strip(),
         (form.get('vehicle_number') or '').strip(),
         (form.get('document_status') or '').strip(),
         (form.get('remarks') or '').strip(),
         float(form.get('penalty_amount') or 0),
         (form.get('penalty_description') or '').strip(),
         '[]',
         (form.get('father_name') or '').strip(),
         (form.get('address1') or '').strip(),
         (form.get('address2') or '').strip(),
         (form.get('address3') or '').strip(),
         (form.get('pincode') or '').strip(),
         float(form.get('vehicle_cost') or 0),
         g_enabled, g_name, g_phone, g_address,
         'active',
         datetime.now().isoformat(timespec='seconds'),
         created_by))

    record_txn(loan_id, 'ORIGINAL', f['agreement_value'],
               note=f'Loan created: principal Rs.{f["principle_amount"]:,.2f}', by=created_by)

    audit_log.record('LOAN_CREATED', entity_type='loan', entity_id=loan_id,
                      new_value=f'agreement={f["agreement_value"]}, tenure={f["tenure"]}')

    return loan_id


def update_loan(loan_id: str, form, is_admin: bool) -> None:
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        raise LoanServiceError('Loan not found.')

    f = compute_loan_fields(
        loan_amount=float(form.get('loan_amount') or 0),
        document_charge=float(form.get('document_charge') or 0),
        interest_amount=float(form.get('interest_amount') or 0),
        tenure_months=int(form.get('tenure') or 1),
    )
    g_enabled, g_name, g_phone, g_address = _guarantor_fields(form)

    if is_admin:
        paid_due     = int(form.get('paid_due') or loan['paid_due'])
        paid_amount  = float(form.get('paid_amount') or loan['paid_amount'])
        feature_dues = int(form.get('feature_dues') or loan['feature_dues'])
        balance      = float(form.get('balance_agreement') or loan['balance_agreement'])
    else:
        paid_due, paid_amount = loan['paid_due'], loan['paid_amount']
        feature_dues, balance = loan['feature_dues'], loan['balance_agreement']

    run("""UPDATE loans SET
           customer_name=?,phone=?,ref=?,follower=?,loan_date=?,due_day=?,
           loan_amount=?,document_charge=?,principle_amount=?,interest_rate=?,
           interest_amount=?,agreement_value=?,
           tenure=?,due_amount=?,paid_due=?,paid_amount=?,feature_dues=?,balance_agreement=?,int_pct=?,
           vehicle_model=?,vehicle_number=?,document_status=?,remarks=?,
           penalty_amount=?,penalty_description=?,
           father_name=?, vehicle_cost=?, address1=?, address2=?, address3=?, pincode=?,
           guarantor_enabled=?, guarantor_name=?, guarantor_phone=?, guarantor_address=?
           WHERE loan_id=?""",
        ((form.get('customer_name') or '').strip(),
         (form.get('phone') or '').strip(),
         (form.get('ref') or '').strip(),
         (form.get('follower') or '').strip(),
         form.get('loan_date', ''),
         (form.get('due_day') or '').strip(),
         f['loan_amount'], f['document_charge'], f['principle_amount'],
         f['interest_rate'], f['interest_amount'], f['agreement_value'],
         f['tenure'], f['due_amount'],
         paid_due, paid_amount, feature_dues, balance,
         f['int_pct'],
         (form.get('vehicle_model') or '').strip(),
         (form.get('vehicle_number') or '').strip(),
         (form.get('document_status') or '').strip(),
         (form.get('remarks') or '').strip(),
         float(form.get('penalty_amount') or 0),
         (form.get('penalty_description') or '').strip(),
         (form.get('father_name') or '').strip(),
         float(form.get('vehicle_cost') or 0),
         (form.get('address1') or '').strip(),
         (form.get('address2') or '').strip(),
         (form.get('address3') or '').strip(),
         (form.get('pincode') or '').strip(),
         g_enabled, g_name, g_phone, g_address,
         loan_id))

    audit_log.record('LOAN_EDITED', entity_type='loan', entity_id=loan_id,
                      old_value=f'agreement={loan["agreement_value"]}',
                      new_value=f'agreement={f["agreement_value"]}')


def topup_loan(loan_id: str, form, by: str) -> dict:
    """Add a top-up to an existing loan. Returns the computed fields
    for flashing a message.

    Fixes a real bug from the old routes/loans.py: it computed
    `new_balance` once using a convoluted expression, then immediately
    overwrote that variable with a second, different calculation
    before it was ever used -- the first calculation was dead code
    that had no effect. There's only one calculation now.
    """
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        raise LoanServiceError('Loan not found.')
    if loan['loan_status'] == 'closed':
        raise LoanServiceError('Cannot top-up a closed loan.')

    topup_amount = float(form.get('topup_amount') or 0)
    topup_doc    = float(form.get('topup_doc_charge') or 0)
    new_tenure   = int(form.get('new_tenure') or loan['tenure'])
    note         = (form.get('note') or '').strip()
    topup_date   = form.get('topup_date') or date.today().isoformat()

    if topup_amount <= 0:
        raise LoanServiceError('Top-up amount must be greater than zero.')

    new_loan_amt = float(loan['loan_amount']) + topup_amount
    new_doc      = float(loan['document_charge']) + topup_doc

    # Same interest RATE as before, re-derived on the new principal x new
    # tenure via the one shared formula (services/financial.py) -- not
    # duplicated math, and consistent no matter how many top-ups a loan
    # has already had.
    f = compute_loan_fields_from_rate(
        loan_amount=new_loan_amt,
        document_charge=new_doc,
        rate_pct=float(loan['interest_rate'] or 0),
        tenure_months=new_tenure,
    )

    new_balance = round(float(loan['balance_agreement']) + topup_amount - topup_doc, 2)

    history = json.loads(loan.get('topup_history') or '[]')
    history.append({
        'date': topup_date,
        'added_amount': topup_amount,
        'doc_charge': topup_doc,
        'new_loan_total': new_loan_amt,
        'new_agreement': f['agreement_value'],
        'new_tenure': new_tenure,
        'new_due': f['due_amount'],
        'note': note,
        'by': by,
    })

    run("""UPDATE loans SET
           loan_amount=?, document_charge=?, principle_amount=?,
           interest_amount=?, interest_rate=?, agreement_value=?,
           tenure=?, due_amount=?, feature_dues=?, balance_agreement=?,
           topup_history=?, remarks=?
           WHERE loan_id=?""",
        (new_loan_amt, new_doc, f['principle_amount'],
         f['interest_amount'], f['interest_rate'], f['agreement_value'],
         new_tenure, f['due_amount'],
         max(new_tenure - loan['paid_due'], 0),
         new_balance,
         json.dumps(history),
         (loan['remarks'] + f'\n[Top-up {topup_date}: +Rs.{topup_amount:,.0f}]').strip(),
         loan_id))

    record_txn(loan_id, 'TOPUP', topup_amount, note=note, by=by)

    audit_log.record('LOAN_TOPUP', entity_type='loan', entity_id=loan_id,
                      old_value=f'loan_amount={loan["loan_amount"]}',
                      new_value=f'loan_amount={new_loan_amt}, topup={topup_amount}')

    return dict(new_loan_amount=new_loan_amt, new_due=f['due_amount'], topup_amount=topup_amount)
