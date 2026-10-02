# Humatron PDF Processing SaaS (`humatron.me`)

> Production-ready, formal, simple, high-performance web platform for converting PDF documents into image-based PDFs quickly and securely.

---

## 1. Project Overview

**Humatron** provides a reliable, secure document processing SaaS designed to flatten PDF documents. Original text, fonts, and vector paths are rendered into raster images at 150 DPI and reconstructed into a clean, unselectable, tamper-resistant PDF preserving the exact page dimensions of the original document.

### Primary Purpose & Workflow

```text
Visitor
  ↓
Register on humatron.me
  ↓
Cryptographic email verification link
  ↓
Login & Access Dashboard
  ↓
Upload first PDF (1 Free Trial PDF)
  ↓
Celery background worker converts pages to images
  ↓
Rebuilds image-based PDF & stores with randomized filename
  ↓
User downloads processed PDF (authenticated ownership check)
  ↓
Trial becomes consumed
  ↓
User chooses 1 of 4 subscription plans
  ↓
Country determines payment provider (Ethiopia = Telebirr, Other = Binance Pay)
  ↓
Server-side payment verification (atomic DB transaction)
  ↓
Subscription activated & usage tracked idempotently
  ↓
Documents automatically deleted after 7-day retention period
```

---

## 2. Technology Stack

- **Backend**: Python 3.12+ / 3.14, Django 5.2, Django REST Framework
- **Database**: PostgreSQL 16+ / 18
- **Background Tasks**: Celery with Redis broker and result backend
- **PDF Engine**: PyMuPDF (`pymupdf`), Pillow, pypdf
- **Frontend**: Clean semantic HTML5, formal CSS, minimal vanilla JavaScript (no heavyweight JS frameworks)
- **Production Server**: Gunicorn with Uvicorn ASGI workers, Nginx reverse proxy, systemd

---

## 3. Repository Structure

```text
humatron/
├── manage.py                   # Django management script
├── requirements.txt            # Python dependencies
├── .env.example                # Documented configuration template
├── .gitignore                  # Git ignore rules
├── README.md                   # Comprehensive documentation
├── SECURITY.md                 # Security & responsible disclosure policy
│
├── config/                     # Core project configuration
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py             # Base settings & environment parser
│   │   ├── development.py      # Development overrides
│   │   └── production.py       # Production security headers & HSTS
│   ├── celery.py               # Celery app & periodic beat schedules
│   ├── urls.py                 # Root URL configuration
│   ├── views.py                # Core pages & error handlers
│   ├── asgi.py                 # ASGI entrypoint
│   └── wsgi.py                 # WSGI entrypoint
│
├── accounts/                   # User authentication, profiles, verification & device signals
├── subscriptions/              # 4 configurable plans, quotas & lifecycle management
├── payments/                   # Binance Pay v3 API & Telebirr SMS verification engine
├── pdf_processor/              # Upload validation, PyMuPDF converter, Celery tasks
├── notifications/              # Transactional email notification service
├── contact/                    # Contact form with honeypot spam protection
├── usage/                      # Idempotent usage deduction & tracking
├── audit/                      # Read-only administrative audit log
│
├── api/                        # Django REST Framework API endpoints
├── templates/                  # Formal, accessible HTML templates
├── static/                     # CSS stylesheets & minimal JS
├── tests/                      # Automated test suite (36 comprehensive tests)
├── deployment/                 # Nginx, Systemd service files, and backup scripts
└── .github/workflows/ci.yml    # GitHub Actions CI/CD pipeline
```

---

## 4. Key Architectural Implementations

### PDF Page-to-Image Flattening (`pdf_processor/converter.py`)
- Employs a chunked, streaming loop rendering each page to a pixmap at 150 DPI.
- Generates a newly initialized PDF document where each page dimensions (`rect.width`, `rect.height`) match the original input.
- Inserts rendered JPEG bytes and immediately frees bitmap memory buffers, keeping RAM consumption constant even for large multi-page documents.

### Security & IDOR Authorization
- Untrusted PDF uploads are checked for `%PDF-` header magic bytes, document corruption, password/encryption status, and page limits before processing.
- Direct filesystem paths are never exposed to the client. Random UUID filenames are stored in `media/uploads/` and `media/processed/`.
- Download endpoint (`/pdf/jobs/<id>/download/`) strictly enforces object-level ownership: users can only download files belonging to their own account.

### Telebirr Payment Verification (`payments/telebirr_parser.py`)
- Untrusted SMS confirmation messages are parsed using prioritized regex extractors.
- Disallows matching reserved words (`TRANSFERRED`, `CUSTOMER`, `SUCCESSFUL`, `COMPLETED`, etc.).
- Verifies extracted ETB amount against the plan's explicit `price_etb` configured by the administrator.
- Uses PostgreSQL unique constraints on `(provider, transaction_id)` to guarantee idempotency and prevent transaction reuse.
- All subscription activations execute inside `transaction.atomic()` with rollback on failure.

