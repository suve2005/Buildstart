import hashlib
import logging
from decimal import Decimal

from database import PaymentRecord, OrderRecord

logger = logging.getLogger(__name__)

# Asymmetric tolerances (business currency, e.g. LKR).
# Underpayment loses revenue directly, so it's zero tolerance. Overpayment (rounding,
# a customer paying a bit extra) gets a small buffer before it's treated as suspicious.
TOLERANCE_UNDER = Decimal("0.00")
TOLERANCE_OVER = Decimal("100.00")

# Every status a payment can sit in before a final APPROVED/REJECTED verdict. Reuse
# detection must check all of these, or a duplicate submission can slip through
# whichever status was left out.
ACTIVE_STATUSES = ("APPROVED", "AWAITING_SMS", "NEEDS_VERIFICATION", "ADVANCED_CHECKING")


def _generate_fingerprint(account_no, amount, payment_date, reference_no):
    """Idempotency key for catching the same real bank transfer reused across submissions.
    Returns None if any component is missing -- callers must treat None as 'reuse can't
    be checked', not as 'no reuse found'."""
    if not all([account_no, amount, payment_date, reference_no]):
        return None
    raw = f"{account_no}|{amount}|{payment_date.date()}|{reference_no}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _find_order(db_session, phone_number: str, order_id, amount):
    """Resolves which order this payment is for.

    - order_id given (bot flow supplied it): use it directly.
    - Otherwise, look up orders awaiting payment for this phone number:
        0 orders  -> no order
        1 order   -> use it
        2+ orders -> try to disambiguate by matching the extracted amount to exactly
                     one order's expected_amount; still not unique -> ambiguous
    """
    if order_id is not None:
        order = db_session.query(OrderRecord).filter(
            OrderRecord.id == order_id, OrderRecord.status == "AWAITING_PAYMENT"
        ).first()
        return ("found", order) if order else ("not_found", None)

    orders = db_session.query(OrderRecord).filter(
        OrderRecord.phone_number == phone_number, OrderRecord.status == "AWAITING_PAYMENT"
    ).all()

    if not orders:
        return "none", None
    if len(orders) == 1:
        return "found", orders[0]

    if amount is not None:
        amount_matches = [o for o in orders if o.expected_amount == amount]
        if len(amount_matches) == 1:
            return "found", amount_matches[0]
    return "ambiguous", None


def validate_payment(db_session, phone_number: str, extracted_data: dict, order_id=None) -> dict:
    account_no = extracted_data.get("account_no")
    amount = extracted_data.get("amount")
    payment_date = extracted_data.get("payment_date")
    reference_no = extracted_data.get("reference_no")

    fingerprint = _generate_fingerprint(account_no, amount, payment_date, reference_no)
    if fingerprint is None:
        # Can't rule out reuse without a fingerprint. Logged so the gap is visible
        # rather than silently skipped -- should be rare now that reference_no is
        # mandatory for every category (see ocr_service.MANDATORY_BY_CATEGORY).
        logger.warning("No fingerprint for phone %s (missing OCR field) -- "
                        "reused-payment check skipped for this submission", phone_number)
    else:
        existing_tx = db_session.query(PaymentRecord).filter(
            PaymentRecord.transaction_fingerprint == fingerprint,
            PaymentRecord.status.in_(ACTIVE_STATUSES),
        ).first()
        if existing_tx:
            return {
                "is_valid": False, "status": "REJECTED", "reason": "reused_payment",
                "message": "This payment transaction has already been used for another order.",
                "fingerprint": fingerprint,
            }

    outcome, order = _find_order(db_session, phone_number, order_id, amount)

    if outcome == "not_found":
        return {
            "is_valid": False, "status": "NEEDS_VERIFICATION", "reason": "order_not_found",
            "message": "We couldn't match this to your order. Our team will review this.",
            "fingerprint": fingerprint,
        }
    if outcome == "none":
        return {
            "is_valid": False, "status": "NEEDS_VERIFICATION", "reason": "no_active_order",
            "message": "We couldn't find a pending order for your number. Our team will review this.",
            "fingerprint": fingerprint,
        }
    if outcome == "ambiguous":
        return {
            "is_valid": False, "status": "NEEDS_VERIFICATION", "reason": "ambiguous_order",
            "message": "You have more than one pending order; our team will confirm which one this covers.",
            "fingerprint": fingerprint,
        }

    if account_no != order.business_account:
        return {
            "is_valid": False, "status": "REJECTED", "reason": "wrong_account",
            "message": "The payment was made to an incorrect bank account. Please check the details.",
            "fingerprint": fingerprint,
        }

    diff = amount - order.expected_amount
    if diff < -TOLERANCE_UNDER:
        return {
            "is_valid": False, "status": "REJECTED", "reason": "underpaid",
            "message": "The paid amount is less than your order total. Please pay the exact amount.",
            "fingerprint": fingerprint,
        }
    if diff > TOLERANCE_OVER:
        return {
            "is_valid": False, "status": "REJECTED", "reason": "overpaid",
            "message": "The paid amount significantly exceeds your order total. Please contact support.",
            "fingerprint": fingerprint,
        }

    reason = "minor_amount_discrepancy" if diff != Decimal("0.00") else None
    return {
        "is_valid": True, "status": "VALIDATED", "reason": reason,
        "message": None, "fingerprint": fingerprint, "order_id": order.id,
    }
