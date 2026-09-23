from flask import Blueprint, render_template, redirect, url_for, flash, send_file, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
from database import one, query, run, get_db, fmt_date, next_loan_id, transaction, metadata
from config import Config
from services import audit_log
import os, io, zipfile

backup_bp = Blueprint('backup', __name__, url_prefix='/backup')

TABLES = ['users', 'customers', 'loans', 'payments']

# ── Excel column → DB field mapping (matches company Sheet1) ─────────────────
# Col:  A      B         C           D       E        F    G         H
# Idx:  0      1         2           3       4        5    6         7
#       Sl.No  Loan No   Loan Date   Name    Mobile   Ref  Due Date  Follower
# Col:  I            J                K                L               M
# Idx:  8            9                10               11              12
#       Loan Amount  Document Charge  Principle Amount Interest Amount Agreement Value
# Col:  N       O           P         Q             R              S
# Idx:  13      14          15        16            17             18
#       Tenure  Due Amount  Paid Due  Paid Amount   Feature Dues   Balance Agreement
# Col:  T      U              V               W               X        Y
# Idx:  19     20             21              22              23       24
#       int %  Vehicle Model  Vehicle Number  Doc Status      Remarks  (empty)

EXCEL_COL_MAP = {
    'loan_id':           1,
    'loan_date':         2,
    'customer_name':     3,
    'phone':             4,
    'ref':               5,
    'due_day':           6,
    'follower':          7,
    'loan_amount':       8,
    'document_charge':   9,
    'principle_amount':  10,
    'interest_amount':   11,
    'agreement_value':   12,
    'tenure':            13,
    'due_amount':        14,
    'paid_due':          15,
    'paid_amount':       16,
    'feature_dues':      17,
    'balance_agreement': 18,
    'int_pct':           19,
    'vehicle_model':     20,
    'vehicle_number':    21,
    'document_status':   22,
    'remarks':           23,
}

# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_float(v):
    try:
        if v is None or str(v).strip() in ('', '-', 'None'): return 0.0
        return float(str(v).replace(',', '').strip())
    except Exception:
        return 0.0

def _safe_int(v):
    try:
        if v is None or str(v).strip() in ('', '-', 'None'): return 0
        return int(float(str(v).strip()))
    except Exception:
        return 0

def _safe_str(v):
    if v is None: return ''
    return str(v).strip()

