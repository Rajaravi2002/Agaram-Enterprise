from flask import Blueprint, jsonify, request
from flask_login import login_required
from database import one, query, fmt_date

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'customers': [], 'loans': [], 'payments': []})
    like = f'%{q}%'
    customers = query(
        "SELECT id,name,phone,occupation FROM customers "
        "WHERE is_active=1 AND (name LIKE ? OR phone LIKE ?) LIMIT 5",
        (like, like))
    loans = query(
        "SELECT loan_id,customer_name,loan_amount,loan_status,vehicle_number FROM loans "
        "WHERE loan_id LIKE ? OR customer_name LIKE ? OR vehicle_number LIKE ? LIMIT 5",
        (like, like, like))
    payments = query(
        "SELECT payment_id,customer_name,paid_amount,collection_date FROM payments "
        "WHERE payment_id LIKE ? OR customer_name LIKE ? OR loan_id LIKE ? LIMIT 5",
        (like, like, like))
    for p in payments:
        p['collection_date'] = fmt_date(p.get('collection_date'))
    return jsonify({'customers': customers, 'loans': loans, 'payments': payments})


# ── Autocomplete suggestions ───────────────────────────────────────────────────

@api_bp.route('/suggest/customers')
@login_required
def suggest_customers():
    """Return name suggestions for customer search bars."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    like = f'%{q}%'
    rows = query(
        "SELECT name, phone FROM customers WHERE is_active=1 "
        "AND (name LIKE ? OR phone LIKE ?) ORDER BY name LIMIT 8",
        (like, like))
    return jsonify([{'label': f"{r['name']} ({r['phone']})", 'value': r['name']} for r in rows])


@api_bp.route('/suggest/loans')
@login_required
def suggest_loans():
    """Return loan ID suggestions."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    like = f'{q}%'  # prefix match for loan IDs
    rows = query(
        "SELECT loan_id, customer_name, loan_status FROM loans "
        "WHERE loan_id LIKE ? OR customer_name LIKE ? ORDER BY id DESC LIMIT 8",
        (like, f'%{q}%'))
    return jsonify([{'label': f"{r['loan_id']} — {r['customer_name']} ({r['loan_status']})",
                     'value': r['loan_id']} for r in rows])


@api_bp.route('/suggest/vehicle')
@login_required
def suggest_vehicle():
    q = request.args.get('q', '').strip()
    if not q: return jsonify([])
    like = f'%{q}%'
    rows = query(
        "SELECT DISTINCT vehicle_number FROM loans WHERE vehicle_number LIKE ? "
        "AND vehicle_number!='' ORDER BY vehicle_number LIMIT 8", (like,))
    return jsonify([{'label': r['vehicle_number'], 'value': r['vehicle_number']} for r in rows])


@api_bp.route('/suggest/followers')
@login_required
def suggest_followers():
    q = request.args.get('q', '').strip()
    like = f'%{q}%' if q else '%'
    rows = query(
        "SELECT DISTINCT follower FROM loans WHERE follower LIKE ? AND follower!='' "
        "ORDER BY follower LIMIT 8", (like,))
    return jsonify([{'label': r['follower'], 'value': r['follower']} for r in rows])


@api_bp.route('/suggest/refs')
@login_required
def suggest_refs():
    q = request.args.get('q', '').strip()
    like = f'%{q}%' if q else '%'
    rows = query(
        "SELECT DISTINCT ref FROM loans WHERE ref LIKE ? AND ref!='' ORDER BY ref LIMIT 8",
        (like,))
    return jsonify([{'label': r['ref'], 'value': r['ref']} for r in rows])


# ── Loan ID existence check ───────────────────────────────────────────────────

@api_bp.route('/check-loan-id')
@login_required
def check_loan_id():
    loan_id = request.args.get('id', '').strip().upper()
    if not loan_id:
        return jsonify({'exists': False})
    loan = one("SELECT loan_id, customer_name, loan_status FROM loans WHERE loan_id=?", (loan_id,))
    if loan:
        return jsonify({'exists': True, 'customer_name': loan['customer_name'],
                        'loan_status': loan['loan_status']})
    return jsonify({'exists': False})


# ── Other helpers ─────────────────────────────────────────────────────────────

@api_bp.route('/customer-by-name')
@login_required
def customer_by_name():
    name = request.args.get('name', '').strip()
    c = one("SELECT * FROM customers WHERE name=? AND is_active=1", (name,))
    if not c:
        return jsonify({'found': False})
    c['date_added'] = fmt_date(c.get('date_added'))
    return jsonify({'found': True, **c})


@api_bp.route('/stats/summary')
@login_required
def stats_summary():
    return jsonify({
        'customers':    one("SELECT COUNT(*) c FROM customers WHERE is_active=1")['c'],
        'active_loans': one("SELECT COUNT(*) c FROM loans WHERE loan_status='active'")['c'],
        'overdue_loans':one("SELECT COUNT(*) c FROM loans WHERE loan_status='overdue'")['c'],
    })
