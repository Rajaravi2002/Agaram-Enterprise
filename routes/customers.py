from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from database import one, query, run, fmt_date
from services import audit_log

customers_bp = Blueprint('customers', __name__, url_prefix='/customers')


def _mask_aadhaar(value: str) -> str:
    """Audit item 31 — full Aadhaar is only shown to admins; everyone
    else sees the last 4 digits, matching how banks display it."""
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) < 4:
        return 'XXXX-XXXX-XXXX' if value else ''
    return f'XXXX-XXXX-{digits[-4:]}'


@customers_bp.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    if search:
        like = f'%{search}%'
        rows = query("SELECT * FROM customers WHERE is_active=1 AND (name LIKE ? OR phone LIKE ?) ORDER BY name", (like, like))
    else:
        rows = query("SELECT * FROM customers WHERE is_active=1 ORDER BY name")
    for c in rows:
        c['loan_count'] = one("SELECT COUNT(*) c FROM loans WHERE customer_name=?", (c['name'],))['c']
        c['date_added'] = fmt_date(c.get('date_added'))
    return render_template('customers/index.html', customers=rows, search=search)

@customers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if one("SELECT id FROM customers WHERE name=?", (name,)):
            flash(f'A customer named "{name}" already exists. Names must be unique.', 'warning')
            return render_template('customers/add.html', form_data=request.form)
        run("""INSERT INTO customers (name,phone,alt_phone,address,aadhaar,occupation,date_added,added_by,is_active)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (name, request.form.get('phone','').strip(), request.form.get('alt_phone','').strip(),
             request.form.get('address','').strip(), request.form.get('aadhaar','').strip(),
             request.form.get('occupation','').strip(),
             datetime.now().isoformat(timespec='seconds'), current_user.username))
        audit_log.record('CUSTOMER_CREATED', entity_type='customer', entity_id=name)
        flash(f'Customer "{name}" added successfully!', 'success')
        return redirect(url_for('customers.index'))
    return render_template('customers/add.html', form_data={})

@customers_bp.route('/<int:cid>')
@login_required
def view(cid):
    customer = one("SELECT * FROM customers WHERE id=?", (cid,))
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('customers.index'))
    customer['date_added'] = fmt_date(customer.get('date_added'))
    if not current_user.is_admin:
        customer['aadhaar'] = _mask_aadhaar(customer.get('aadhaar'))
    loans = query("SELECT * FROM loans WHERE customer_name=? ORDER BY created_at DESC", (customer['name'],))
    for l in loans:
        l['loan_date'] = fmt_date(l.get('loan_date'))
    return render_template('customers/view.html', customer=customer, loans=loans)

@customers_bp.route('/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def edit(cid):
    customer = one("SELECT * FROM customers WHERE id=?", (cid,))
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('customers.index'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        dup = one("SELECT id FROM customers WHERE name=? AND id!=?", (name, cid))
        if dup:
            flash(f'Another customer named "{name}" already exists.', 'warning')
            return render_template('customers/edit.html', customer=customer)
        old_name = customer['name']
        # Aadhaar can only be changed by an admin (audit item 31) — a
        # non-admin submission of this field is ignored and the
        # existing value is kept, same pattern as loan financial fields.
        aadhaar = request.form.get('aadhaar', '').strip() if current_user.is_admin else customer['aadhaar']
        run("UPDATE customers SET name=?,phone=?,alt_phone=?,address=?,aadhaar=?,occupation=? WHERE id=?",
            (name, request.form.get('phone','').strip(), request.form.get('alt_phone','').strip(),
             request.form.get('address','').strip(), aadhaar,
             request.form.get('occupation','').strip(), cid))
        if name != old_name:
            run("UPDATE loans    SET customer_name=? WHERE customer_name=?", (name, old_name))
            run("UPDATE payments SET customer_name=? WHERE customer_name=?", (name, old_name))
        audit_log.record('CUSTOMER_EDITED', entity_type='customer', entity_id=name,
                          old_value=old_name if name != old_name else '')
        flash('Customer updated.', 'success')
        return redirect(url_for('customers.view', cid=cid))
    customer['date_added'] = fmt_date(customer.get('date_added'))
    if not current_user.is_admin:
        customer['aadhaar'] = _mask_aadhaar(customer.get('aadhaar'))
    return render_template('customers/edit.html', customer=customer)

@customers_bp.route('/<int:cid>/delete', methods=['POST'])
@login_required
def delete(cid):
    if not current_user.is_admin:
        flash('Only admin can delete customers.', 'danger')
        return redirect(url_for('customers.index'))
    c = one("SELECT * FROM customers WHERE id=?", (cid,))
    if c:
        active = one("SELECT COUNT(*) n FROM loans WHERE customer_name=? AND loan_status IN ('active', 'overdue')", (c['name'],))['n']
        if active:
            flash('Cannot delete customer with active or overdue loans.', 'warning')
            return redirect(url_for('customers.view', cid=cid))
    run("UPDATE customers SET is_active=0 WHERE id=?", (cid,))
    audit_log.record('CUSTOMER_DEACTIVATED', entity_type='customer', entity_id=c['name'] if c else str(cid))
    flash('Customer deactivated.', 'success')
    return redirect(url_for('customers.index'))

@customers_bp.route('/lookup')
@login_required
def lookup():
    """AJAX: return customer info by name"""
    from flask import jsonify
    name = request.args.get('name','').strip()
    c = one("SELECT * FROM customers WHERE name=? AND is_active=1", (name,))
    if c:
        return jsonify({'found': True, 'phone': c['phone'], 'alt_phone': c['alt_phone'], 'address': c['address']})
    return jsonify({'found': False})
