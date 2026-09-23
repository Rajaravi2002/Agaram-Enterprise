# Agaram Finance Management System

A complete, production-ready offline loan management system for local finance companies. Built with Python Flask, MongoDB, Bootstrap 5 and Chart.js.

---

## Features

| Module | Features |
|---|---|
| **Authentication** | Admin & Staff roles, session management, remember me |
| **Dashboard** | 9 live KPI cards, 5 Chart.js charts, recent activity feed |
| **Customer Management** | Add / Edit / View / Deactivate, duplicate phone check |
| **Loan Management** | Create / View / Close / Mark overdue, auto EMI calculation |
| **EMI Collection** | Record payments, automatic carry-forward logic |
| **Pending Dues** | Real-time carry-forward tracking per loan |
| **Defaulters** | Overdue loan list with quick-collect button |
| **Reports** | Daily / Weekly / Monthly / Custom collection, loan, pending |
| **Excel Export** | Customers, Loans, Payments, Pending via OpenPyXL |
| **PDF Export** | Collection and Loan reports via ReportLab |
| **Backup** | Manual + restore; ZIP-compressed JSON backup |
| **Global Search** | Instant search across customers, loans, payments |

---

## Quick Start (Windows)

### Prerequisites
- Python 3.9 or higher — https://python.org
- MongoDB Community Server — https://www.mongodb.com/try/download/community

### Install

```
1. Extract the project folder anywhere on your PC.
2. Double-click setup.bat
3. Follow the prompts (optionally load sample data).
4. Double-click start.bat to launch.
5. Open http://localhost:5000 in your browser.
```

### Default Credentials

| Role  | Username | Password  |
|-------|----------|-----------|
| Admin | admin    | admin123  |
| Staff | staff    | staff123  |

> ⚠️ Change passwords after first login in production.

---

## Manual Setup (Command Line)

```bash
# 1. Navigate to project folder
cd agaram_finance

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start MongoDB (Windows service)
net start MongoDB

# 4. (Optional) Load sample data
python seed_data.py

# 5. Start the application
python run.py
```

---

## Project Structure

```
agaram_finance/
├── run.py                  # Application entry point
├── app.py                  # Flask app factory + DB init
├── config.py               # Configuration
├── models.py               # Schemas, ID generators, EMI calc
├── seed_data.py            # Sample data seeder
├── requirements.txt        # Python dependencies
├── setup.bat               # Windows first-time setup
├── start.bat               # Windows launcher
│
├── routes/
│   ├── auth.py             # Login / Logout / User loader
│   ├── dashboard.py        # Dashboard + Chart API endpoints
│   ├── customers.py        # Customer CRUD
│   ├── loans.py            # Loan management + EMI calculator
│   ├── payments.py         # EMI collection, pending, defaulters
│   ├── reports.py          # Reports + Excel/PDF export
│   ├── backup.py           # Backup / Restore
│   └── api.py              # Global search + AJAX helpers
│
├── templates/
│   ├── base.html           # Master layout (sidebar, topbar)
│   ├── auth/login.html
│   ├── dashboard/index.html
│   ├── customers/{index,add,edit,view}.html
│   ├── loans/{index,create,view}.html
│   ├── payments/{index,collect,receipt,pending,defaulters}.html
│   ├── reports/{index,collection,loan_report,pending_report}.html
│   └── backup/index.html
│
├── static/
│   ├── css/main.css        # Full design system CSS
│   └── js/main.js          # Sidebar, search, helpers
│
├── backups/                # Backup ZIP files stored here
└── reports/                # Temp report files
```

---

## MongoDB Collections

### `users`
```json
{
  "username": "admin",
  "password_hash": "<bcrypt>",
  "role": "admin | staff",
  "full_name": "Administrator",
  "email": "admin@agaram.local",
  "is_active": true,
  "created_at": "ISODate",
  "last_login": "ISODate"
}
```

