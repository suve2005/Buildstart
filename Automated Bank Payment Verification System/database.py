import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Numeric, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://blah:change_me@localhost:3306/payment_db") # change blah to root and change_me to pw

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class OrderRecord(Base):
    """MOCK: represents the business's internal database of customer orders."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(20), index=True)
    expected_amount = Column(Numeric(12, 2))
    business_account = Column(String(50))
    status = Column(String(20), default="AWAITING_PAYMENT")


class PaymentRecord(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    image_hash = Column(String(64), unique=True, index=True, nullable=False)
    phone_number = Column(String(20), index=True)
    status = Column(String(50), default="PENDING")
    reason = Column(String(100))
    category = Column(String(30))
    retry_count = Column(Integer, default=0, nullable=False)


    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)

    
    confidence_score = Column(Float, default=100.0)
    ocr_confidence = Column(Float)

    
    bank_name = Column(String(100))
    account_no = Column(String(50))
    amount = Column(Numeric(12, 2))
    payment_date = Column(DateTime)
    reference_no = Column(String(100), index=True)
    payee_name = Column(String(100))
    nic_masked = Column(String(20))  # raw NIC is never stored

  
    transaction_fingerprint = Column(String(64), unique=True, index=True, nullable=True)

    created_at = Column(DateTime, server_default=func.now())


class SMSRecord(Base):
    """Inbound bank SMS notifications, kept for audit and matched against AWAITING_SMS payments."""
    __tablename__ = "sms_messages"

    id = Column(Integer, primary_key=True)
    bank_name = Column(String(100))
    account_no = Column(String(50))
    amount = Column(Numeric(12, 2))
    raw_text = Column(String(500))
    matched_payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    received_at = Column(DateTime, server_default=func.now())


Base.metadata.create_all(bind=engine)
