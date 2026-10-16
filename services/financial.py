"""
services/financial.py – Single source of truth for Agaram Finance's
loan-math formulas.

Updated Formula:
  Interest = Loan Amount x Rate% x Tenure (Months)
  Agreement Value = Loan Amount + Interest Amount
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


def interest_amount_from_rate(loan_amount: float, rate_pct: float, tenure_months: int) -> float:
    """interest = loan_amount x rate% x tenure (flat monthly rate)."""
    if tenure_months <= 0:
        return 0.0
    return round2(_d(loan_amount) * (_d(rate_pct) / 100) * tenure_months)


def rate_from_interest_amount(interest_amount: float, loan_amount: float, tenure_months: int) -> float:
    """Derives interest rate % from interest amount based on total loan_amount."""
    if loan_amount <= 0 or tenure_months <= 0:
        return 0.0
    return round2(_d(interest_amount) / (_d(loan_amount) * tenure_months) * 100)


def agreement_value(loan_amount: float, interest_amt: float) -> float:
    """Agreement Value = Loan Amount + Interest Amount."""
    return round2(_d(loan_amount) + _d(interest_amt))


def monthly_due(agreement: float, tenure_months: int) -> float:
    """Applied everywhere -- loan creation, the AJAX preview, and top-ups."""
    if tenure_months <= 0:
        return 0.0
    if ROUND_DUE_UP:
        return float(math.ceil(float(agreement) / tenure_months))
    return round2(_d(agreement) / tenure_months)


def split_principal_interest(agreement_val: float, principle: float, amount: float):
    """Proportionally allocate a payment between principal and interest."""
    agreement_val = float(agreement_val or 0)
    if agreement_val <= 0:
        return round2(amount), 0.0
    ratio = float(principle) / agreement_val
    principal_part = round2(_d(amount) * _d(ratio))
    interest_part = round2(_d(amount) - _d(principal_part))
    return principal_part, interest_part


def compute_loan_fields(loan_amount: float, document_charge: float,
                         interest_amount: float, tenure_months: int) -> dict:
    """Turns (loan_amount, document_charge, interest_amount, tenure) into derived fields."""
    principle = principle_amount(loan_amount, document_charge)
    rate = rate_from_interest_amount(interest_amount, loan_amount, tenure_months)
    agreement = agreement_value(loan_amount, interest_amount)
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
    """AJAX preview calculator & top-ups using Loan Amount * Rate% * Months."""
    principle = principle_amount(loan_amount, document_charge)
    interest_amt = interest_amount_from_rate(loan_amount, rate_pct, tenure_months)
    agreement = agreement_value(loan_amount, interest_amt)
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