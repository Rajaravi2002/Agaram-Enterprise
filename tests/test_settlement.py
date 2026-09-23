"""
tests/test_settlement.py – Scenarios the production audit asked for
(item 22): 0 months paid, 1 month paid, advance payment, overdue
payment, fully paid loan, expired tenure, settlement on/after the
tenure end date.

Run with:  python -m unittest tests.test_settlement -v
"""
import unittest
from datetime import date, timedelta

from services.settlement_service import calc_settlement, months_between


def make_loan(loan_date, tenure=12, loan_amount=24000.0, due_amount=2000.0,
              paid_due=0, interest_amount=6000.0, balance_agreement=None,
              loan_id='AGM0001'):
    return {
        'loan_id': loan_id,
        'customer_name': 'Test Customer',
        'loan_date': loan_date.isoformat() if isinstance(loan_date, date) else loan_date,
        'tenure': tenure,
        'loan_amount': loan_amount,
        'due_amount': due_amount,
        'paid_due': paid_due,
        'interest_amount': interest_amount,
        'balance_agreement': balance_agreement if balance_agreement is not None else loan_amount + interest_amount,
    }


class TestSettlementScenarios(unittest.TestCase):

    def test_zero_months_paid_settlement_covers_full_tenure(self):
        """No payments made at all, settling right after the loan date."""
        loan = make_loan(loan_date=date.today(), paid_due=0)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertEqual(result['completed_months'], 0)
        self.assertEqual(result['future_due_count'], 12)
        self.assertEqual(result['overdue_count'], 0)
        self.assertGreater(result['settlement_amount'], 0)

    def test_one_month_paid_on_time(self):
        loan_date = date.today() - timedelta(days=31)
        loan = make_loan(loan_date=loan_date, paid_due=1)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertEqual(result['completed_months'], 1)
        self.assertEqual(result['overdue_count'], 0)  # paid up to date
        self.assertEqual(result['future_due_count'], 11)

    def test_advance_payment_reduces_future_dues(self):
        """Customer paid 3 months but only 1 month has actually elapsed --
        the extra 2 are advance dues, not future dues to be settled."""
        loan_date = date.today() - timedelta(days=31)
        loan = make_loan(loan_date=loan_date, paid_due=3)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertEqual(result['completed_months'], 1)
        self.assertEqual(result['advance_dues'], 2)
        self.assertEqual(result['future_due_count'], 12 - 1 - 2)
        self.assertEqual(result['overdue_count'], 0)

    def test_overdue_payment_adds_overdue_amount(self):
        """3 months have elapsed but customer only paid 1 -- 2 months
        are overdue and must be charged in full, on top of future dues."""
        loan_date = date.today() - timedelta(days=95)  # ~3 months elapsed
        loan = make_loan(loan_date=loan_date, paid_due=1)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertGreaterEqual(result['completed_months'], 3)
        self.assertEqual(result['overdue_count'], result['completed_months'] - 1)
        self.assertGreater(result['total_overdue'], 0)

    def test_fully_paid_loan_settles_to_zero(self):
        """All 12 months already paid -- nothing left to settle."""
        loan_date = date.today() - timedelta(days=365)
        loan = make_loan(loan_date=loan_date, paid_due=12)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertEqual(result['future_due_count'], 0)
        self.assertEqual(result['settlement_amount'], 0)

    def test_expired_tenure_caps_completed_months_at_tenure(self):
        """Loan is well past its tenure end date -- completed_months
        must cap at tenure, not keep growing forever."""
        loan_date = date.today() - timedelta(days=800)  # ~26 months, tenure=12
        loan = make_loan(loan_date=loan_date, tenure=12, paid_due=6)
        result = calc_settlement(loan, as_of_date=date.today())
        self.assertEqual(result['completed_months'], 12)
        self.assertEqual(result['future_due_count'], 0)

    def test_settlement_on_exact_tenure_end_date(self):
        loan_date = date.today().replace(day=1) - timedelta(days=365)
        loan = make_loan(loan_date=loan_date, tenure=12, paid_due=12)
        as_of = loan_date.replace(year=loan_date.year + 1)
        result = calc_settlement(loan, as_of_date=as_of.isoformat())
        self.assertLessEqual(result['completed_months'], 12)

    def test_months_between_helper(self):
        self.assertEqual(months_between(date(2026, 1, 1), date(2026, 4, 1)), 3)
        self.assertEqual(months_between(None, date.today()), 0)
        self.assertEqual(months_between(date.today(), None), 0)


if __name__ == '__main__':
    unittest.main()
