"""
manage.py – One-off administrative CLI commands.

Usage (after activating your venv and setting env vars / .env):

    flask --app run init-db
    flask --app run create-admin
"""
import getpass
from datetime import datetime

import click
from werkzeug.security import generate_password_hash


def register_cli(app):

    @app.cli.command('init-db')
    def init_db_cmd():
        """Create all tables (and sequences on Postgres) if they don't exist.
        Safe to re-run — uses CREATE TABLE IF NOT EXISTS semantics."""
        from database import create_schema
        create_schema(app)
        click.echo('Schema created / verified.')

    @app.cli.command('create-admin')
    @click.option('--username', prompt=True)
    @click.option('--full-name', prompt='Full name')
    @click.option('--email', prompt=True, default='')
    def create_admin_cmd(username, full_name, email):
        """Interactively create an admin user with a password you choose
        (never a known default). Replaces the old auto-seeded admin123
        account."""
        from database import users
        from sqlalchemy import select

        # Use the engine directly (not the per-request g.db wrapper) since
        # this runs outside a normal Flask request lifecycle.
        with app.db_engine.begin() as conn:
            existing = conn.execute(
                select(users.c.id).where(users.c.username == username)
            ).fetchone()
            if existing:
                click.echo(f'User "{username}" already exists. Aborting.')
                return

            password = getpass.getpass('Password: ')
            confirm  = getpass.getpass('Confirm password: ')
            if password != confirm:
                click.echo('Passwords did not match. Aborting.')
                return
            if len(password) < 12:
                click.echo('Password must be at least 12 characters. Aborting.')
                return

            conn.execute(users.insert().values(
                username=username,
                password_hash=generate_password_hash(password),
                role='admin',
                full_name=full_name,
                email=email,
                is_active=True,
                must_change_password=False,
                created_at=datetime.now(),
            ))
            click.echo(f'Admin user "{username}" created.')
