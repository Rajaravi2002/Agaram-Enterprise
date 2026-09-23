from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from database import one, query
from services import settlement_service
from routes.backup import auto_sync_excel
from datetime import date

settlement_bp = Blueprint('settlement', __name__, url_prefix='/settlement')


@settlement_bp.route('/')
@login_required
def index():
    loan_id = request.args.get('loan_id', '').strip()
    loan    = None
    result  = None
    as_of   = request.args.get('as_of', date.today().isoformat())
    if loan_id:
        loan = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
        if loan:
            result = settlement_service.calc_settlement(loan, as_of)

    active_loans = query(
        "SELECT loan_id, customer_name, balance_agreement FROM loans "
        "WHERE loan_status IN ('active','overdue') ORDER BY customer_name"
    )
    return render_template('settlement/index.html',
                           loan=loan, result=result, loan_id=loan_id,
                           as_of=as_of, active_loans=active_loans,
                           today=date.today().isoformat())


@settlement_bp.route('/calculate')
@login_required
def calculate():
    """AJAX endpoint."""
    loan_id = request.args.get('loan_id', '').strip()
    as_of   = request.args.get('as_of', date.today().isoformat())
    loan    = one("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
    if not loan:
        return jsonify({'error': 'Loan not found'}), 404
    return jsonify(settlement_service.calc_settlement(loan, as_of))


@settlement_bp.route('/collect', methods=['POST'])
@login_required
def collect():
    try:
        payment_id = settlement_service.collect_settlement(request.form, current_user.username)
    except settlement_service.SettlementServiceError as e:
        flash(str(e), 'danger')
        return redirect(url_for('settlement.index'))

    auto_sync_excel()
    loan_id = request.form.get('loan_id', '').strip()
    flash(f'Settlement collected for {loan_id}. Loan is now closed.', 'success')
    return redirect(url_for('payments.receipt', payment_id=payment_id))