def _parse_date(v):
    """Parse various date formats → YYYY-MM-DD string."""
    if v is None: return ''
    s = str(v).strip()
    if not s or s == 'None': return ''
    # Already ISO
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    # DD-MM-YYYY
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y'):
        try:
            return datetime.strptime(s[:10], fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    # datetime string from Excel
    try:
        return datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
    except ValueError:
        pass
    return s[:10]


# ── Excel backup export ────────────────────────────────────────────────────────

def auto_sync_excel():
    """Automatically save the latest Excel backup to the reports folder."""
    try:
        output = create_excel_backup_file()
        reports_dir = os.path.join(current_app.root_path, 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        sync_path = os.path.join(reports_dir, 'agaram_finance_sync.xlsx')
        with open(sync_path, 'wb') as f:
            f.write(output.getvalue())
        return True
    except Exception as e:
        print(f"Excel Sync Error: {e}")
        return False

def create_excel_backup_file():
    """Export all loans to a styled Excel file matching the company format."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    loans = query("SELECT * FROM loans ORDER BY id")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.freeze_panes = "A2"

    # ── Styling helpers ───────────────────────────────────────────────────────
    HDR_FILL  = PatternFill("solid", start_color="0F4C81")
    HDR_FONT  = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    DATA_FONT = Font(name="Arial", size=9)
    ALT_FILL  = PatternFill("solid", start_color="EEF3FA")
    THIN      = Side(style='thin', color="CCCCCC")
    BDR       = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    CENTER    = Alignment(horizontal='center', vertical='center', wrap_text=True)
    LEFT      = Alignment(horizontal='left',   vertical='center', wrap_text=True)

    # ── Headers (matching company sheet exactly) ──────────────────────────────
    headers = [
        "Sl.No", "Loan No", "Loan Date", "Name", "Mobile Number",
        "Ref", "Due Date", "Follower",
        "Loan Amount", "Document Charge", "Princple Amount",
        "Interst Amount", "Agrement Value", "Tenure", "Due Amount",
        "Paid Due", "Paid Amount", "Feature Dues",
        "Balance Aggrement Amount", "int %", "Rate %/mo",
        "Vehicle Model", "Vehicle Number", "Document Status",
        "Remarks", "Penalty Amount", "Penalty Description",
    ]
    col_widths = [6, 10, 13, 24, 24, 10, 9, 12,
                  13, 15, 15, 14, 14, 8, 12,
                  9, 13, 12, 20, 7, 9,
                  26, 16, 22,
                  28, 13, 28]

    for ci, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.fill = HDR_FILL; cell.font = HDR_FONT
        cell.border = BDR;    cell.alignment = CENTER
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[1].height = 32

    # ── Data rows ─────────────────────────────────────────────────────────────
    totals = {c: 0.0 for c in [9,10,11,12,13,15,17,19,26]}
    for ri, l in enumerate(loans, 2):
        fill = ALT_FILL if ri % 2 == 0 else PatternFill()
        row_data = [
            ri - 1,
            l['loan_id'],
            fmt_date(l['loan_date'], '%d-%m-%Y'),
            l['customer_name'],
            l['phone'],
            l['ref'],
            l['due_day'],
            l['follower'],
            l['loan_amount'],
            l['document_charge'],
            l['principle_amount'],
            l['interest_amount'],
            l['agreement_value'],
            l['tenure'],
            l['due_amount'],
            l['paid_due'],
            l['paid_amount'],
            l['feature_dues'],
            l['balance_agreement'],
            l['int_pct'],
            l.get('interest_rate', 0),
            l['vehicle_model'],
            l['vehicle_number'],
            l['document_status'],
            l['remarks'],
            l['penalty_amount'],
            l['penalty_description'],
        ]
        # accumulate totals for numeric cols
        for ci_t, fi in [(9,'loan_amount'),(10,'document_charge'),(11,'principle_amount'),
                         (12,'interest_amount'),(13,'agreement_value'),(15,'due_amount'),
                         (17,'paid_amount'),(19,'balance_agreement'),(26,'penalty_amount')]:
            totals[ci_t] = totals.get(ci_t, 0) + (l[fi] or 0)

        for ci, val in enumerate(row_data, 1):
            c = ws.cell(row=ri, column=ci, value=val)
            c.font = DATA_FONT; c.border = BDR; c.fill = fill
            c.alignment = LEFT
            if isinstance(val, (int, float)) and ci not in (1, 14, 16, 18):
                c.number_format = '#,##0.00'

    # ── Totals row ────────────────────────────────────────────────────────────
    tr = len(loans) + 2
    ws.cell(tr, 1, "TOTAL").font = Font(bold=True, name="Arial", size=10)
    for ci, key in totals.items():
        c = ws.cell(tr, ci, key)
        c.font  = Font(bold=True, name="Arial", size=9)
        c.fill  = PatternFill("solid", start_color="D6E4F7")
        c.border = BDR
        c.number_format = '#,##0.00'

    # ── Payment History sheet ───────────────────────────────────────────────────
    ws2 = wb.create_sheet("Payment History")
    ws2.freeze_panes = "A2"
    pay_headers = ["Sl.No", "Payment ID", "Loan No", "Customer Name", "Collection Date",
                   "Payment Type", "Payment Mode", "EMI Amount", "Carry Forward", "Total Due",
                   "Paid Amount", "Principal", "Interest", "Pending Amount", "Outstanding",
                   "Penalty Amount", "Month #", "Remarks", "Collected By"]
    pay_widths  = [6, 14, 10, 24, 14, 12, 12, 12, 13, 12, 12, 12, 12, 13, 13, 13, 8, 26, 14]
    for ci, (h, w) in enumerate(zip(pay_headers, pay_widths), 1):
        cell = ws2.cell(row=1, column=ci, value=h)
        cell.fill = HDR_FILL; cell.font = HDR_FONT
        cell.border = BDR;    cell.alignment = CENTER
        ws2.column_dimensions[get_column_letter(ci)].width = w
    ws2.row_dimensions[1].height = 30

    payments = query("SELECT * FROM payments ORDER BY collection_date DESC")
    pay_totals = {'paid': 0.0, 'principal': 0.0, 'interest': 0.0, 'pending': 0.0, 'penalty': 0.0}
    for ri, p in enumerate(payments, 2):
        fill = ALT_FILL if ri % 2 == 0 else PatternFill()
        row_data = [
            ri - 1, p['payment_id'], p['loan_id'], p['customer_name'],
            fmt_date(p['collection_date'], '%d-%m-%Y'),
            p.get('payment_type', 'EMI'), p.get('payment_mode', 'Cash'),
            p['emi_amount'], p['carry_forward'], p['total_due'],
            p['paid_amount'], p.get('principal_component', 0), p.get('interest_component', 0),
            p['pending_amount'], p.get('outstanding_balance', 0), p['penalty_amount'],
            p['month_number'], p['collection_remarks'], p['collected_by'],
        ]
        pay_totals['paid']      += p['paid_amount'] or 0
        pay_totals['principal'] += p.get('principal_component', 0) or 0
        pay_totals['interest']  += p.get('interest_component', 0) or 0
        pay_totals['pending']   += p['pending_amount'] or 0
        pay_totals['penalty']   += p['penalty_amount'] or 0
        for ci, val in enumerate(row_data, 1):
            c = ws2.cell(row=ri, column=ci, value=val)
            c.font = DATA_FONT; c.border = BDR; c.fill = fill
            c.alignment = LEFT
            # Numeric columns: 8-16 (EMI Amount through Penalty Amount); Month#(17) stays plain int
            if isinstance(val, (int, float)) and ci not in (1, 17):
                c.number_format = '#,##0.00'

    ptr = len(payments) + 2
    ws2.cell(ptr, 1, "TOTAL").font = Font(bold=True, name="Arial", size=10)
    # Column indices matched to the header layout above:
    # 11=Paid Amount, 12=Principal, 13=Interest, 14=Pending Amount, 16=Penalty Amount
    totals_map = {
        11: pay_totals['paid'],
        12: pay_totals['principal'],
        13: pay_totals['interest'],
        14: pay_totals['pending'],
        16: pay_totals['penalty'],
    }
    for ci, key in totals_map.items():
        c = ws2.cell(ptr, ci, key)
        c.font = Font(bold=True, name="Arial", size=9)
        c.fill = PatternFill("solid", start_color="D6E4F7")
        c.border = BDR
        c.number_format = '#,##0.00'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# ── core JSON backup ──────────────────────────────────────────────────────────

def create_backup(backup_type='manual', created_by='system'):
    import json
    timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = Config.BACKUP_FOLDER
    os.makedirs(backup_dir, exist_ok=True)

    # 1) JSON snapshot
    payload = {tbl: query(f"SELECT * FROM {tbl}") for tbl in TABLES}
    json_bytes = json.dumps(payload, indent=2, default=str, ensure_ascii=False).encode('utf-8')

    # 2) Excel snapshot
    excel_bytes = create_excel_backup_file().getvalue()

    zip_name = f'agaram_backup_{timestamp}.zip'
    zip_path = os.path.join(backup_dir, zip_name)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'agaram_backup_{timestamp}.json',  json_bytes)
        zf.writestr(f'agaram_loans_{timestamp}.xlsx',   excel_bytes)

    file_size = os.path.getsize(zip_path)
    backup_id = f'BAK-{timestamp}'
    run("""INSERT INTO backups
           (backup_id,backup_type,file_path,file_name,file_size,created_at,created_by,status)
           VALUES (?,?,?,?,?,?,?,'success')""",
        (backup_id, backup_type, zip_path, zip_name,
         file_size, datetime.now().isoformat(timespec='seconds'), created_by))
    auto_sync_excel()
    return backup_id, zip_path, zip_name


# ── Excel import ──────────────────────────────────────────────────────────────

def _import_excel(filepath):
    """
    Parse the company Excel sheet and upsert loans + customers.
    Returns (inserted, updated, skipped, errors).
    """
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    inserted = updated = skipped = 0
    errors = []

    # Find the header row (look for "Loan No" anywhere in first 5 rows)
    header_row = 1
    for r in range(1, 6):
        row_vals = [str(c.value or '').strip() for c in ws[r]]
        if any('Loan No' in v or 'loan no' in v.lower() for v in row_vals):
            header_row = r
            break

    for ri, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        # Skip empty rows
        if not row or all(v is None for v in row):
            continue

        def col(idx):
            try:    return row[idx] if idx < len(row) else None
            except: return None

        loan_id_raw = _safe_str(col(EXCEL_COL_MAP['loan_id']))
        name_raw    = _safe_str(col(EXCEL_COL_MAP['customer_name']))

        # Skip rows without a loan number or name
        if not loan_id_raw and not name_raw:
            skipped += 1
            continue

        # Auto-generate loan_id if missing
        if not loan_id_raw:
            loan_id_raw = next_loan_id()

        # Normalise loan_id to AGM#### format
        loan_id = loan_id_raw.strip().upper()
        if not loan_id.startswith('AGM'):
            loan_id = f'AGM{loan_id.zfill(4)}'

        try:
            phone         = _safe_str(col(EXCEL_COL_MAP['phone']))
            ref           = _safe_str(col(EXCEL_COL_MAP['ref']))
            due_day       = _safe_str(col(EXCEL_COL_MAP['due_day']))
            follower      = _safe_str(col(EXCEL_COL_MAP['follower']))
            loan_date     = _parse_date(col(EXCEL_COL_MAP['loan_date']))
            loan_amount   = _safe_float(col(EXCEL_COL_MAP['loan_amount']))
            doc_charge    = _safe_float(col(EXCEL_COL_MAP['document_charge']))
            principle     = _safe_float(col(EXCEL_COL_MAP['principle_amount']))
            interest      = _safe_float(col(EXCEL_COL_MAP['interest_amount']))
            agreement     = _safe_float(col(EXCEL_COL_MAP['agreement_value']))
            tenure        = _safe_int(col(EXCEL_COL_MAP['tenure']))
            due_amount    = _safe_float(col(EXCEL_COL_MAP['due_amount']))
            paid_due      = _safe_int(col(EXCEL_COL_MAP['paid_due']))
            paid_amount   = _safe_float(col(EXCEL_COL_MAP['paid_amount']))
            feature_dues  = _safe_int(col(EXCEL_COL_MAP['feature_dues']))
            balance       = _safe_float(col(EXCEL_COL_MAP['balance_agreement']))
            int_pct       = _safe_str(col(EXCEL_COL_MAP['int_pct']))
            veh_model     = _safe_str(col(EXCEL_COL_MAP['vehicle_model']))
            veh_number    = _safe_str(col(EXCEL_COL_MAP['vehicle_number']))
            doc_status    = _safe_str(col(EXCEL_COL_MAP['document_status']))
            remarks       = _safe_str(col(EXCEL_COL_MAP['remarks']))

            if not name_raw:
                raise ValueError('customer name is required')
            if not loan_date:
                raise ValueError('loan date is required')
            try:
                datetime.strptime(loan_date, '%Y-%m-%d')
            except ValueError as exc:
                raise ValueError(f'invalid loan date: {loan_date}') from exc
            if loan_amount <= 0:
                raise ValueError('loan amount must be greater than zero')
            if tenure <= 0:
                raise ValueError('tenure must be greater than zero')

            # Compute missing fields if Excel had formulas (data_only gives result)
            if principle == 0 and loan_amount > 0:
                principle = loan_amount - doc_charge
            if agreement == 0 and principle > 0:
                agreement = principle + interest
            if due_amount == 0 and agreement > 0 and tenure > 0:
                due_amount = round(agreement / tenure, 2)
            if balance == 0 and agreement > 0 and paid_amount > 0:
                balance = round(agreement - paid_amount, 2)

            # Back-compute interest_rate from interest/principle/tenure
            if principle > 0 and tenure > 0 and interest > 0:
                interest_rate_num = round((interest / (principle * tenure)) * 100, 4)
            elif int_pct:
                try:
                    interest_rate_num = float(str(int_pct).replace('%','').strip())
                except Exception:
                    interest_rate_num = 0.0
            else:
                interest_rate_num = 0.0

            # Determine status
            status = 'active'
            if balance <= 0 and paid_amount > 0:
                status = 'closed'
            elif feature_dues > 0:
                # Check if overdue based on date
                try:
                    from dateutil.relativedelta import relativedelta
                    end_date = datetime.strptime(loan_date, '%Y-%m-%d') + relativedelta(months=int(tenure))
                    if datetime.now() > end_date:
                        status = 'overdue'
                except:
                    pass

            now = datetime.now().isoformat(timespec='seconds')

            # Upsert customer (by name)
            if name_raw:
                existing_cust = one("SELECT id FROM customers WHERE name=?", (name_raw,))
                if not existing_cust:
                    run("""INSERT INTO customers
                           (name,phone,alt_phone,address,aadhaar,occupation,date_added,added_by,is_active)
                           VALUES (?,?,?,?,?,?,?,?,1)""",
                        (name_raw, phone, '', '', '', '', now, 'excel_import'))

            # Upsert loan using portable UPDATE/INSERT statements. SQLite's
            # INSERT OR REPLACE deletes and recreates a row, while PostgreSQL
            # does not support that syntax and deletion would lose the row id.
            existing_loan = one("SELECT id FROM loans WHERE loan_id=?", (loan_id,))
            loan_values = (
                loan_id, name_raw, phone, ref, follower, loan_date, due_day,
                 loan_amount, doc_charge, principle, interest_rate_num, interest, agreement,
                 tenure, due_amount, paid_due, paid_amount, feature_dues, balance,
                 int_pct, veh_model, veh_number, doc_status, remarks,
                 0, '', '[]', status, now, 'excel_import')
            if existing_loan:
                run("""UPDATE loans SET
                       customer_name=?,phone=?,ref=?,follower=?,loan_date=?,due_day=?,
                       loan_amount=?,document_charge=?,principle_amount=?,interest_rate=?,interest_amount=?,agreement_value=?,
                       tenure=?,due_amount=?,paid_due=?,paid_amount=?,feature_dues=?,balance_agreement=?,int_pct=?,
                       vehicle_model=?,vehicle_number=?,document_status=?,remarks=?,penalty_amount=?,penalty_description=?,
                       topup_history=?,loan_status=?,created_at=?,created_by=? WHERE loan_id=?""",
                    loan_values[1:] + (loan_id,))
            else:
                run("""INSERT INTO loans
                   (loan_id,customer_name,phone,ref,follower,loan_date,due_day,
                    loan_amount,document_charge,principle_amount,interest_rate,interest_amount,agreement_value,
                    tenure,due_amount,paid_due,paid_amount,feature_dues,balance_agreement,int_pct,
                    vehicle_model,vehicle_number,document_status,remarks,
                    penalty_amount,penalty_description,topup_history,loan_status,created_at,created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    loan_values)

            if existing_loan:
                updated += 1
            else:
                inserted += 1

        except Exception as exc:
            errors.append(f'Row {ri} ({loan_id_raw}): {exc}')
            skipped += 1

    return inserted, updated, skipped, errors


# ── routes ────────────────────────────────────────────────────────────────────

@backup_bp.route('/')
@login_required
def index():
    backups = query("SELECT * FROM backups ORDER BY created_at DESC")
    for b in backups:
        b['file_exists']    = os.path.exists(b.get('file_path', ''))
        b['size_kb']        = round(b.get('file_size', 0) / 1024, 1)
        b['created_at_str'] = fmt_date(b.get('created_at'), '%d %b %Y %H:%M')
    # Auto-backup scheduler status
    try:
        import scheduler
        auto_interval_hours = scheduler.INTERVAL_HOURS
        auto_keep_last      = scheduler.KEEP_LAST
    except Exception:
        auto_interval_hours = 24
        auto_keep_last      = 30
    last_auto = next((b for b in backups if b.get('backup_type') == 'auto'), None)
    return render_template('backup/index.html', backups=backups,
                           auto_interval_hours=auto_interval_hours,
                           auto_keep_last=auto_keep_last,
                           last_auto=last_auto)


@backup_bp.route('/create', methods=['POST'])
@login_required
def create():
    if not current_user.is_admin:
        flash('Only admin can create backups.', 'danger')
        return redirect(url_for('backup.index'))
    try:
        _, _, zip_name = create_backup('manual', current_user.username)
        audit_log.record('BACKUP_CREATED', entity_type='backup', entity_id=zip_name)
        flash(f'Backup created: {zip_name} (contains JSON + Excel)', 'success')
    except Exception as exc:
        flash(f'Backup failed: {exc}', 'danger')
    return redirect(url_for('backup.index'))


@backup_bp.route('/download-excel')
@login_required
def download_excel():
    """Instant Excel-only download without saving a backup record."""
    try:
        output = create_excel_backup_file()
        fname  = f'agaram_loans_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        return send_file(output, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        flash(f'Excel export failed: {exc}', 'danger')
        return redirect(url_for('backup.index'))


@backup_bp.route('/download/<backup_id>')
@login_required
def download(backup_id):
    b = one("SELECT * FROM backups WHERE backup_id=?", (backup_id,))
    if not b or not os.path.exists(b.get('file_path', '')):
        flash('Backup file not found.', 'danger')
        return redirect(url_for('backup.index'))
    return send_file(b['file_path'], as_attachment=True, download_name=b['file_name'])


@backup_bp.route('/download-excel-from/<backup_id>')
@login_required
def download_excel_from_backup(backup_id):
    """Extract and serve the Excel file from inside a backup ZIP."""
    b = one("SELECT * FROM backups WHERE backup_id=?", (backup_id,))
    if not b or not os.path.exists(b.get('file_path', '')):
        flash('Backup file not found.', 'danger')
        return redirect(url_for('backup.index'))
    with zipfile.ZipFile(b['file_path'], 'r') as zf:
        excel_names = [n for n in zf.namelist() if n.endswith('.xlsx')]
        if not excel_names:
            flash('No Excel file found in this backup (older backup format). Use "Download Excel Now" instead.', 'warning')
            return redirect(url_for('backup.index'))
        xlsx_bytes = zf.read(excel_names[0])
    return send_file(io.BytesIO(xlsx_bytes), as_attachment=True,
                     download_name=excel_names[0],
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@backup_bp.route('/import-excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    if not current_user.is_admin:
        flash('Only admin can import data.', 'danger')
        return redirect(url_for('backup.index'))

    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('No file selected.', 'warning')
            return redirect(url_for('backup.import_excel'))

        f = request.files['excel_file']
        if not f.filename or not f.filename.lower().endswith('.xlsx'):
            flash('Please upload a valid .xlsx file.', 'warning')
            return redirect(url_for('backup.import_excel'))

        # Save to temp
        tmp_path = os.path.join(Config.BACKUP_FOLDER, f'import_tmp_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
        os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
        f.save(tmp_path)

        try:
            inserted, updated, skipped, errors = _import_excel(tmp_path)
            if errors:
                for err in errors[:5]:
                    flash(f'Row error: {err}', 'warning')
                if len(errors) > 5:
                    flash(f'… and {len(errors)-5} more row errors.', 'warning')
            audit_log.record('EXCEL_IMPORTED', entity_type='excel_import', entity_id=f.filename,
                              new_value=f'inserted={inserted}, updated={updated}, skipped={skipped}')
            flash(f'Import complete — {inserted} inserted, {updated} updated, {skipped} skipped.', 'success')
        except Exception as exc:
            flash(f'Import failed: {exc}', 'danger')
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return redirect(url_for('loans.index'))

    return render_template('backup/import_excel.html')


@backup_bp.route('/restore/<backup_id>', methods=['POST'])
@login_required
def restore(backup_id):
    if not current_user.is_admin:
        flash('Only admin can restore backups.', 'danger')
        return redirect(url_for('backup.index'))

    b = one("SELECT * FROM backups WHERE backup_id=?", (backup_id,))
    if not b or not os.path.exists(b.get('file_path', '')):
        flash('Backup file not found.', 'danger')
        return redirect(url_for('backup.index'))

    try:
        import json
        with zipfile.ZipFile(b['file_path'], 'r') as zf:
            json_names = [n for n in zf.namelist() if n.endswith('.json')]
            if not json_names:
                flash('No JSON snapshot found in backup.', 'danger')
                return redirect(url_for('backup.index'))
            raw = zf.read(json_names[0]).decode('utf-8')

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('Backup JSON must contain an object of table snapshots.')

        prepared = {}
        for tbl in TABLES:
            rows = payload.get(tbl, [])
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError(f'Invalid snapshot for table {tbl}.')
            allowed = {c.name for c in metadata.tables[tbl].columns}
            for row in rows:
                unknown = set(row) - allowed
                if unknown:
                    raise ValueError(f'Unknown columns in {tbl}: {sorted(unknown)}')
            prepared[tbl] = rows

        # All validation happens before the first DELETE. The savepoint also
        # rolls back every restore statement if any insert fails, preventing
        # the old DELETE-then-INSERT path from leaving a partial database.
        with transaction():
            for tbl in TABLES:
                rows = prepared[tbl]
                run(f"DELETE FROM {tbl}")
                if not rows:
                    continue
                cols = list(rows[0].keys())
                if not cols:
                    continue
                col_list = ', '.join(cols)
                placeholders = ', '.join('?' * len(cols))
                for r in rows:
                    run(f"INSERT INTO {tbl} ({col_list}) VALUES ({placeholders})",
                        tuple(r.get(c) for c in cols))
        audit_log.record('BACKUP_RESTORED', entity_type='backup', entity_id=backup_id)
        flash('Database restored successfully!', 'success')
    except Exception as exc:
        flash(f'Restore failed: {exc}', 'danger')

    return redirect(url_for('backup.index'))
