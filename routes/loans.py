from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from database import one, query, run, fmt_date, to_dt
from services import loan_service
from services.financial import compute_loan_fields_from_rate
from routes.backup import auto_sync_excel
import json

loans_bp = Blueprint('loans', __name__, url_prefix='/loans')

# ── helpers ───────────────────────────────────────────────────────────────────

def _is_overdue(loan):
    if loan['loan_status'] == 'closed':
        return False
    if not loan.get('loan_date') or not loan.get('tenure'):
        return False
    try:
        from dateutil.relativedelta import relativedelta
        end_date = to_dt(loan['loan_date']) + relativedelta(months=int(loan['tenure']))
        return date.today() > end_date.date()
    except Exception:
        return False


# ── list ──────────────────────────────────────────────────────────────────────

@loans_bp.route('/')
@login_required
def index():
    status = request.args.get('status', '')
    search = request.args.get('search', '').strip()
    sql, params = "SELECT * FROM loans WHERE 1=1", []
    if status:
        sql += " AND loan_status=?"; params.append(status)
    if search:
        like = f'%{search}%'
        sql += " AND (loan_id LIKE ? OR customer_name LIKE ? OR vehicle_number LIKE ?)"
        params += [like, like, like]
    sql += " ORDER BY id DESC"
    loans = query(sql, params)
    for l in loans:
        l['loan_date'] = fmt_date(l.get('loan_date'))
    return render_template('loans/index.html', loans=loans, status_filter=status, search=search)


# ── create ────────────────────────────────────────────────────────────────────

@loans_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    customers = query("SELECT name, phone, alt_phone FROM customers WHERE is_active=1 ORDER BY name")
    if request.method == 'POST':
        customer_name = request.form['customer_name'].strip()
        try:
            loan_id = loan_service.create_loan(request.form, current_user.username)
        except loan_service.LoanServiceError as e:
            flash(str(e), 'danger')
            return render_template('loans/create.html', customers=customers,
                                   form_data=request.form,
                                   today=date.today().isoformat(),
                                   prefill_name=customer_name, prefill_loan=None)
        auto_sync_excel()
        flash(f'Loan {loan_id} created for {customer_name}!', 'success')
        return redirect(url_for('loans.view', loan_id=loan_id))
    # Pre-fill customer_name if passed via querystring
    prefill_name = request.args.get('customer_name', '')
    prefill_loan = None
    if prefill_name:
        prefill_loan = one("SELECT * FROM loans WHERE customer_name=? AND loan_status IN ('active','overdue') ORDER BY id DESC LIMIT 1",
                           (prefill_name,))
    return render_template('loans/create.html', customers=customers, form_data={},
                           today=date.today().isoformat(),
                           prefill_name=prefill_name, prefill_loan=prefill_loan)


# ── top-up (merge into existing loan) ─────────────────────────────────────────

@loans_bp.route('/<loan_id>/topup', methods=['GET', 'POST'])
@login_required
def topup(loan_id):
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        flash('Loan not found.', 'danger')
        return redirect(url_for('loans.index'))
    if loan['loan_status'] == 'closed':
        flash('Cannot top-up a closed loan.', 'warning')
        return redirect(url_for('loans.view', loan_id=loan_id))

    if request.method == 'POST':
        try:
            result = loan_service.topup_loan(loan_id, request.form, current_user.username)
        except loan_service.LoanServiceError as e:
            flash(str(e), 'warning')
            return redirect(url_for('loans.topup', loan_id=loan_id))
        auto_sync_excel()
        flash(f'Top-up of Rs.{result["topup_amount"]:,.2f} added to {loan_id}. '
              f'New loan total: Rs.{result["new_loan_amount"]:,.2f}.', 'success')
        return redirect(url_for('loans.view', loan_id=loan_id))

    return render_template('loans/topup.html', loan=loan, today=date.today().isoformat())


# ── view ──────────────────────────────────────────────────────────────────────

