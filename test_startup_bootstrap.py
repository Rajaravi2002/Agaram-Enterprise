import os
import tempfile
import unittest

from werkzeug.security import check_password_hash


class TestStartupBootstrap(unittest.TestCase):
    def setUp(self):
        self.db_path = tempfile.mktemp(prefix='agaram_startup_', suffix='.db')
        os.environ['SECRET_KEY'] = 'startup-test-secret'
        os.environ['DATABASE_URL'] = 'sqlite:///' + self.db_path
        os.environ['APP_ENV'] = 'testing'
        os.environ['ADMIN_USERNAME'] = 'bootstrap-admin'
        os.environ['ADMIN_PASSWORD'] = 'bootstrap-password-123'
        os.environ['ADMIN_FULL_NAME'] = 'Bootstrap Admin'
        os.environ['ADMIN_EMAIL'] = 'admin@example.test'
        # Config values are class attributes evaluated on first import. Keep
        # this test isolated when pytest has already imported another module.
        from config import Config
        Config.SECRET_KEY = os.environ['SECRET_KEY']
        Config.DATABASE_URL = os.environ['DATABASE_URL']
        Config.APP_ENV = os.environ['APP_ENV']

    def tearDown(self):
        for key in ('SECRET_KEY', 'DATABASE_URL', 'APP_ENV', 'ADMIN_USERNAME',
                    'ADMIN_PASSWORD', 'ADMIN_FULL_NAME', 'ADMIN_EMAIL'):
            os.environ.pop(key, None)
        for suffix in ('', '-shm', '-wal'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_fresh_database_is_ready_for_login_and_restart_is_idempotent(self):
        from app import create_app
        from database import one

        app = create_app()
        with app.app_context():
            user = one('SELECT * FROM users WHERE username=?', ('bootstrap-admin',))
            self.assertIsNotNone(user)
            self.assertEqual(user['full_name'], 'Bootstrap Admin')
            self.assertTrue(check_password_hash(user['password_hash'], 'bootstrap-password-123'))

        restarted_app = create_app()
        restarted_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with restarted_app.app_context():
            users = one('SELECT COUNT(*) AS count FROM users')
            user = one('SELECT * FROM users WHERE username=?', ('bootstrap-admin',))
            self.assertEqual(users['count'], 1)
            self.assertTrue(check_password_hash(user['password_hash'], 'bootstrap-password-123'))

        response = restarted_app.test_client().post('/login', data={
            'username': 'bootstrap-admin',
            'password': 'bootstrap-password-123',
        })
        self.assertEqual(response.status_code, 302)


if __name__ == '__main__':
    unittest.main()
