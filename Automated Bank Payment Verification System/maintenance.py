from sqlalchemy import text
from database import SessionLocal

SMS_TOLERANCE_MINUTES = 30  # how long we wait for a matching bank SMS before escalating -random val

# Clears extracted data only. Rows, hashes, statuses and fraud history are kept, so
# duplicate detection and the audit trail survive. AWAITING_SMS / NEEDS_VERIFICATION /

PURGE_SQL = text("""
    UPDATE payments
    SET bank_name = NULL, account_no = NULL, amount = NULL, payment_date = NULL,
        reference_no = NULL, payee_name = NULL, nic_masked = NULL
    WHERE created_at < DATE_SUB(NOW(), INTERVAL 12 HOUR)
      AND (status = 'PENDING'
           OR (status = 'REJECTED' AND reason IN ('quality_failed', 'ocr_incomplete')))
""")

TIMEOUT_SQL = text("""
    UPDATE payments
    SET status = 'ADVANCED_CHECKING', reason = 'sms_timeout'
    WHERE status = 'AWAITING_SMS'
      AND created_at < DATE_SUB(NOW(), INTERVAL :minutes MINUTE)
""")


def purge_stale_extracted_data():
    with SessionLocal() as db:
        db.execute(PURGE_SQL)
        db.commit()


def escalate_timed_out_sms_waits():
    """Payments still AWAITING_SMS past the tolerance window get routed to Advanced
    Checking, matching the 'SMS fails to arrive -> alert business, route to Advanced
    Checking' rule from the pipeline spec.
    TODO: push an actual business alert (email/Slack/dashboard notification) here --
    right now the row only surfaces via the dashboard's active-processes list."""
    with SessionLocal() as db:
        db.execute(TIMEOUT_SQL, {"minutes": SMS_TOLERANCE_MINUTES})
        db.commit()
