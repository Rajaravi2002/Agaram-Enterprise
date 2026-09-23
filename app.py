from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from config import Config

login_manager = LoginManager()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.init_app(app)

    # ── Database engine + per-request transaction ───────────────────────
    from database import init_engine, close_db
    init_engine(app)
    app.teardown_appcontext(close_db)
    # NOTE: schema creation is explicit now — run `flask init-db` once
    # during deployment (see manage.py / README). It is deliberately NOT
    # run automatically here, so that a multi-worker Gunicorn boot doesn't
    # race N workers against the schema at once (audit item 11).

    # ── Flask-Login ───────────────────────────────────────────────────────
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    # ── CSRF protection ──────────────────────────────────────────────────
    # All 13 POST templates now carry {{ csrf_token() }} (Stage 3), so
    # this is safe to enable.
    csrf.init_app(app)

    # ── Blueprints ────────────────────────────────────────────────────────
    from routes.auth      import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.customers import customers_bp
    from routes.loans     import loans_bp
    from routes.payments  import payments_bp
    from routes.reports   import reports_bp
    from routes.backup     import backup_bp
    from routes.settlement import settlement_bp
    from routes.api       import api_bp

    for bp in (auth_bp, dashboard_bp, customers_bp, loans_bp,
               payments_bp, reports_bp, backup_bp, api_bp, settlement_bp):
        app.register_blueprint(bp)

    # ── CLI commands (schema init, admin creation) ──────────────────────
    from manage import register_cli
    register_cli(app)

    # ── Error handlers — never leak tracebacks/SQL/paths to users ───────
    for code in (400, 403, 404, 413, 429, 500):
        app.register_error_handler(code, _make_error_handler(code))

    # NOTE: the old in-process background scheduler (scheduler.py) has been
    # removed on purpose. Running a Python thread inside a Gunicorn worker
    # means N workers each run their own backup thread (audit item 12).
    # Automatic backups are now a systemd timer / cron job calling
    # deploy/backup.sh — see MIGRATION_NOTES.md.

    # ── Security headers ─────────────────────────────────────────────────
    # Transport-layer headers (HSTS) belong in Nginx (see deploy/nginx.conf)
    # since Nginx terminates TLS; these apply regardless of what's in front.
    @app.after_request
    def _security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    return app


def _make_error_handler(code):
    def _handler(e):
        return render_template(f'errors/{code}.html'), code
    return _handler