### Rate Limiting & Abuse Prevention
- In-memory / Redis cache-backed rate limiting middleware protects authentication (`/accounts/login/`, `/accounts/register/`), contact form, and PDF upload endpoints.
- Returns HTTP 429 Too Many Requests with a `Retry-After` header when limits are exceeded.

---

## 5. Local Setup & Installation

### Prerequisites
- Python 3.10+ (tested on Python 3.12 & Python 3.14)
- PostgreSQL 14+
- Redis 6+

### Step 1: Clone and Set Up Virtual Environment

```bash
git clone https://github.com/humatron/humatron.git
cd humatron

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` to match your local database and Redis connection:

```ini
DJANGO_SECRET_KEY=local-dev-secret-key-at-least-50-characters-long
DJANGO_DEBUG=True
DATABASE_URL=postgresql://humatron_user:password@localhost:5432/humatron_db
REDIS_URL=redis://127.0.0.1:6379/0
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Step 3: Run Database Migrations & Seed Plans

```bash
python manage.py migrate
python manage.py seed_plans
```

This creates the four configurable subscription plans in PostgreSQL:
1. **Starter**: $20.00 USD / 2,700 ETB (10 PDFs)
2. **Professional**: $50.00 USD / 6,750 ETB (25 PDFs) — Recommended primary plan
3. **Business**: $100.00 USD / 13,500 ETB (60 PDFs)
4. **Enterprise**: $250.00 USD / 33,750 ETB (200 PDFs)

### Step 4: Create Superuser

```bash
python manage.py createsuperuser
```

### Step 5: Start Background Workers

In a separate terminal:
```bash
# Start Celery Worker
celery -A config worker -l INFO

# Start Celery Beat (Periodic Cleanup Scheduler)
celery -A config beat -l INFO
```

### Step 6: Start Development Server

```bash
python manage.py runserver
```

Access the application at `http://127.0.0.1:8000/`.

---

## 6. Running the Automated Test Suite

Run the full automated test suite containing 36 unit, integration, payment, security, and IDOR tests:

```bash
python manage.py test tests
```

To run individual test modules:
```bash
python manage.py test tests.test_auth
python manage.py test tests.test_pdf_processing
python manage.py test tests.test_trial_and_usage
python manage.py test tests.test_subscriptions
python manage.py test tests.test_payments_telebirr
python manage.py test tests.test_payments_binance
python manage.py test tests.test_security
python manage.py test tests.test_contact_and_api
```

---

## 7. Production Deployment Guide

### Architecture

```text
Internet
   ↓
Nginx (Port 80/443, SSL/TLS, Security Headers, Static Assets)
   ↓
Gunicorn / Uvicorn ASGI Application (127.0.0.1:8000)
   ↓
PostgreSQL 16+ & Redis 7+

Celery Worker (PDF Stealth) + Celery Beat (Daily File Cleanup)
```

### Deployment Steps on Ubuntu / Debian Linux

1. **Deploy Code & Static Files**:
   ```bash
   sudo mkdir -p /var/www/humatron
   # Copy code to /var/www/humatron
   python manage.py collectstatic --noinput
   ```

