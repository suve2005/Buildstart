import hashlib
import logging
import os
from contextlib import asynccontextmanager

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException, Header, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import ocr_service
import validation_service
import vision_service
from database import SessionLocal, PaymentRecord, OrderRecord, SMSRecord
from maintenance import purge_stale_extracted_data, escalate_timed_out_sms_waits
from schemas import PaymentOut, PaymentDetailOut, OrderOut, StatsOut, DecisionIn, SMSIngestIn

load_dotenv()
logger = logging.getLogger(__name__)

MAX_SIZE = 10 * 1024 * 1024
MAX_RETRIES = 2
RETRY_WINDOW_HOURS = 12
RETRYABLE_REASONS = ("quality_failed", "ocr_incomplete")
OCR_MIN_CONFIDENCE = 70.0
REVIEW_THRESHOLD = 80.0
EXTRACTED_FIELDS = ("bank_name", "account_no", "amount", "payment_date",
                    "reference_no", "payee_name", "nic_masked")


ABUSE_WINDOW_MINUTES = 60
ABUSE_THRESHOLD = 5
NO_ORDER_REASONS = ("no_active_order", "ambiguous_order", "order_not_found")

MSG_ACK = "Payment received, verifying now..."
MSG_DUPLICATE = "This payment slip has already been submitted."
MSG_RESENT = "We already received this exact image and couldn't read it. Please send a new, clearer photo."
MSG_BLURRY = "The image is too blurry. Please send a clearer photo."
MSG_UNREADABLE = ("We couldn't clearly read the transaction details (amount, account or reference). "
                  "Please send a clearer, flat image of the complete slip.")
