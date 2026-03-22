import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Text, DateTime,
    Boolean, Enum as SQLEnum, ForeignKey, JSON, LargeBinary, TypeDecorator
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base


# ──── Cross-DB UUID Type (works with both PostgreSQL and SQLite) ────
class UUIDType(TypeDecorator):
    """Platform-independent UUID type. Uses String(36) for SQLite, native UUID for PG."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(str(value)) if not isinstance(value, uuid.UUID) else value
        return value


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    AUDITOR = "auditor"
    ANALYST = "analyst"
    VIEWER = "viewer"


class InvoiceStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    OCR_COMPLETE = "ocr_complete"
    ANALYZED = "analyzed"
    FLAGGED = "flagged"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNDER_REVIEW = "under_review"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class User(Base):
    __tablename__ = "users"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(SQLEnum(UserRole), default=UserRole.VIEWER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reviews = relationship("AuditReview", back_populates="reviewer")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    # File metadata
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_hash = Column(String(128), index=True)  # SHA-256 hash
    file_size = Column(Integer)
    mime_type = Column(String(100))

    # OCR extracted data
    vendor_name = Column(String(500))
    invoice_number = Column(String(200), index=True)
    invoice_date = Column(DateTime)
    due_date = Column(DateTime)
    total_amount = Column(Float)
    currency = Column(String(10), default="USD")
    tax_amount = Column(Float)
    subtotal = Column(Float)
    buyer_name = Column(String(500))
    raw_text = Column(Text)
    ocr_confidence = Column(Float)  # 0-100
    extracted_data = Column(JSON)  # Full structured extraction

    # Vector fingerprint
    fingerprint_vector = Column(LargeBinary)  # Serialized numpy array
    perceptual_hash = Column(String(128), index=True)

    # Fraud analysis results
    status = Column(SQLEnum(InvoiceStatus), default=InvoiceStatus.UPLOADED, index=True)
    risk_score = Column(Float, default=0.0)  # 0-100
    risk_level = Column(SQLEnum(RiskLevel), default=RiskLevel.LOW)

    # Individual scores
    forgery_score = Column(Float, default=0.0)
    duplicate_score = Column(Float, default=0.0)
    anomaly_score = Column(Float, default=0.0)

    # Fraud evidence
    fraud_evidence = Column(JSON)  # Detailed findings
    duplicate_of_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=True)
    similar_invoices = Column(JSON)  # List of similar invoice IDs with scores

    # Metadata
    uploaded_by = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Encryption flag
    is_encrypted = Column(Boolean, default=False)

    # Relationships
    reviews = relationship("AuditReview", back_populates="invoice")
    audit_logs = relationship("AuditLog", back_populates="invoice")


class AuditReview(Base):
    __tablename__ = "audit_reviews"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False)
    reviewer_id = Column(UUIDType, ForeignKey("users.id"), nullable=False)
    decision = Column(String(50))  # approved, rejected, escalated
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=True)
    user_id = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(JSON)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="audit_logs")