@loans_bp.route('/<loan_id>')
@login_required
def view(loan_id):
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        flash('Loan not found.', 'danger')
        return redirect(url_for('loans.index'))
    overdue = _is_overdue(loan)
    if overdue and loan['loan_status'] == 'active':
        run("UPDATE loans SET loan_status='overdue' WHERE loan_id=?", (loan_id,))
        loan['loan_status'] = 'overdue'
    payments = query("SELECT * FROM payments WHERE loan_id=? ORDER BY collection_date", (loan_id,))
    for p in payments:
        p['collection_date'] = fmt_date(p.get('collection_date'))
    loan['loan_date'] = fmt_date(loan.get('loan_date'))
    topup_history = json.loads(loan.get('topup_history') or '[]')
    other_loans = query(
        "SELECT * FROM loans WHERE customer_name=? AND loan_id!=? ORDER BY id DESC",
        (loan['customer_name'], loan_id))
    return render_template('loans/view.html', loan=loan, payments=payments,
                           overdue=overdue, topup_history=topup_history,
                           other_loans=other_loans)


# ── edit ──────────────────────────────────────────────────────────────────────

@loans_bp.route('/<loan_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(loan_id):
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        flash('Loan not found.', 'danger')
        return redirect(url_for('loans.index'))
    if request.method == 'POST':
        try:
            loan_service.update_loan(loan_id, request.form, current_user.is_admin)
        except loan_service.LoanServiceError as e:
            flash(str(e), 'danger')
            return redirect(url_for('loans.edit', loan_id=loan_id))
        auto_sync_excel()
        flash('Loan updated successfully.', 'success')
        return redirect(url_for('loans.view', loan_id=loan_id))
    loan['loan_date'] = loan['loan_date'][:10] if loan.get('loan_date') else ''
    return render_template('loans/edit.html', loan=loan)


# ── penalty ───────────────────────────────────────────────────────────────────

@loans_bp.route('/<loan_id>/penalty', methods=['GET', 'POST'])
@login_required
def penalty(loan_id):
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        flash('Loan not found.', 'danger')
        return redirect(url_for('loans.index'))
    if request.method == 'POST':
        run("UPDATE loans SET penalty_amount=?, penalty_description=? WHERE loan_id=?",
            (float(request.form.get('penalty_amount') or 0),
             request.form.get('penalty_description','').strip(), loan_id))
        flash('Penalty updated.', 'success')
        return redirect(url_for('loans.view', loan_id=loan_id))
    return render_template('loans/penalty.html', loan=loan)


# ── close / overdue ───────────────────────────────────────────────────────────

@loans_bp.route('/<loan_id>/close', methods=['POST'])
@login_required
def close(loan_id):
    if not current_user.is_admin:
        flash('Only admin can close loans.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan_id))
    run("UPDATE loans SET loan_status='closed', closed_at=? WHERE loan_id=?",
        (datetime.now().isoformat(timespec='seconds'), loan_id))
    flash(f'Loan {loan_id} closed.', 'success')
    return redirect(url_for('loans.view', loan_id=loan_id))


@loans_bp.route('/<loan_id>/mark-overdue', methods=['POST'])
@login_required
def mark_overdue(loan_id):
    if not current_user.is_admin:
        flash('Only admin can mark loans as overdue.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan_id))
    run("UPDATE loans SET loan_status='overdue' WHERE loan_id=?", (loan_id,))
    flash(f'Loan {loan_id} marked as overdue.', 'warning')
    return redirect(url_for('loans.view', loan_id=loan_id))


# ── AJAX: calculate ───────────────────────────────────────────────────────────

@loans_bp.route('/calculate', methods=['POST'])
@login_required
def calculate():
    """Live preview while filling the create/edit form. Uses the exact
    same formula module (services/financial.py) as the actual save, so
    this preview can never disagree with what gets persisted."""
    d = request.get_json()
    f = compute_loan_fields_from_rate(
        loan_amount=float(d.get('loan_amount', 0)),
        document_charge=float(d.get('document_charge', 0)),
        rate_pct=float(d.get('interest_rate', 0)),
        tenure_months=int(d.get('tenure', 1)),
    )
    return jsonify({
        'principle':    f['principle_amount'],
        'interest_amt': f['interest_amount'],
        'agreement':    f['agreement_value'],
        'due_amount':   f['due_amount'],
    })


# ── AJAX: customer loan summary ───────────────────────────────────────────────

@loans_bp.route('/customer-loans/<customer_name>')
@login_required
def customer_loans(customer_name):
    """Return active/overdue loans for a customer — used in create form."""
    loans = query(
        "SELECT loan_id, loan_amount, balance_agreement, interest_rate, tenure, loan_status "
        "FROM loans WHERE customer_name=? AND loan_status IN ('active','overdue') ORDER BY id DESC",
        (customer_name,))
    return jsonify(loans)
