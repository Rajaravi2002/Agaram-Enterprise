"""
config.py – Production configuration for Agaram Finance.

All secrets and environment-specific values come from environment
variables. There are NO hard-coded fallbacks for anything security
sensitive: if SECRET_KEY or DATABASE_URL is missing, the app refuses
to start rather than silently running with a known/guessable value.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in, or set it "
            f"in your process manager / systemd unit."
        )
    return val


class Config:
    APP_ENV = os.environ.get('APP_ENV', 'development')

    # ── Secrets / DB — no insecure fallback ─────────────────────────────
    SECRET_KEY   = _require('SECRET_KEY')
    DATABASE_URL = _require('DATABASE_URL')  # e.g. postgresql+psycopg://user:pass@host/db

    # ── Session hardening ────────────────────────────────────────────────
    SESSION_COOKIE_SECURE   = APP_ENV == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # ── Uploads ──────────────────────────────────────────────────────────
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_MB', '10')) * 1024 * 1024

    # ── App folders ──────────────────────────────────────────────────────
    BACKUP_FOLDER  = os.environ.get('BACKUP_FOLDER',  os.path.join(BASE_DIR, 'backups'))
    REPORTS_FOLDER = os.environ.get('REPORTS_FOLDER', os.path.join(BASE_DIR, 'reports'))
    BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))

    # ── CSRF (Flask-WTF) ─────────────────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # tokens valid for the whole session

    @staticmethod
    def init_app(app):
        os.makedirs(Config.BACKUP_FOLDER,  exist_ok=True)
        os.makedirs(Config.REPORTS_FOLDER, exist_ok=True)

        if Config.APP_ENV == 'production' and not Config.DATABASE_URL.startswith(
            ('postgresql://', 'postgresql+psycopg://', 'postgresql+psycopg2://')
        ):
            raise RuntimeError(
                'APP_ENV=production requires a PostgreSQL DATABASE_URL. '
                'SQLite is for local development only.'
            )