2. **Configure Nginx**:
   ```bash
   sudo cp deployment/nginx.conf /etc/nginx/sites-available/humatron
   sudo ln -s /etc/nginx/sites-available/humatron /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

3. **Install Systemd Services**:
   ```bash
   sudo cp deployment/humatron.service /etc/systemd/system/
   sudo cp deployment/humatron-celery.service /etc/systemd/system/
   sudo cp deployment/humatron-celerybeat.service /etc/systemd/system/

   sudo systemctl daemon-reload
   sudo systemctl enable --now humatron
   sudo systemctl enable --now humatron-celery
   sudo systemctl enable --now humatron-celerybeat
   ```

4. **SSL Certificates (Let's Encrypt)**:
   ```bash
   sudo certbot --nginx -d humatron.me -d www.humatron.me
   ```

---

## 8. Database Backups & Recovery

### Automated Backups
The automated backup script is located at `deployment/backup_db.sh`. It performs compressed custom-format dumps (`pg_dump -Fc`), creates SHA256 checksums, tests restore integrity, and rotates backups keeping the last 30 days.

Schedule via cron (`crontab -e`):
```cron
0 2 * * * /var/www/humatron/deployment/backup_db.sh >> /var/log/humatron/backup_cron.log 2>&1
```

### Database Restoration
To restore a backup safely:
```bash
sudo /var/www/humatron/deployment/restore_db.sh /var/backups/humatron/postgres/humatron_db_YYYYMMDD_HHMMSS.dump
```

---

## 9. Binance Pay Integration Guide

### 1. Overview
Humatron integrates **Binance Pay (Merchant Acquiring v3)** to allow customers worldwide to pay for SaaS subscriptions using cryptocurrency (USDT, USDC, BTC, ETH, and other supported crypto assets) with instant settlement and 0% gas fees.

- **Primary Source of Truth**: [Binance Developer Documentation](https://developers.binance.com/)
- **Merchant Management Portal**: [Binance Merchant Admin](https://merchant.binance.com/)

---

### 2. Binance Merchant Account Setup
1. Register or log in to your verified business/merchant account at [merchant.binance.com](https://merchant.binance.com/).
2. Complete Merchant Identity / Business Verification (KYC/KYB).
3. Navigate to **Developer** / **API Management** in the merchant portal.
4. Generate your **API Key** (Certificate Serial Number) and **Secret Key**.
5. Set up IP Whitelisting for your production server IP addresses (optional during local testing).

---

### 3. Required Credentials & Environment Variables
Add the following variables to your server `.env` file:

```bash
# Binance Pay API Credentials (Official Merchant Open API)
BINANCE_PAY_API_KEY=your_binance_pay_certificate_sn_or_api_key
BINANCE_PAY_SECRET_KEY=your_binance_pay_secret_key
BINANCE_PAY_BASE_URL=https://bpay.binanceapi.com
BINANCE_PAY_RETURN_URL=https://humatron.me/payments/binance/return/
BINANCE_PAY_CANCEL_URL=https://humatron.me/payments/binance/cancel/
BINANCE_PAY_WEBHOOK_URL=https://humatron.me/payments/webhook/binance/
```

> [!CAUTION]
> **Never commit your API Secret Key to version control.** Store it strictly as a server-side environment variable.

---

### 4. Local Development & Simulation
For local development, when `BINANCE_PAY_API_KEY` is omitted or set to mock values:
- Order creation automatically operates in simulated sandbox mode.
- Initiating a payment directs to `/payments/binance/simulate-checkout/<trade_no>/`.
- Developers can click "Simulate Successful Payment" to test the exact webhook and activation flow end-to-end without real funds.
- To test with live Binance Sandbox or Testnet credentials, set `BINANCE_PAY_BASE_URL` and valid test credentials in `.env`.

---

### 5. Webhook Configuration
Configure your webhook notification URL in the Binance Merchant Portal:
- **Webhook Endpoint**: `https://<your-domain>/payments/webhook/binance/`
- **Supported Events**: `PAY_SUCCESS`, `PAY_CLOSED`, `PAY_EXPIRED`
- **Method**: HTTP `POST`

---

### 6. Payment Flow & Authoritative Verification Architecture

```text
Customer selects plan on SaaS checkout
       ↓
Django POST /payments/binance/initiate/<plan_code>/
       ↓
1. Server validates user & active plan
2. Server calculates authoritative price from database plan
3. Server generates unique merchantTradeNo (HP<timestamp><hex>)
4. Django calls POST /binancepay/openapi/v3/order (HMAC-SHA512 signed)
5. Django creates pending Payment record in database
       ↓
Customer redirected to Binance hosted checkout URL (or scans QR)
       ↓
Customer completes payment on Binance
       ↓
Binance dispatches Webhook to /payments/webhook/binance/
       ↓
1. Django verifies RSA-SHA256 signature using Binance Public Key certificate
2. Django acquires row-level lock (select_for_update) on Payment record
3. Idempotency check: if already VERIFIED, returns SUCCESS without duplicate activation
4. Fallback verification: queries POST /binancepay/openapi/v2/order/query
5. Verifies orderAmount, currency (USDT), and order status (PAID)
       ↓
Atomic Database Transaction:
- Payment marked VERIFIED with timestamp & Binance transaction ID
- Subscription marked ACTIVE (quotas & validity period updated)
- Dispatches transactional payment receipt email
       ↓
Customer returns to /payments/binance/return/ and receives immediate SaaS access
```

---

### 7. Database Migrations & Models
The `Payment` model in `payments/models.py` includes:
- `provider`: Choices include `'binance'` (`PROVIDER_BINANCE`).
- `merchant_trade_no`: Unique indexed reference for each Binance order.
- `prepay_id`: Binance prepay order identifier.
- `binance_order_id`: Binance transaction identifier.
- `checkout_url`, `qr_code_url`, `qr_content`: Checkout links and QR codes.
- `order_expire_time`: Expiration timestamp.
- Unique constraints: `['provider', 'transaction_id']` and `unique_binance_merchant_trade_no`.

To apply migrations:
```bash
python manage.py migrate payments
```

---

### 8. Testing
Run the dedicated Binance Pay test suite:
```bash
python manage.py test tests.test_payments_binance
```
Run all payment tests (Telebirr, Binance):
```bash
python manage.py test tests.test_payments_telebirr tests.test_payments_binance
```

---

### 9. Security Best Practices
- **HMAC-SHA512 Outbound Requests**: All outgoing requests are signed with timestamp and nonce.
- **RSA-SHA256 Webhook Verification**: Inbound webhooks are verified using Binance's public key certificates fetched directly from `POST /binancepay/openapi/certificates` and cached in Redis.
- **Zero Frontend Authority**: Subscription prices, amounts, and statuses are strictly dictated and verified by the Django backend.
- **Timing Attacks & Tampering**: Raw body byte verification ensures no signature mismatches or tampering.

---

## 10. License & Responsible Use

Proprietary software for **humatron.me**. All rights reserved.
Ensure compliance with document privacy regulations in your jurisdiction.

# humatrona1
