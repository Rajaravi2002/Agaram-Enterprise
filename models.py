"""
models.py  –  Pure business-logic helpers (no DB calls).
              ID generation now lives in database.py.
"""

def calculate_loan(loan_amount, interest_rate, duration_months):
    """Simple Interest:  SI = P * R * T / 1200"""
    total_interest = (loan_amount * interest_rate * duration_months) / 1200
    total_payable  = loan_amount + total_interest
    monthly_emi    = total_payable / duration_months
    return round(total_interest, 2), round(total_payable, 2), round(monthly_emi, 2)
