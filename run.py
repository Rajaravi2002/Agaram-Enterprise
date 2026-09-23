"""
run.py – WSGI entrypoint.

Production:   gunicorn -w 3 -b 127.0.0.1:8000 run:app   (behind Nginx)
Local dev:    flask --app run --debug run
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Convenience only — do not use this for production. Bind to
    # localhost, not 0.0.0.0, and let Nginx + Gunicorn handle the
    # internet-facing side.
    app.run(host='127.0.0.1', port=5000, debug=(app.config['APP_ENV'] != 'production'))
