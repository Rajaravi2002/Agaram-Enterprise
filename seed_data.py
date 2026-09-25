"""seed_data.py – populate database with realistic sample data and custom admin.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from dateutil.relativedelta import relativedelta
import random
from werkzeug.security import generate_password_hash

from app import create_app
from database import run, query, next_loan_id, next_payment_id

app = create_app()

SAMPLE = [
    dict(name="Sample Customer A", phone="9000000001", loan_amount=25000, doc_charge=2500, interest=6800, tenure=12, int_pct="2.25", vehicle="Hero SPL+ / 2018-19",   vnum="TN95B0001",  doc_status="Collected",  ref="",      follower="Staff1",  payments_made=12),
    dict(name="Sample Customer B", phone="9000000002", loan_amount=33500, doc_charge=3350, interest=9100, tenure=12, int_pct="2.25", vehicle="Hero SPL+ / 2019",     vnum="TN67B0002", doc_status="Collected",  ref="",      follower="Staff2", payments_made=12),
    dict(name="Sample Customer C", phone="9000000003", loan_amount=36000, doc_charge=3600, interest=13810,tenure=17, int_pct="2.25", vehicle="TVS XL100 / 2021",     vnum="TN95E0003",  doc_status="Collected",  ref="",      follower="Staff1",  payments_made=10),
    dict(name="Sample Customer D", phone="9000000004", loan_amount=23000, doc_charge=2300, interest=6280, tenure=12, int_pct="2.25", vehicle="Yamaha SalutoRX",      vnum="TN84J0004",  doc_status="Collected",  ref="",      follower="Staff2", payments_made=8, overdue=True),
    dict(name="Sample Customer E", phone="9000000005", loan_amount=34000, doc_charge=3400, interest=11750,tenure=15, int_pct="2.25", vehicle="Hero SPL+ / 2019",     vnum="TN84H0005",  doc_status="Collected",  ref="",      follower="Staff2", payments_made=15),
]


def seed():
    with app.app_context():
        # Clear existing tables
        run("DELETE FROM payments")
        run("DELETE FROM loans")
        run("DELETE FROM customers")

        # -------------------------------------------------------------
        # ADD CUSTOM ADMIN USER
        # -------------------------------------------------------------
        new_username = "my_new_admin"
        new_password = "MyStrongPassword123!"
        hashed_pw = generate_password_hash(new_password)

        # Ensure users table exists and insert/update custom admin
        run("""
            INSERT INTO users (username, password_hash, role, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash
        """, (new_username, hashed_pw, 'admin', datetime.now().isoformat(timespec='seconds')))
        
        print(f"Custom user '{new_username}' created successfully!")

        # Seed Sample Customers and Loans
        for d in SAMPLE:
            principle  = d['loan_amount'] - d['doc_charge']
            agreement  = principle + d['interest']
            due_amount = round(agreement / d['tenure'], 2)
            loan_date  = datetime.now() - relativedelta(months=d['payments_made'] + 1)
            paid_due   = d['payments_made']
            paid_amt   = due_amount * paid_due
            balance    = round(agreement - paid_amt, 2)
            status     = 'overdue' if d.get('overdue') else ('closed' if balance <= 0 else 'active')

            exists = query("SELECT id FROM customers WHERE name=?", (d['name'],))
            if not exists:
                run(
                    "INSERT INTO customers (name,phone,alt_phone,address,aadhaar,occupation,date_added,added_by,is_active)"
                    " VALUES (?,?,?,?,?,?,?,?,1)",
                    (d['name'], d['phone'], '', '', '', '', datetime.now().isoformat(timespec='seconds'), 'seed'))

            loan_id = next_loan_id()
            run("""INSERT INTO loans
               (loan_id,customer_name,phone,ref,follower,loan_date,due_day,
                loan_amount,document_charge,principle_amount,interest_rate,interest_amount,agreement_value,
                tenure,due_amount,paid_due,paid_amount,feature_dues,balance_agreement,int_pct,
                vehicle_model,vehicle_number,document_status,remarks,
                penalty_amount,penalty_description,topup_history,loan_status,created_at,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (loan_id, d['name'], d['phone'], d.get('ref', ''), d.get('follower', ''),
                 loan_date.strftime('%Y-%m-%d'), '25th',
                 d['loan_amount'], d['doc_charge'], principle,
                 float(d['int_pct'].replace('%', '')) if d.get('int_pct') else 0.0,
                 d['interest'], agreement,
                 d['tenure'], due_amount, paid_due, paid_amt,
                 max(d['tenure'] - paid_due, 0), balance, d['int_pct'],
                 d['vehicle'], d['vnum'], d['doc_status'], '',
                 0, '', '[]', status,
                 loan_date.isoformat(timespec='seconds'), 'seed'))

            carry = 0.0
            for mo in range(1, paid_due + 1):
                pay_date  = loan_date + relativedelta(months=mo)
                total_due = round(due_amount + carry, 2)
                partial   = random.random() < 0.15 and status != 'closed'
                paid      = round(total_due * random.uniform(0.7, 0.9), 2) if partial else total_due
                pending   = round(max(total_due - paid, 0), 2)
                carry     = pending
                pid = next_payment_id()
                run("""INSERT INTO payments
                    (payment_id,loan_id,customer_name,collection_date,
                     emi_amount,carry_forward,total_due,paid_amount,pending_amount,
                     month_number,penalty_amount,collection_remarks,collected_by,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, loan_id, d['name'], pay_date.strftime('%Y-%m-%d'),
                     due_amount, carry, total_due, paid, pending, mo,
                     0, 'Regular payment' if not partial else 'Partial payment',
                     'seed', pay_date.isoformat(timespec='seconds')))
            print(f"  {loan_id}  {d['name']:25s}  {paid_due}/{d['tenure']} months  status={status}")

        print(f"\nSeeded {len(SAMPLE)} loans with payments.")


if __name__ == '__main__':
    seed()