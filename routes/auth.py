from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from urllib.parse import urlparse
from app import login_manager
from database import one, run
from services import audit_log

auth_bp = Blueprint('auth', __name__)

# ── Basic in-process login lockout ──────────────────────────────────────────
# NOTE: this dict lives in one Gunicorn worker's memory only. With
# `-w 3` workers, an attacker can get 3x the attempts by hitting
# different workers, and the counters reset on every deploy/restart.
# The real defense is deploy/nginx.conf's `limit_req zone=login` (see
# Stage 1) plus, ideally, Flask-Limiter with a shared Redis backend for
# anything beyond a single-worker deployment. This in-process check is
# a cheap second layer, not a substitute for either.
_failed_attempts = {}   # username -> [timestamps]
MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)


def _is_locked_out(username: str) -> bool:
    attempts = _failed_attempts.get(username, [])
    cutoff = datetime.now() - LOCKOUT_WINDOW
    attempts = [t for t in attempts if t > cutoff]
    _failed_attempts[username] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def _record_failed_attempt(username: str):
    _failed_attempts.setdefault(username, []).append(datetime.now())


def _clear_attempts(username: str):
    _failed_attempts.pop(username, None)


def _safe_next_url(target: str) -> str:
    """Only ever redirect to a path on this same site (audit item 16 —
    open redirect). `next=https://evil.example.com` or a
    protocol-relative `next=//evil.example.com` is rejected."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.netloc or parsed.scheme:
        return None
    if not target.startswith('/') or target.startswith('//'):
        return None
    return target


# ── User model for Flask-Login ────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, row):
        self.id            = str(row['id'])
        self.username      = row['username']
        self.role          = row['role']
        self.full_name     = row['full_name']
        self._is_active    = bool(row['is_active'])
        self.must_change_password = bool(row.get('must_change_password'))

    def get_id(self):        return self.id
    @property
    def is_active(self):     return self._is_active
    @property
    def is_admin(self):      return self.role == 'admin'


@login_manager.user_loader
def load_user(user_id):
    row = one("SELECT * FROM users WHERE id = ?", (user_id,))
    return User(row) if row else None


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/',      methods=['GET'])
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        if _is_locked_out(username):
            flash('Too many failed attempts. Please wait 15 minutes and try again.', 'danger')
            return render_template('auth/login.html')

        row = one("SELECT * FROM users WHERE username = ? AND is_active = 1",
                  (username,))
        if row and check_password_hash(row['password_hash'], password):
            _clear_attempts(username)
            user = User(row)
            login_user(user, remember=remember)
            run("UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(timespec='seconds'), row['id']))
            audit_log.record('LOGIN', entity_type='user', entity_id=username)
            flash(f'Welcome back, {user.full_name}!', 'success')

            if user.must_change_password:
                flash('Please change your password before continuing.', 'warning')
                return redirect(url_for('auth.change_password'))

            nxt = _safe_next_url(request.args.get('next'))
            return redirect(nxt or url_for('dashboard.index'))

        _record_failed_attempt(username)
        audit_log.record('LOGIN_FAILED', entity_type='user', entity_id=username, username=username)
        flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    audit_log.record('LOGOUT', entity_type='user', entity_id=current_user.username)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw     = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        row = one("SELECT * FROM users WHERE id=?", (current_user.id,))
        if not row or not check_password_hash(row['password_hash'], current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('auth/change_password.html')
        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'danger')
            return render_template('auth/change_password.html')
        if len(new_pw) < 12:
            flash('New password must be at least 12 characters.', 'danger')
            return render_template('auth/change_password.html')

        from werkzeug.security import generate_password_hash
        run("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
            (generate_password_hash(new_pw), current_user.id))
        flash('Password changed successfully.', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')

