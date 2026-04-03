import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Text, DateTime,
    Boolean, Enum as SQLEnum, ForeignKey, JSON, LargeBinary, TypeDecorator, Index
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
    MANAGER = "manager"
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
    DUPLICATE = "duplicate"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ──── Users (SRS Section 5.1) ────
class User(Base):
    __tablename__ = "users"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(SQLEnum(UserRole), default=UserRole.VIEWER)
    is_active = Column(Boolean, default=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    sso_provider = Column(String(100), nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reviews = relationship("AuditReview", back_populates="reviewer")


# ──── Invoices (SRS Section 5.1) ────
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    # File metadata
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_hash = Column(String(128), index=True)  # SHA-256 hash (sha256_hash)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    phash = Column(String(256), index=True)  # Perceptual hash

    # OCR extracted data (denormalized for fast access)
    vendor_name = Column(String(500))
    invoice_number = Column(String(200), index=True)
    invoice_date = Column(DateTime)
    due_date = Column(DateTime)
    total_amount = Column(Float)
    currency = Column(String(10), default="USD")
    tax_amount = Column(Float)
    subtotal = Column(Float)
    buyer_name = Column(String(500))
    vendor_address = Column(Text)
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
    risk_class = Column(String(20), default="low")  # SRS: risk_class column

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
    tenant_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    # Encryption flag
    is_encrypted = Column(Boolean, default=False)

    # Relationships
    reviews = relationship("AuditReview", back_populates="invoice")
    audit_logs = relationship("AuditLog", back_populates="invoice")
    extracted_data_rel = relationship("ExtractedData", back_populates="invoice", uselist=False)
    forgery_results = relationship("ForgeryResult", back_populates="invoice", uselist=False)
    duplicate_results = relationship("DuplicateResult", back_populates="invoice")
    anomaly_results = relationship("AnomalyResult", back_populates="invoice", uselist=False)

    # Partial index for pending_review optimization
    __table_args__ = (
        Index("ix_invoices_pending_review", "status", postgresql_where=(status == "under_review")),
    )


# ──── Extracted Data (SRS Section 5.1 - extracted_data table) ────
class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    invoice_number = Column(String(200))
    vendor_name = Column(String(500))
    vendor_address = Column(Text)
    invoice_date = Column(DateTime)
    due_date = Column(DateTime)
    line_items = Column(JSON)  # JSONB in PostgreSQL
    subtotal = Column(Float)
    tax = Column(Float)
    total = Column(Float)
    currency = Column(String(10), default="USD")
    payment_terms = Column(String(200))
    confidence_score = Column(Float)
    raw_ocr_output = Column(Text)

    invoice = relationship("Invoice", back_populates="extracted_data_rel")

    __table_args__ = (
        Index("ix_extracted_vendor_total_date", "vendor_name", "total", "invoice_date"),
    )


# ──── Forgery Results (SRS Section 5.1 - forgery_results table) ────
class ForgeryResult(Base):
    __tablename__ = "forgery_results"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    ela_score = Column(Float, default=0.0)
    font_consistency_score = Column(Float, default=0.0)
    metadata_anomaly_score = Column(Float, default=0.0)
    logo_match_score = Column(Float, default=0.0)
    copy_paste_score = Column(Float, default=0.0)
    heatmap_path = Column(String(1000))  # Path to generated heatmap image
    overall_forgery_score = Column(Float, default=0.0)
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="forgery_results")


# ──── Duplicate Results (SRS Section 5.1 - duplicate_results table) ────
class DuplicateResult(Base):
    __tablename__ = "duplicate_results"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    matched_invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=True)
    levenshtein_score = Column(Float, default=0.0)
    semantic_score = Column(Float, default=0.0)
    exact_match_fields = Column(JSON)
    duplicate_probability = Column(Float, default=0.0)
    match_type = Column(String(50))  # exact_hash, perceptual, fuzzy, semantic
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="duplicate_results", foreign_keys=[invoice_id])


# ──── Anomaly Results (SRS Section 5.1 - anomaly_results table) ────
class AnomalyResult(Base):
    __tablename__ = "anomaly_results"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    isolation_forest_score = Column(Float, default=0.0)
    autoencoder_error = Column(Float, default=0.0)
    combined_anomaly_score = Column(Float, default=0.0)
    feature_importances = Column(JSON)
    heuristic_flags = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="anomaly_results")


# ──── Page Index (SRS Section 5.1 - Vectorless RAG) ────
class PageIndex(Base):
    __tablename__ = "page_index"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    section_heading = Column(String(500))
    content_type = Column(String(100))  # text, table, heading, image
    byte_offset_start = Column(Integer)
    byte_offset_end = Column(Integer)
    content_preview = Column(Text)  # First 500 chars of section
    created_at = Column(DateTime, default=datetime.utcnow)


# ──── Document TOC (SRS Section 5.1 - Vectorless RAG) ────
class DocumentTOC(Base):
    __tablename__ = "document_toc"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False, index=True)
    entry_title = Column(String(500), nullable=False)
    page_number = Column(Integer, nullable=False)
    level = Column(Integer, default=1)  # Heading level (1=H1, 2=H2, etc)
    parent_entry_id = Column(UUIDType, ForeignKey("document_toc.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ──── Audit Log (SRS Section 5.1 - immutable) ────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=True)
    user_id = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))  # invoice, user, model, system
    entity_id = Column(String(100))
    details = Column(JSON)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    invoice = relationship("Invoice", back_populates="audit_logs")


# ──── Audit Review (SRS Section 5.1) ────
class AuditReview(Base):
    __tablename__ = "audit_reviews"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=False)
    reviewer_id = Column(UUIDType, ForeignKey("users.id"), nullable=False)
    decision = Column(String(50))  # approved, rejected, escalated, request_info
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")


# ──── Vendor Templates (SRS Section 5.1) ────
class VendorTemplate(Base):
    __tablename__ = "vendor_templates"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    vendor_name = Column(String(500), nullable=False, index=True)
    logo_image_path = Column(String(1000))
    header_template_path = Column(String(1000))
    registered_by = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    tenant_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ──── Webhook Configuration (SRS Section 6.2) ────
class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    url = Column(String(2000), nullable=False)
    events = Column(JSON)  # List of event types to subscribe to
    secret = Column(String(255))  # For HMAC signature verification
    is_active = Column(Boolean, default=True)
    tenant_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ──── RAG Retrieval Log (SRS Section 2.3 - audit trail) ────
class RAGRetrievalLog(Base):
    __tablename__ = "rag_retrieval_logs"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    query_text = Column(Text)
    document_id = Column(UUIDType, ForeignKey("invoices.id"), nullable=True)
    page_number = Column(Integer)
    section_identifier = Column(String(500))
    byte_offset = Column(Integer)
    query_context = Column(Text)
    user_id = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
