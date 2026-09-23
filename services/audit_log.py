"""
services/audit_log.py – Write-only audit trail (audit item 17).

Call `record()` after any state-changing action a finance company
would want to be able to answer "who did this and when" about. Reads
`flask_login.current_user` and `flask.request` automatically when not
given explicitly, so most call sites just do:

    audit_log.record('LOAN_CREATED', entity_type='loan', entity_id=loan_id,
                      new_value=f'agreement={agreement_value}')
"""
from datetime import datetime

from database import run

ACTIONS = {
    'LOGIN', 'LOGIN_FAILED', 'LOGOUT',
    'CUSTOMER_CREATED', 'CUSTOMER_EDITED', 'CUSTOMER_DEACTIVATED',
    'LOAN_CREATED', 'LOAN_EDITED', 'LOAN_TOPUP',
    'PAYMENT_COLLECTED', 'SETTLEMENT_COLLECTED', 'LOAN_CLOSED',
    'PENALTY_UPDATED', 'BACKUP_CREATED', 'BACKUP_RESTORED', 'EXCEL_IMPORTED',
}


def record(action: str, entity_type: str = '', entity_id: str = '',
           old_value: str = '', new_value: str = '', username: str = None) -> None:
    if action not in ACTIONS:
        raise ValueError(f'Unknown audit action: {action}')

    user_id = None
    uname = username
    if uname is None:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                uname = current_user.username
                user_id = int(current_user.id)
        except Exception:
            uname = ''

    ip = ''
    try:
        from flask import request as flask_request
        ip = flask_request.remote_addr or ''
    except Exception:
        pass

    run("""INSERT INTO audit_logs
           (user_id, username, action, entity_type, entity_id, old_value, new_value, ip_address, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, uname or '', action, entity_type, entity_id,
         old_value or '', new_value or '', ip,
         datetime.now().isoformat(timespec='seconds')))
