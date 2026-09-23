from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import date
from database import one, query, fmt_date, to_dt
from services import payment_service
from routes.backup import auto_sync_excel

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


def _loan_is_overdue(loan):
    if not loan or loan['loan_status'] == 'closed':
        return False
    try:
        from dateutil.relativedelta import relativedelta
        end_dt = to_dt(loan['loan_date']) + relativedelta(months=int(loan['tenure']))
        return date.today() > end_dt.date()
    except Exception:
        return False


@payments_bp.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    if search:
        like = f'%{search}%'
        rows = query("SELECT * FROM payments WHERE customer_name LIKE ? OR loan_id LIKE ? OR payment_id LIKE ? ORDER BY collection_date DESC LIMIT 200", (like, like, like))
    else:
        rows = query("SELECT * FROM payments ORDER BY collection_date DESC LIMIT 200")
    for p in rows:
        p['collection_date'] = fmt_date(p.get('collection_date'))
    return render_template('payments/index.html', payments=rows, search=search)


@payments_bp.route('/collect', methods=['GET', 'POST'])
@login_required
def collect():
    loan_id   = request.args.get('loan_id', '')
    loan      = None
    carry_fwd = 0
    total_due = 0
    overdue   = False

    if loan_id:
        loan = one("SELECT * FROM loans WHERE loan_id=? AND loan_status IN ('active','overdue')", (loan_id,))
        if loan:
            carry_fwd = payment_service.carry_forward(loan_id)
            total_due = round(loan['due_amount'] + carry_fwd, 2)
            overdue   = _loan_is_overdue(loan)

    if request.method == 'POST':
        loan_id = request.form['loan_id'].strip()
        try:
            result = payment_service.collect_payment(request.form, current_user.username)
        except payment_service.PaymentServiceError as e:
            flash(str(e), 'danger')
            return redirect(url_for('payments.collect'))
        auto_sync_excel()
        flash(result['message'], 'success')
        return redirect(url_for('payments.receipt', payment_id=result['payment_id']))

    active_loans = query("SELECT loan_id, customer_name, due_amount FROM loans WHERE loan_status IN ('active','overdue') ORDER BY customer_name")
    return render_template('payments/collect.html',
                           loan=loan, carry_forward=carry_fwd, total_due=total_due,
                           active_loans=active_loans, loan_id=loan_id, overdue=overdue)


@payments_bp.route('/receipt/<payment_id>')
@login_required
def receipt(payment_id):
    payment = one("SELECT * FROM payments WHERE payment_id=?", (payment_id,))
    if not payment:
        flash('Payment not found.', 'danger')
        return redirect(url_for('payments.index'))
    loan = one("SELECT * FROM loans WHERE loan_id=?", (payment['loan_id'],))
    payment['collection_date'] = fmt_date(payment.get('collection_date'))
    payment['created_at']      = fmt_date(payment.get('created_at'), '%d %b %Y %H:%M')
    return render_template('payments/receipt.html', payment=payment, loan=loan)


@payments_bp.route('/pending')
@login_required
def pending():
    rows = query("""
        SELECT p.loan_id, p.customer_name, p.pending_amount AS latest_pending,
               p.paid_amount AS last_paid, p.collection_date AS last_payment_date,
               l.loan_status, l.due_amount, l.phone
        FROM payments p JOIN loans l ON l.loan_id=p.loan_id
        WHERE p.id IN (
            SELECT id FROM payments p2 WHERE p2.loan_id=p.loan_id
            ORDER BY p2.collection_date DESC LIMIT 1
        ) AND p.pending_amount > 0
        ORDER BY p.pending_amount DESC
    """)
    for r in rows:
        r['last_payment_date_str'] = fmt_date(r.get('last_payment_date'))
    return render_template('payments/pending.html', pending_list=rows)


@payments_bp.route('/defaulters')
@login_required
def defaulters():
    overdue = query("SELECT * FROM loans WHERE loan_status='overdue' ORDER BY customer_name")
    result = []
    for loan in overdue:
        last = one("SELECT * FROM payments WHERE loan_id=? ORDER BY collection_date DESC LIMIT 1", (loan['loan_id'],))
        result.append({
            'loan': loan,
            'pending': last['pending_amount'] if last else loan['balance_agreement'],
            'last_date': fmt_date(last['collection_date']) if last else 'Never',
        })
    return render_template('payments/defaulters.html', defaulters_list=result)


@payments_bp.route('/api/loan-info/<loan_id>')
@login_required
def loan_info(loan_id):
    loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        return jsonify({'error': 'Not found'}), 404
    carry = payment_service.carry_forward(loan_id)
    overdue = _loan_is_overdue(loan)
    agreement = float(loan.get('agreement_value') or 0)
    principle = float(loan.get('principle_amount') or 0)
    ratio = (principle / agreement) if agreement else 0
    return jsonify({
        'loan_id':       loan['loan_id'],
        'customer_name': loan['customer_name'],
        'due_amount':    loan['due_amount'],
        'carry_forward': carry,
        'total_due':     round(loan['due_amount'] + carry, 2),
        'balance':       loan['balance_agreement'],
        'loan_status':   loan['loan_status'],
        'penalty_amount':loan['penalty_amount'],
        'overdue':       overdue,
        'principal_ratio': round(ratio, 6),
    })
