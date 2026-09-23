from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from datetime import datetime, timedelta
from database import one, query
import calendar

dashboard_bp = Blueprint('dashboard', __name__)


def get_dashboard_stats():
    now = datetime.now()
    today_str       = now.strftime('%Y-%m-%d')
    yesterday_str   = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    month_start_str = now.strftime('%Y-%m-01')
    # Previous month range
    prev_month_last  = (now.replace(day=1) - timedelta(days=1))
    prev_month_start = prev_month_last.strftime('%Y-%m-01')
    prev_month_end   = prev_month_last.strftime('%Y-%m-%d')

    total_customers  = one("SELECT COUNT(*) c FROM customers WHERE is_active=1")['c']
    active_loans     = one("SELECT COUNT(*) c FROM loans WHERE loan_status='active'")['c']
    closed_loans     = one("SELECT COUNT(*) c FROM loans WHERE loan_status='closed'")['c']
    overdue_loans    = one("SELECT COUNT(*) c FROM loans WHERE loan_status='overdue'")['c']

    total_loan_issued = one("SELECT COALESCE(SUM(loan_amount),0)  v FROM loans")['v']
    total_collected   = one("SELECT COALESCE(SUM(paid_amount),0)  v FROM payments")['v']
    outstanding       = one("SELECT COALESCE(SUM(pending_amount),0) v FROM payments")['v']

    today_collection = one(
        "SELECT COALESCE(SUM(paid_amount),0) v FROM payments WHERE DATE(collection_date) = ?",
        (today_str,))['v']
    yesterday_collection = one(
        "SELECT COALESCE(SUM(paid_amount),0) v FROM payments WHERE DATE(collection_date) = ?",
        (yesterday_str,))['v']

    monthly_collection = one(
        "SELECT COALESCE(SUM(paid_amount),0) v FROM payments WHERE DATE(collection_date) >= ?",
        (month_start_str,))['v']
    prev_month_collection = one(
        "SELECT COALESCE(SUM(paid_amount),0) v FROM payments "
        "WHERE DATE(collection_date) >= ? AND DATE(collection_date) <= ?",
        (prev_month_start, prev_month_end))['v']

    total_loans = active_loans + closed_loans + overdue_loans

    def _delta_pct(current, previous):
        if previous <= 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 1)

    collection_rate = 0.0
    if total_loan_issued > 0:
        collection_rate = round((total_collected / total_loan_issued) * 100, 1)

    return {
        'total_customers':    total_customers,
        'active_loans':       active_loans,
        'closed_loans':       closed_loans,
        'overdue_loans':      overdue_loans,
        'total_loans':        total_loans,
        'total_loan_issued':  round(total_loan_issued, 2),
        'total_collected':    round(total_collected, 2),
        'outstanding':        round(outstanding, 2),
        'today_collection':   round(today_collection, 2),
        'yesterday_collection': round(yesterday_collection, 2),
        'monthly_collection': round(monthly_collection, 2),
        'prev_month_collection': round(prev_month_collection, 2),
        'today_delta_pct':    _delta_pct(today_collection, yesterday_collection),
        'month_delta_pct':    _delta_pct(monthly_collection, prev_month_collection),
        'collection_rate':    collection_rate,
    }


@dashboard_bp.route('/dashboard')
@login_required
def index():
    return render_template('dashboard/index.html', stats=get_dashboard_stats())


@dashboard_bp.route('/api/chart/monthly-collection')
@login_required
def chart_monthly_collection():
    today = datetime.now()
    labels, values = [], []
    for i in range(11, -1, -1):
        yr, mo = today.year, today.month - i
        while mo <= 0:
            mo += 12; yr -= 1
        ms_str = f"{yr:04d}-{mo:02d}-01"
        _, ld = calendar.monthrange(yr, mo)
        me_str = f"{yr:04d}-{mo:02d}-{ld:02d}"
        v = one("SELECT COALESCE(SUM(paid_amount),0) v FROM payments "
                "WHERE DATE(collection_date) >= ? AND DATE(collection_date) <= ?",
                (ms_str, me_str))['v']
        labels.append(datetime(yr, mo, 1).strftime('%b %Y'))
        values.append(round(v, 2))
    return jsonify({'labels': labels, 'values': values})


@dashboard_bp.route('/api/chart/loan-distribution')
@login_required
def chart_loan_distribution():
    r = one("""SELECT
        SUM(CASE WHEN loan_status='active'  THEN 1 ELSE 0 END) active,
        SUM(CASE WHEN loan_status='closed'  THEN 1 ELSE 0 END) closed,
        SUM(CASE WHEN loan_status='overdue' THEN 1 ELSE 0 END) overdue
        FROM loans""")
    return jsonify({
        'labels': ['Active', 'Closed', 'Overdue'],
        'values': [r['active'] or 0, r['closed'] or 0, r['overdue'] or 0]
    })


@dashboard_bp.route('/api/chart/top-borrowers')
@login_required
def chart_top_borrowers():
    rows = query("""SELECT customer_name, SUM(loan_amount) total
                    FROM loans GROUP BY customer_name
                    ORDER BY total DESC LIMIT 7""")
    return jsonify({
        'labels': [r['customer_name'] for r in rows],
        'values': [round(r['total'], 2) for r in rows]
    })


@dashboard_bp.route('/api/chart/collection-performance')
@login_required
def chart_collection_performance():
    today = datetime.now()
    labels, collected, pending = [], [], []
    for i in range(5, -1, -1):
        yr, mo = today.year, today.month - i
        while mo <= 0:
            mo += 12; yr -= 1
        ms_str = f"{yr:04d}-{mo:02d}-01"
        _, ld = calendar.monthrange(yr, mo)
        me_str = f"{yr:04d}-{mo:02d}-{ld:02d}"
        c = one("SELECT COALESCE(SUM(paid_amount),0)    v FROM payments WHERE DATE(collection_date)>=? AND DATE(collection_date)<=?", (ms_str, me_str))['v']
        p = one("SELECT COALESCE(SUM(pending_amount),0) v FROM payments WHERE DATE(collection_date)>=? AND DATE(collection_date)<=?", (ms_str, me_str))['v']
        labels.append(datetime(yr, mo, 1).strftime('%b %Y'))
        collected.append(round(c, 2))
        pending.append(round(p, 2))
    return jsonify({'labels': labels, 'collected': collected, 'pending': pending})


@dashboard_bp.route('/api/recent-activity')
@login_required
def recent_activity():
    rows = query("""SELECT payment_id, customer_name, paid_amount, collection_date, payment_type
                    FROM payments ORDER BY id DESC LIMIT 8""")
    for r in rows:
        # collection_date is stored as ISO string; format for display
        r['collection_date'] = _fmt(r.get('collection_date'))
    return jsonify(rows)


def _fmt(val):
    if not val:
        return ''
    for f in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(val), f).strftime('%d %b %Y')
        except ValueError:
            pass
    return str(val)
