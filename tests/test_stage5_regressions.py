"""Regression tests for Stage 5 import and restore workflows."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime

os.environ.setdefault('SECRET_KEY', 'stage5-regression-secret')
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(prefix='stage5_regression_', suffix='.db')
os.environ['APP_ENV'] = 'testing'
os.environ['BACKUP_FOLDER'] = tempfile.mkdtemp(prefix='stage5_regression_backups_')
os.environ['REPORTS_FOLDER'] = tempfile.mkdtemp(prefix='stage5_regression_reports_')

from app import create_app
from database import create_schema, users, customers, loans, backups, one
from routes.backup import _import_excel
from services.loan_service import create_loan
from werkzeug.security import generate_password_hash


class TestStage5Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import openpyxl
        cls.openpyxl = openpyxl
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        create_schema(cls.app)
        with cls.app.db_engine.begin() as conn:
            conn.execute(users.insert().values(
                username='stage5-admin',
                password_hash=generate_password_hash('stage5-password-123'),
                role='admin', full_name='Stage 5 Admin', email='',
                is_active=True, must_change_password=False,
                created_at=datetime.now(),
            ))

    def setUp(self):
        self.client = self.app.test_client()

    def _workbook(self, rows):
        wb = self.openpyxl.Workbook()
        ws = wb.active
        headers = ['Sl.No', 'Loan No', 'Loan Date', 'Name', 'Mobile', 'Ref',
                   'Due Date', 'Follower', 'Loan Amount', 'Document Charge',
                   'Princple Amount', 'Interst Amount', 'Agrement Value',
                   'Tenure', 'Due Amount', 'Paid Due', 'Paid Amount',
                   'Feature Dues', 'Balance Aggrement Amount', 'int %',
                   'Vehicle Model', 'Vehicle Number', 'Document Status', 'Remarks']
        ws.append(headers)
        for row in rows:
            ws.append(row)
        path = tempfile.mktemp(suffix='.xlsx')
        wb.save(path)
        return path

    def test_excel_import_inserts_then_updates_without_replace(self):
        row = [1, 'AGM9001', '2026-01-01', 'Imported Customer', '123', '', '', '',
               10000, 500, 9500, 1200, 10700, 12, 892, 0, 0, 12, 10700,
               '1.05%', '', '', '', '']
        path = self._workbook([row])
        with self.app.app_context():
            self.assertEqual(_import_excel(path)[:3], (1, 0, 0))
            self.assertEqual(_import_excel(path)[:3], (0, 1, 0))
            self.assertEqual(one('SELECT customer_name FROM loans WHERE loan_id=?', ('AGM9001',))['customer_name'], 'Imported Customer')

    def test_excel_import_rejects_missing_name_and_zero_tenure(self):
        missing_name = [1, 'AGM9002', '2026-01-01', '', '123', '', '', '',
                        10000, 500, 9500, 1200, 10700, 12, 892, 0, 0, 12, 10700,
                        '1.05%', '', '', '', '']
        zero_tenure = [1, 'AGM9003', '2026-01-01', 'Bad Tenure', '123', '', '', '',
                       10000, 500, 9500, 1200, 10700, 0, 0, 0, 0, 0, 10700,
                       '1.05%', '', '', '', '']
        path = self._workbook([missing_name, zero_tenure])
        with self.app.app_context():
            inserted, updated, skipped, errors = _import_excel(path)
            self.assertEqual((inserted, updated, skipped), (0, 0, 2))
            self.assertEqual(len(errors), 2)
            self.assertIsNone(one('SELECT id FROM loans WHERE loan_id=?', ('AGM9002',)))
            self.assertIsNone(one('SELECT id FROM loans WHERE loan_id=?', ('AGM9003',)))

    def test_restore_failure_rolls_back_all_deletes(self):
        with self.app.app_context():
            create_loan({'customer_name': 'Existing', 'loan_amount': '1000',
                         'document_charge': '0', 'interest_amount': '100',
                         'tenure': '10', 'loan_date': '2026-01-01'}, 'stage5-admin')
        with self.app.app_context():
            payload = {'users': [], 'customers': [], 'loans': [{
                'loan_id': 'AGM-BAD', 'customer_name': 'Bad',
                'unexpected_column': 'must be rejected',
            }], 'payments': []}
            backup_path = tempfile.mktemp(suffix='.zip')
            with zipfile.ZipFile(backup_path, 'w') as zf:
                zf.writestr('snapshot.json', json.dumps(payload))
            with self.app.db_engine.begin() as conn:
                conn.execute(backups.insert().values(
                    backup_id='BAK-ROLLBACK', backup_type='manual',
                    file_path=backup_path, file_name='snapshot.zip', file_size=1,
                    created_at=datetime.now(), created_by='stage5-admin', status='success'))

        self.assertEqual(self.client.post('/login', data={
            'username': 'stage5-admin', 'password': 'stage5-password-123',
        }).status_code, 302)
        response = self.client.post('/backup/restore/BAK-ROLLBACK')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(one("SELECT id FROM loans WHERE customer_name=?", ('Existing',)))


if __name__ == '__main__':
    unittest.main()
