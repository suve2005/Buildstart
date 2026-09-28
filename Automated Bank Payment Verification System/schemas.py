from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_hash: str
    phone_number: str
    status: str
    reason: Optional[str] = None
    category: Optional[str] = None
    retry_count: int
    order_id: Optional[int] = None

    confidence_score: Optional[float] = None
    ocr_confidence: Optional[float] = None

    bank_name: Optional[str] = None
    account_no: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_date: Optional[datetime] = None
    reference_no: Optional[str] = None
    payee_name: Optional[str] = None
    nic_masked: Optional[str] = None

    created_at: datetime

    @field_validator("confidence_score", "ocr_confidence")
    @classmethod
    def _round(cls, v):
        return round(v, 1) if v is not None else v


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_number: str
    expected_amount: Decimal
    business_account: str
    status: str


class PaymentDetailOut(BaseModel):
    payment: PaymentOut
    order: Optional[OrderOut] = None


class StatsOut(BaseModel):
    target_revenue: float
    verified_income: float
    discrepancy: float


class DecisionIn(BaseModel):
    decision: str  # "APPROVED" or "REJECTED"
    note: Optional[str] = None


class SMSIngestIn(BaseModel):
    bank_name: Optional[str] = None
    account_no: str
    amount: Decimal
    raw_text: Optional[str] = None