### `customers`
```json
{
  "customer_id": "AGR-CUST-0001",
  "name": "Rajesh Kumar",
  "phone": "9876543210",
  "alt_phone": "9876543211",
  "address": "12, Gandhi Nagar, Madurai",
  "aadhaar": "234567890123",
  "occupation": "Farmer",
  "date_added": "ISODate",
  "added_by": "admin",
  "is_active": true
}
```

### `loans`
```json
{
  "loan_id": "AGR-LOAN-0001",
  "customer_id": "AGR-CUST-0001",
  "customer_name": "Rajesh Kumar",
  "loan_amount": 50000,
  "interest_rate": 12,
  "loan_start_date": "ISODate",
  "loan_duration_months": 12,
  "due_date": "ISODate",
  "total_interest": 6000,
  "total_payable": 56000,
  "monthly_emi": 4666.67,
  "loan_status": "active | closed | overdue",
  "created_at": "ISODate",
  "created_by": "admin",
  "closed_at": null,
  "remarks": ""
}
```

### `payments`
```json
{
  "payment_id": "AGR-PAY-0001",
  "loan_id": "AGR-LOAN-0001",
  "customer_id": "AGR-CUST-0001",
  "customer_name": "Rajesh Kumar",
  "collection_date": "ISODate",
  "emi_amount": 4666.67,
  "carry_forward": 0,
  "total_due": 4666.67,
  "paid_amount": 4666.67,
  "pending_amount": 0,
  "month_number": 1,
  "collection_remarks": "Regular payment",
  "collected_by": "staff",
  "created_at": "ISODate"
}
```

---

## EMI & Carry-Forward Logic

### Simple Interest Formula
```
Total Interest  = (Principal × Rate × Duration) / 1200
Total Payable   = Principal + Total Interest
Monthly EMI     = Total Payable / Duration
```

### Carry-Forward Logic
```
Month 1: EMI = ₹5,000 | Paid = ₹3,000 | Pending = ₹2,000
Month 2: Base EMI = ₹5,000 + Carry Forward ₹2,000 = Total Due ₹7,000
Month 2: Customer pays ₹7,000 → Pending = ₹0
```
This is implemented in `routes/payments.py → get_carry_forward()`.

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/search?q=` | Global search |
| GET | `/api/customer/<id>` | Customer JSON |
| GET | `/api/chart/monthly-collection` | 12-month chart data |
| GET | `/api/chart/loan-distribution` | Pie chart data |
| GET | `/api/chart/top-borrowers` | Bar chart data |
| GET | `/api/chart/collection-performance` | 6-month dual bar |
| GET | `/api/recent-activity` | Recent payments JSON |
| GET | `/payments/api/loan-info/<id>` | Loan + carry-forward info |
| POST| `/loans/calculate` | EMI calculator (AJAX) |

---

## Backup & Restore

- **Create Backup**: Admin → Backup → "Create Backup Now"
- **Download**: Click the download icon next to any backup
- **Restore**: Click the restore icon (⚠️ overwrites all current data)
- **Location**: `./backups/agaram_backup_YYYYMMDD_HHMMSS.zip`
- **Format**: All MongoDB collections serialised to JSON, compressed to ZIP

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Cannot connect to MongoDB | Run `net start MongoDB` or start from Windows Services |
| Port 5000 in use | Edit `run.py` and change `port=5000` to another port |
| Missing module error | Run `pip install -r requirements.txt` again |
| Blank page after login | Check MongoDB is running and accessible |

---

## Technology Stack

| Component | Library | Version |
|-----------|---------|---------|
| Backend   | Flask + Flask-Login | 3.0 |
| Database  | MongoDB + PyMongo | 4.6 |
| Frontend  | Bootstrap 5 + Bootstrap Icons | 5.3 |
| Charts    | Chart.js | 4.4 |
| Excel     | Pandas + OpenPyXL | Latest |
| PDF       | ReportLab | 4.0 |
| Fonts     | Inter (Google Fonts) | — |

---

*Agaram Finance Management System v1.0 — Built for offline local use*
