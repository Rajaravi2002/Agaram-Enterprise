"""
tests/test_financial.py – Proves the two formulas that used to
disagree (audit items 9 & 10) are now true inverses of each other and
applied consistently everywhere.

Run with:  python -m unittest tests.test_financial -v
"""
import unittest

from services.financial import (
    compute_loan_fields, compute_loan_fields_from_rate,
    interest_amount_from_rate, rate_from_interest_amount,
    monthly_due, split_principal_interest,
)


class TestRateInterestAreInverses(unittest.TestCase):
    def test_rate_to_amount_to_rate_round_trips(self):
        principle, rate, tenure = 22500.0, 2.25, 12
        amt = interest_amount_from_rate(principle, rate, tenure)
        back = rate_from_interest_amount(amt, principle, tenure)
        self.assertAlmostEqual(back, rate, places=1)

    def test_create_and_preview_paths_agree(self):
        """The AJAX preview (rate -> amount) and the actual save path
        (amount -> rate) must land on the same loan for the same inputs
        -- this was the exact bug in the old code."""
        loan_amount, doc_charge, rate, tenure = 25000.0, 2500.0, 2.25, 12

        preview = compute_loan_fields_from_rate(loan_amount, doc_charge, rate, tenure)
        # Staff then submits the previewed interest_amount as the real form value.
        saved = compute_loan_fields(loan_amount, doc_charge, preview['interest_amount'], tenure)

        self.assertEqual(preview['agreement_value'], saved['agreement_value'])
        self.assertEqual(preview['due_amount'], saved['due_amount'])
        self.assertAlmostEqual(preview['interest_rate'], saved['interest_rate'], places=1)

    def test_zero_tenure_does_not_divide_by_zero(self):
        self.assertEqual(rate_from_interest_amount(1000, 20000, 0), 0.0)
        self.assertEqual(interest_amount_from_rate(20000, 2.0, 0), 0.0)
        self.assertEqual(monthly_due(24000, 0), 0.0)


class TestMonthlyDueRounding(unittest.TestCase):
    def test_rounds_up_not_down(self):
        # 52000 / 12 = 4333.33... -> must round UP to 4334, never down.
        self.assertEqual(monthly_due(52000, 12), 4334.0)

    def test_exact_division_unchanged(self):
        self.assertEqual(monthly_due(24000, 12), 2000.0)


class TestPrincipalInterestSplit(unittest.TestCase):
    def test_split_sums_exactly_to_amount(self):
        agreement, principle, amount = 29300.0, 22500.0, 2441.67
        p, i = split_principal_interest(agreement, principle, amount)
        self.assertAlmostEqual(p + i, amount, places=2)

    def test_zero_agreement_all_principal(self):
        p, i = split_principal_interest(0, 0, 500)
        self.assertEqual((p, i), (500.0, 0.0))


if __name__ == '__main__':
    unittest.main()
