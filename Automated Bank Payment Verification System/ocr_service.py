import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Dynamic requirements per category. reference_no is now mandatory for PHYSICAL_SLIP too:
# it's what the reused-payment fingerprint (validation_service) relies on, and physical
# slip reuse is exactly the fraud pattern that check exists to catch.
MANDATORY_BY_CATEGORY = {
    "DIGITAL": ("amount", "account_no", "reference_no", "payment_date"),
    "PHYSICAL_SLIP": ("amount", "account_no", "reference_no", "payment_date"),
    "ATM_RECEIPT": ("amount", "payment_date", "reference_no"),
}
DEFAULT_MANDATORY = ("amount", "account_no", "reference_no", "payment_date")

_AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d{1,2})?")
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",   # day-first (Sri Lanka)
    "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y",
)


def _mask_nic(nic):
    """Keeps only the last 4 characters. E.g. 987654321V -> ******321V."""
    if not nic:
        return None
    nic = nic.strip()
    return "*" * (len(nic) - 4) + nic[-4:] if len(nic) > 4 else "***"


def _normalize_amount(amount_str):
    """'Rs. 25,000.00' -> Decimal('25000.00'). Assumes '.' as the decimal separator --
    a EU-style 'Rs 25.000,00' slip would misparse. Known limitation, not fixed here."""
    if not amount_str:
        return None
    match = _AMOUNT_RE.search(str(amount_str))
    if not match:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def _parse_date(date_str):
    if not date_str:
        return None
    cleaned = " ".join(str(date_str).split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _normalize_reference(ref):
    """Strips whitespace/punctuation and uppercases, so 'REF-8392 01' and 'ref839201'
    fingerprint identically, and OCR noise (stray dashes/spaces) doesn't split one real
    reference number into two different fingerprints."""
    if not ref:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(ref)).upper()
    return cleaned or None


def _run_ocr(file_bytes: bytes, category: str):
    """
    MOCK: replace with a real OCR engine (AWS Textract, Google Vision, ...).
    Should return (raw_fields_dict, ocr_confidence 0-100). With a real engine, compute
    confidence as the MIN over the mandatory fields' own confidences (weakest link),
    not an average -- one unreadable mandatory field shouldn't be masked by three easy ones.
    """
    fake_ref = "REF" + hashlib.sha256(file_bytes).hexdigest()[:8].upper()  # differs per image
    raw = {
        "bank_name": "Commercial Bank",
        "account_no": "1002345678",
        "amount": "Rs. 25,000.00",
        "payment_date": datetime.now().strftime("%Y-%m-%d"),
        "reference_no": fake_ref,
        "payee_name": "Tech Corp",
        "nic_no": "987654321V",
    }
    return raw, 92.5


def process_slip_text(file_bytes: bytes, category: str) -> dict:
    raw, ocr_confidence = _run_ocr(file_bytes, category)

    data = {
        "bank_name": raw.get("bank_name"),
        "account_no": re.sub(r"\D", "", raw.get("account_no") or "") or None,
        "amount": _normalize_amount(raw.get("amount")),
        "payment_date": _parse_date(raw.get("payment_date")),
        "reference_no": _normalize_reference(raw.get("reference_no")),
        "payee_name": raw.get("payee_name"),
        "nic_masked": _mask_nic(raw.get("nic_no")),  # raw NIC never leaves this function
    }

    required = MANDATORY_BY_CATEGORY.get(category, DEFAULT_MANDATORY)
    missing = [f for f in required if not data.get(f)]
    if missing:
        ocr_confidence = min(ocr_confidence, 50.0)

    return {
        "is_complete": not missing,
        "missing_fields": missing,
        "data": data,
        "ocr_confidence": ocr_confidence,
    }