MSG_ESCALATED = "We couldn't automatically verify the slip details. A human agent will review your payment shortly."
MSG_REVIEW = "Your payment is being reviewed by our team. We'll update you shortly."
MSG_FRAUD = "We are unable to process this slip. Please contact support."
MSG_NO_ORDER_ABUSE = "We still can't find a matching order for your number. Please contact support directly."
MSG_APPROVED = "Your payment has been successfully verified! Your order is now processing."
MSG_REJECTED_FINAL = "Your payment could not be verified. Please contact support for help."

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")
SMS_INGEST_SECRET = os.getenv("SMS_INGEST_SECRET")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")]


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(purge_stale_extracted_data, "interval", minutes=30)
    scheduler.add_job(escalate_timed_out_sms_waits, "interval", minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_dashboard_auth(x_api_key: str = Header(None)):
    """MVP auth for internal dashboard routes only -- not the customer-facing /intake
    or the bank's /sms/ingest webhook, which need their own auth schemes (WhatsApp
    webhook verification, SMS gateway signature) not yet implemented here."""
    if not DASHBOARD_API_KEY:
        
        raise HTTPException(status_code=503, detail="Dashboard auth is not configured")
    if x_api_key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def require_sms_auth(x_sms_secret: str = Header(None)):
    if not SMS_INGEST_SECRET:
        raise HTTPException(status_code=503, detail="SMS ingestion is not configured")
    if x_sms_secret != SMS_INGEST_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing SMS secret")


def send_whatsapp_message(phone_number: str, text_body: str):
    """Synchronous POST to the Meta Graph API (runs as a background task)."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        return
    
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": phone_number,
               "type": "text", "text": {"body": text_body}}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error("WhatsApp send failed: %s %s", response.status_code, response.text)
    except requests.RequestException as e:
        logger.error("WhatsApp send error: %s", e)


def get_retry_count(db: Session, phone_number: str) -> int:
    last = (db.query(PaymentRecord)
            .filter(PaymentRecord.phone_number == phone_number,
                    PaymentRecord.created_at > func.date_sub(
                        func.now(), text(f"INTERVAL {RETRY_WINDOW_HOURS} HOUR")))
            .order_by(desc(PaymentRecord.id))
            .first())
    if last and last.status == "REJECTED" and last.reason in RETRYABLE_REASONS:
        return last.retry_count + 1
    return 0


def count_recent_no_order_submissions(db: Session, phone_number: str) -> int:
    return db.query(PaymentRecord).filter(
        PaymentRecord.phone_number == phone_number,
        PaymentRecord.reason.in_(NO_ORDER_REASONS),
        PaymentRecord.created_at > func.date_sub(func.now(), text(f"INTERVAL {ABUSE_WINDOW_MINUTES} MINUTE")),
    ).count()


def retry_or_escalate(retry_count: int, reason: str, retry_message: str):
    if retry_count >= MAX_RETRIES:
        return "NEEDS_VERIFICATION", "max_retries_exceeded", MSG_ESCALATED
    return "REJECTED", reason, retry_message


def save_and_respond(db, background_tasks, phone_number, image_hash, status, reason, message,
                     retry_count, category, confidence, order_id=None, fingerprint=None, ocr=None):
    data = ocr["data"] if ocr else {}
    record = PaymentRecord(
        image_hash=image_hash, phone_number=phone_number, status=status, reason=reason,
        category=category, retry_count=retry_count, confidence_score=confidence,
        ocr_confidence=ocr["ocr_confidence"] if ocr else None,
        transaction_fingerprint=fingerprint, order_id=order_id,
        **{field: data.get(field) for field in EXTRACTED_FIELDS},
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:  
        db.rollback()
        background_tasks.add_task(send_whatsapp_message, phone_number, MSG_DUPLICATE)
        return {"status": "rejected", "reason": "duplicate_slip"}

    if message:
        background_tasks.add_task(send_whatsapp_message, phone_number, message)
    return {"status": status, "reason": reason, "hash": image_hash, "category": category,
            "confidence": round(confidence, 1) if confidence is not None else None,
            "retry_count": retry_count}


@app.post("/api/v1/intake")
async def process_intake(
        background_tasks: BackgroundTasks,
        phone_number: str = Form(...),
        company_sms_enabled: bool = Form(...),  # MOCK: must come from server-side business settings later
        order_id: int = Form(None),             # optional: pass this when the bot flow knows which order
        slip_image: UploadFile = File(...),
        db: Session = Depends(get_db)):

    # 1. Validation
    if not (slip_image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are accepted")
    file_bytes = await slip_image.read()
    if not file_bytes or len(file_bytes) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Invalid file size")

    # 2. Deduplication
    image_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = db.query(PaymentRecord).filter(PaymentRecord.image_hash == image_hash).first()
    if existing:
        if existing.phone_number != phone_number:
            logger.warning("Slip hash %s reused by a different phone number", image_hash)
        retryable = existing.status == "REJECTED" and existing.reason in RETRYABLE_REASONS
        background_tasks.add_task(send_whatsapp_message, phone_number,
                                  MSG_RESENT if retryable else MSG_DUPLICATE)
        return {"status": "rejected", "reason": "duplicate_slip"}

    background_tasks.add_task(send_whatsapp_message, phone_number, MSG_ACK)

    retry_count = get_retry_count(db, phone_number)
    category = await run_in_threadpool(vision_service.categorize_image, file_bytes)

    # 3. Visual quality (cheap)
    quality = await run_in_threadpool(vision_service.assess_image_quality, file_bytes, category)
    if not quality["is_clear"]:
        status, reason, message = retry_or_escalate(retry_count, "quality_failed", MSG_BLURRY)
        return save_and_respond(db, background_tasks, phone_number, image_hash, status, reason,
                                message, retry_count, category, confidence=0.0)

    # 4. Fraud check (cheap, before the expensive OCR)
    fraud = await run_in_threadpool(vision_service.detect_visual_fraud, file_bytes, category)
    visual_confidence = 100.0 - fraud["confidence_penalty"]
    if fraud["is_fraudulent"]:
        return save_and_respond(db, background_tasks, phone_number, image_hash, "REJECTED",
                                "fraud_detected", MSG_FRAUD, retry_count, category, visual_confidence)

    # 5. Cost guard: skip the expensive OCR call entirely if this phone has no order at
    #    all (independent of what's in the image) and has already hit the abuse threshold.
    if order_id is None:
        has_any_order = db.query(OrderRecord).filter(
            OrderRecord.phone_number == phone_number, OrderRecord.status == "AWAITING_PAYMENT"
        ).first()
        if not has_any_order and count_recent_no_order_submissions(db, phone_number) >= ABUSE_THRESHOLD:
            return save_and_respond(db, background_tasks, phone_number, image_hash, "REJECTED",
                                    "no_active_order", MSG_NO_ORDER_ABUSE, retry_count,
                                    category, visual_confidence)

    # 6. OCR (expensive: only reached after the cheap checks pass)
    ocr = await run_in_threadpool(ocr_service.process_slip_text, file_bytes, category)
    cumulative = visual_confidence * ocr["ocr_confidence"] / 100.0

    if not ocr["is_complete"] or ocr["ocr_confidence"] < OCR_MIN_CONFIDENCE:
        status, reason, message = retry_or_escalate(retry_count, "ocr_incomplete", MSG_UNREADABLE)
        return save_and_respond(db, background_tasks, phone_number, image_hash, status, reason,
                                message, retry_count, category, cumulative, ocr=ocr)

    # 7. Stage 3: cross-reference against the order, tolerance, and reuse detection
    verdict = validation_service.validate_payment(db, phone_number, ocr["data"], order_id=order_id)

    if not verdict["is_valid"]:
        status, reason, message = verdict["status"], verdict["reason"], verdict["message"]
    elif cumulative < REVIEW_THRESHOLD:
        status, reason, message = "NEEDS_VERIFICATION", "low_confidence", MSG_REVIEW
    else:
        status = "AWAITING_SMS" if company_sms_enabled else "ADVANCED_CHECKING"
        reason, message = verdict["reason"], None  # keeps e.g. minor_amount_discrepancy for the dashboard

    return save_and_respond(db, background_tasks, phone_number, image_hash, status, reason, message,
                            retry_count, category, cumulative,
                            order_id=verdict.get("order_id"), fingerprint=verdict.get("fingerprint"), ocr=ocr)


@app.post("/api/v1/sms/ingest", dependencies=[Depends(require_sms_auth)])
def ingest_sms(payload: SMSIngestIn, db: Session = Depends(get_db)):
    """Bank SMS webhook. Matches on account + exact amount against payments still
    AWAITING_SMS. An ambiguous match (two customers, same amount, same account, same
    window) is deliberately left unresolved rather than guessed -- it will either
    self-resolve if a later SMS narrows it down, or time out to ADVANCED_CHECKING for
    a human to sort out using the reference number."""
    sms = SMSRecord(bank_name=payload.bank_name, account_no=payload.account_no,
                    amount=payload.amount, raw_text=payload.raw_text)
    db.add(sms)
    db.flush()

    candidates = db.query(PaymentRecord).filter(
        PaymentRecord.status == "AWAITING_SMS",
        PaymentRecord.account_no == payload.account_no,
        PaymentRecord.amount == payload.amount,
    ).all()

    if len(candidates) == 1:
        payment = candidates[0]
        payment.status = "APPROVED"
        payment.reason = "sms_matched"
        sms.matched_payment_id = payment.id
        db.commit()
        send_whatsapp_message(payment.phone_number, MSG_APPROVED)
        return {"matched": True, "payment_id": payment.id}

    db.commit()
    return {"matched": False, "candidate_count": len(candidates)}


@app.post("/api/v1/payments/{image_hash}/decision", dependencies=[Depends(require_dashboard_auth)])
def submit_manual_decision(image_hash: str, decision: DecisionIn,
                           background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Lets the dashboard resolve a NEEDS_VERIFICATION or ADVANCED_CHECKING payment."""
    record = db.query(PaymentRecord).filter(PaymentRecord.image_hash == image_hash).first()
    if not record:
        raise HTTPException(status_code=404, detail="Payment not found")
    if record.status not in ("NEEDS_VERIFICATION", "ADVANCED_CHECKING"):
        raise HTTPException(status_code=400, detail=f"Payment is in status {record.status}, not reviewable")
    if decision.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail="decision must be APPROVED or REJECTED")

    record.status = decision.decision
    record.reason = decision.note or "manual_review"
    db.commit()

    background_tasks.add_task(send_whatsapp_message, record.phone_number,
                              MSG_APPROVED if decision.decision == "APPROVED" else MSG_REJECTED_FINAL)
    return {"status": record.status, "hash": image_hash}


