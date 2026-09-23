"""
services/financial.py – Single source of truth for Agaram Finance's
loan-math formulas (audit items 9 & 10).

Before this stage there were TWO different formulas doing the same
job, in different files, that disagreed with each other:

  routes/loans.py  (saved on create/edit):
      rate  = interest_amount / (loan_amount * tenure) * 100
      due   = ceil(agreement / tenure)

  routes/loans.py `/calculate` AJAX preview:
      interest_amount = principle * rate * tenure / 100
      due             = round(agreement / tenure, 2)

Both the base (loan_amount vs. principle) and the rounding rule
(ceil vs. round) disagreed, so the live preview a staff member saw
while filling the form did not necessarily match what got saved.

This module is now the ONLY place either formula is written down.
Both are on `principle` (money actually disbursed after the document
charge is deducted, which is what interest should accrue on), and
`monthly_due` always rounds UP to the nearest rupee — a lender should
never come up short by rounding, and now there's one switch instead
of two divergent formulas. If a different rounding rule turns out to
be the actual business rule, change ROUND_DUE_UP here — nowhere else.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal('0.01')
ROUND_DUE_UP = True  # ceil() when True; round-to-nearest when False


def _d(value) -> Decimal:
    return Decimal(str(value))


def round2(value) -> float:
    return float(_d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def principle_amount(loan_amount: float, document_charge: float) -> float:
    return round2(_d(loan_amount) - _d(document_charge))


def interest_amount_from_rate(principle: float, rate_pct: float, tenure_months: int) -> float:
    """interest = principle x rate% x tenure   (flat monthly rate)."""
    if tenure_months <= 0:
        return 0.0
    return round2(_d(principle) * (_d(rate_pct) / 100) * tenure_months)


def rate_from_interest_amount(interest_amount: float, principle: float, tenure_months: int) -> float:
    """Inverse of interest_amount_from_rate -- the ONLY formula used to
    derive a displayed interest rate % from a user-entered interest
    amount, everywhere in the app."""
    if principle <= 0 or tenure_months <= 0:
        return 0.0
    return round2(_d(interest_amount) / (_d(principle) * tenure_months) * 100)


def agreement_value(principle: float, interest_amt: float) -> float:
    return round2(_d(principle) + _d(interest_amt))


def monthly_due(agreement: float, tenure_months: int) -> float:
    """Applied everywhere -- loan creation, the AJAX preview, and
    top-ups -- so the screen and the saved loan always agree."""
    if tenure_months <= 0:
        return 0.0
    if ROUND_DUE_UP:
        return float(math.ceil(float(agreement) / tenure_months))
    return round2(_d(agreement) / tenure_months)


def split_principal_interest(agreement_val: float, principle: float, amount: float):
    """Proportionally allocate a payment between principal and interest
    based on the loan's principal:agreement ratio. Always sums exactly
    to `amount` (no rounding drift)."""
    agreement_val = float(agreement_val or 0)
    if agreement_val <= 0:
        return round2(amount), 0.0
    ratio = float(principle) / agreement_val
    principal_part = round2(_d(amount) * _d(ratio))
    interest_part = round2(_d(amount) - _d(principal_part))
    return principal_part, interest_part


def compute_loan_fields(loan_amount: float, document_charge: float,
                         interest_amount: float, tenure_months: int) -> dict:
    """The one function that turns (loan_amount, document_charge,
    interest_amount, tenure) -- what the create/edit forms submit --
    into every derived financial field on a loan."""
    principle = principle_amount(loan_amount, document_charge)
    rate = rate_from_interest_amount(interest_amount, principle, tenure_months)
    agreement = agreement_value(principle, interest_amount)
    due = monthly_due(agreement, tenure_months)
    return dict(
        loan_amount=round2(loan_amount),
        document_charge=round2(document_charge),
        principle_amount=principle,
        interest_amount=round2(interest_amount),
        interest_rate=rate,
        int_pct=f"{rate:.2f}%",
        agreement_value=agreement,
        tenure=tenure_months,
        due_amount=due,
    )


def compute_loan_fields_from_rate(loan_amount: float, document_charge: float,
                                   rate_pct: float, tenure_months: int) -> dict:
    """Same as compute_loan_fields but for flows where the rate is the
    input and the interest amount is derived -- the AJAX preview
    calculator, and top-ups (which keep the loan's existing rate)."""
    principle = principle_amount(loan_amount, document_charge)
    interest_amt = interest_amount_from_rate(principle, rate_pct, tenure_months)
    agreement = agreement_value(principle, interest_amt)
    due = monthly_due(agreement, tenure_months)
    return dict(
        loan_amount=round2(loan_amount),
        document_charge=round2(document_charge),
        principle_amount=principle,
        interest_amount=interest_amt,
        interest_rate=round2(rate_pct),
        int_pct=f"{float(rate_pct):.2f}%",
        agreement_value=agreement,
        tenure=tenure_months,
        due_amount=due,
    )
