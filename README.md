# WhatsApp Payment Verification Agent

A prototype system that verifies customer bank-transfer payments over WhatsApp
without a direct bank API. It reasons over payment slip images, OCR'd data, bank
SMS notifications, and order history to decide **APPROVED**, **REJECTED**, or
**NEEDS_VERIFICATION**, with a reason and a next step — and it's built to spend
AI/OCR cost only when the cheap checks can't already resolve the case.

## How a payment moves through the pipeline

```
Customer sends slip image on WhatsApp
        │
        ▼
1. Intake & dedup ── SHA-256 hash check ──► duplicate? reject, notify customer
        │
        ▼
2. Acknowledge ── "Payment received, verifying now..."
        │
        ▼
3. Categorize ── DIGITAL / PHYSICAL_SLIP / ATM_RECEIPT (heuristic)
        │
        ▼
4. Visual quality check (cheap, local) ── too blurry? ──► retry loop (max 2) ──► NEEDS_VERIFICATION
        │
        ▼
5. Visual fraud check (cheap, local) ── tampering detected? ──► REJECTED
        │
        ▼
6. Cost guard ── no order at all for this phone + already abusive? ──► REJECTED, skip OCR
        │
        ▼
7. OCR extraction (expensive) ── bank, account, amount, date, reference, payee, NIC
   incomplete / low confidence? ──► retry loop (max 2) ──► NEEDS_VERIFICATION
        │
        ▼
8. Validation ── cross-reference against the order:
   - reused transaction fingerprint? ──► REJECTED
   - no / ambiguous order match?     ──► NEEDS_VERIFICATION
   - wrong account?                  ──► REJECTED
   - under/overpaid past tolerance?  ──► REJECTED
        │
        ▼
9. Route ── SMS enabled? ──► AWAITING_SMS (times out to ADVANCED_CHECKING)
             SMS disabled? ──► ADVANCED_CHECKING
        │
        ▼
10. Resolution ── bank SMS match (auto-APPROVED) or human decision via dashboard
```

Every stage after the first cheap checks is gated on the previous one passing —
OCR only runs if the image is clear and not obviously tampered with, and the
expensive OCR call is skipped entirely for phones with no order at all once
they've already been flagged a few times.

## Project structure

```
.
├── main.py                 # FastAPI app: intake pipeline, SMS webhook, dashboard API
├── database.py              # SQLAlchemy models (PaymentRecord, OrderRecord, SMSRecord)
├── schemas.py                # Pydantic response models for the dashboard endpoints
├── vision_service.py         # Blur detection, categorization, ELA tamper check (OpenCV)
├── ocr_service.py            # OCR extraction + normalization (currently mocked)
├── validation_service.py     # Stage 3: order matching, tolerance, reuse detection
├── maintenance.py            # Scheduled jobs: stale-data purge, SMS timeout escalation
├── requirements.txt
└── .env                      # Not committed — see below
```

## Setup

1. **Install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate          # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Create the database**
   ```sql
   CREATE DATABASE payment_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'payment_app'@'localhost' IDENTIFIED BY 'a_strong_password';
   GRANT ALL PRIVILEGES ON payment_db.* TO 'payment_app'@'localhost';
   FLUSH PRIVILEGES;
   ```

3. **Create `.env`** in the project root:
   ```
   DATABASE_URL=mysql+pymysql://payment_app:a_strong_password@localhost:3306/payment_db
   WHATSAPP_TOKEN=your_meta_whatsapp_token
   WHATSAPP_PHONE_ID=your_whatsapp_phone_number_id
   DASHBOARD_API_KEY=some_random_string_for_the_dashboard
   SMS_INGEST_SECRET=some_random_string_for_the_sms_webhook
   CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
   ```
   Without `DASHBOARD_API_KEY` / `SMS_INGEST_SECRET` set, those routes return `503`
   rather than opening up unauthenticated.

4. **Run it**
   ```bash
   uvicorn main:app --reload
   ```
   Tables are created automatically on first run. API docs: `http://localhost:8000/docs`.

## API reference

### Customer-facing

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/intake` | none yet* | Submit a slip image (`multipart/form-data`: `phone_number`, `company_sms_enabled`, `order_id` optional, `slip_image`) |

\* Production should verify this is really coming from your WhatsApp webhook, not
the open internet.

### Bank / gateway-facing

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/sms/ingest` | `X-SMS-Secret` header | Report an inbound bank SMS (`bank_name`, `account_no`, `amount`, `raw_text`) |

### Internal dashboard (all require `X-API-Key` header)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/payments?status=&limit=&offset=` | List payments, newest first |
| `GET /api/v1/payments/{image_hash}` | One payment + its matched order, for the diff view |
| `GET /api/v1/stats` | Target revenue, verified income, discrepancy |
| `GET /api/v1/active-processes` | Payments still `PENDING` / `AWAITING_SMS` / `ADVANCED_CHECKING` |
| `POST /api/v1/payments/{image_hash}/decision` | Human resolves a `NEEDS_VERIFICATION` / `ADVANCED_CHECKING` payment (`{"decision": "APPROVED"\|"REJECTED", "note": "..."}`) |

## Payment status values

| Status | Meaning |
|---|---|
| `PENDING` | Submitted, still going through checks |
| `REJECTED` | Failed a check with a specific reason (see `reason` field) |
| `AWAITING_SMS` | Passed all checks, waiting for a matching bank SMS |
| `ADVANCED_CHECKING` | SMS disabled, or SMS timed out — awaiting human/advanced review |
| `NEEDS_VERIFICATION` | Confidence too low, or an order-matching ambiguity — needs a human decision |
| `APPROVED` | Verified, either by SMS match or manual decision |

## Configuration you'll likely want to tune

- `vision_service.BLUR_THRESHOLDS` and the ELA constants in `_ela_penalty` — currently
  guesses, calibrate against real slips.
- `ocr_service.MANDATORY_BY_CATEGORY` and `OCR_MIN_CONFIDENCE` in `main.py`.
- `validation_service.TOLERANCE_OVER` — currently a flat Rs. 100 buffer on overpayment,
  zero tolerance on underpayment.
- `maintenance.SMS_TOLERANCE_MINUTES` — how long to wait for a bank SMS before
  escalating to `ADVANCED_CHECKING`.
- `main.ABUSE_THRESHOLD` / `ABUSE_WINDOW_MINUTES` — how many order-less submissions
  from one phone number before the OCR step gets skipped.

## Known limitations (not yet built)

- `ocr_service.py` is fully mocked — no real OCR engine is wired in yet.
- Physical-slip tamper detection (`vision_service.detect_visual_fraud`) always
  returns "not fraudulent" for `PHYSICAL_SLIP` / `ATM_RECEIPT` — only the digital
  ELA check is implemented.
- No real WhatsApp webhook receiver — `send_whatsapp_message` can send outbound
  messages, but nothing yet ingests inbound ones or verifies Meta's webhook signature.
- SMS timeout only marks the row `ADVANCED_CHECKING`; no actual alert (email/Slack)
  goes to the business yet — see the `TODO` in `maintenance.py`.
- `_normalize_amount` assumes `.` as the decimal separator; a EU-formatted slip
  (`25.000,00`) would misparse.
- Dashboard auth is a single static API key — fine for a prototype, not for
  production multi-user access.