# Dashboard GET endpoints (all require the dashboard API key)

@app.get("/api/v1/payments", response_model=list[PaymentOut], dependencies=[Depends(require_dashboard_auth)])
def get_payments(status: str = Query(None), limit: int = Query(100, le=500),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = db.query(PaymentRecord)
    if status:
        q = q.filter(PaymentRecord.status == status)
    return q.order_by(desc(PaymentRecord.created_at)).offset(offset).limit(limit).all()


@app.get("/api/v1/payments/{image_hash}", response_model=PaymentDetailOut,
        dependencies=[Depends(require_dashboard_auth)])
def get_payment_detail(image_hash: str, db: Session = Depends(get_db)):
    record = db.query(PaymentRecord).filter(PaymentRecord.image_hash == image_hash).first()
    if not record:
        raise HTTPException(status_code=404, detail="Payment not found")

    order = None
    if record.order_id is not None:
        order = db.query(OrderRecord).filter(OrderRecord.id == record.order_id).first()
    elif record.phone_number:
        order = db.query(OrderRecord).filter(OrderRecord.phone_number == record.phone_number).first()

    return {"payment": record, "order": order}


@app.get("/api/v1/stats", response_model=StatsOut, dependencies=[Depends(require_dashboard_auth)])
def get_dashboard_stats(db: Session = Depends(get_db)):
    target = db.query(func.sum(OrderRecord.expected_amount)).filter(
        OrderRecord.status == "AWAITING_PAYMENT").scalar() or 0
    verified = db.query(func.sum(PaymentRecord.amount)).filter(
        PaymentRecord.status == "APPROVED").scalar() or 0
    return {"target_revenue": float(target), "verified_income": float(verified),
            "discrepancy": float(verified) - float(target)}


@app.get("/api/v1/active-processes", response_model=list[PaymentOut], dependencies=[Depends(require_dashboard_auth)])
def get_active_processes(db: Session = Depends(get_db)):
    """Payments still moving through the pipeline: pending, awaiting SMS, or in
    advanced checking. ADVANCED_CHECKING was previously missing from this filter,
    which made SMS-timeout escalations disappear from the dashboard."""
    return db.query(PaymentRecord).filter(
        PaymentRecord.status.in_(["PENDING", "AWAITING_SMS", "ADVANCED_CHECKING"])
    ).order_by(desc(PaymentRecord.created_at)).all()
