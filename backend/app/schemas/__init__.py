import uuid
from datetime import datetime, date
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


# ──── Auth Schemas ────
class UserCreate(BaseModel):
    email: str
    username: str
    password: str
    full_name: Optional[str] = None
    role: str = "viewer"


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserResponse


# ──── Invoice Schemas ────
class InvoiceBase(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    currency: str = "USD"


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_hash: Optional[str]
    status: str
    risk_score: float
    risk_level: str

    # OCR Data
    vendor_name: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[datetime]
    due_date: Optional[datetime]
    total_amount: Optional[float]
    currency: Optional[str]
    tax_amount: Optional[float]
    subtotal: Optional[float]
    buyer_name: Optional[str]
    ocr_confidence: Optional[float]

    # Fraud scores
    forgery_score: float
    duplicate_score: float
    anomaly_score: float
    fraud_evidence: Optional[dict]
    similar_invoices: Optional[list]

    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


class InvoiceListResponse(BaseModel):
    invoices: List[InvoiceResponse]
    total: int
    page: int
    page_size: int


class InvoiceUploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    message: str
    task_id: Optional[str] = None


class BatchUploadResponse(BaseModel):
    uploaded: int
    tracking_ids: List[Dict[str, Any]]
    errors: List[Dict[str, str]] = []


# ──── Dashboard Schemas ────
class DashboardStats(BaseModel):
    total_invoices: int
    flagged_invoices: int
    approved_invoices: int
    rejected_invoices: int
    avg_risk_score: float
    high_risk_count: int
    critical_count: int
    total_amount_processed: float
    duplicates_detected: int
    invoices_today: int


class AlertItem(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    filename: str
    risk_score: float
    risk_level: str
    alert_type: str  # forgery, duplicate, anomaly
    description: str
    created_at: datetime


class AlertsResponse(BaseModel):
    alerts: List[AlertItem]
    total: int


class VendorRiskItem(BaseModel):
    vendor_name: str
    total_invoices: int
    flagged_count: int
    avg_risk_score: float
    total_amount: float
    flag_rate: float


class VendorAnalyticsResponse(BaseModel):
    vendors: List[VendorRiskItem]
    total: int


# ──── Review Schemas ────
class ReviewCreate(BaseModel):
    decision: str  # approved, rejected, escalated, request_info
    notes: Optional[str] = None


class ReviewResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ──── Vectorless RAG Schemas (SRS FR-800) ────
class DocumentQueryRequest(BaseModel):
    query: str
    document_id: Optional[uuid.UUID] = None
    target_type: Optional[str] = None  # pricing, amounts, dates, terms


class DocumentQueryResult(BaseModel):
    document_id: uuid.UUID
    page_number: int
    section_heading: Optional[str]
    content_preview: str
    relevance_score: float


class DocumentQueryResponse(BaseModel):
    query: str
    results: List[DocumentQueryResult]
    total_results: int


class TOCEntry(BaseModel):
    id: uuid.UUID
    entry_title: str
    page_number: int
    level: int

    class Config:
        from_attributes = True


class DocumentTOCResponse(BaseModel):
    document_id: uuid.UUID
    entries: List[TOCEntry]


# ──── Duplicate Comparison Schemas (SRS FR-505) ────
class DuplicateMatchItem(BaseModel):
    matched_invoice_id: uuid.UUID
    match_type: str
    levenshtein_score: float
    semantic_score: float
    duplicate_probability: float
    field_comparison: Optional[Dict[str, Any]] = None


class DuplicateMatchResponse(BaseModel):
    invoice_id: uuid.UUID
    matches: List[DuplicateMatchItem]
    total_matches: int


# ──── ML Model Schemas (SRS FR-606) ────
class ModelMetricsResponse(BaseModel):
    model_name: str
    precision: float
    recall: float
    f1_score: float
    auc_roc: float
    training_samples: int
    last_trained: Optional[datetime]
    contamination_rate: float


class ModelRetrainRequest(BaseModel):
    force: bool = False


class ModelRetrainResponse(BaseModel):
    status: str
    message: str
    metrics: Optional[ModelMetricsResponse] = None


# ──── Audit Log Schemas (SRS Section 5.1) ────
class AuditLogEntry(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    details: Optional[dict]
    user_id: Optional[uuid.UUID]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    entries: List[AuditLogEntry]
    total: int
    page: int
    page_size: int


# ──── Webhook Schemas (SRS Section 6.2) ────
class WebhookConfigCreate(BaseModel):
    url: str
    events: List[str]  # invoice.processed, invoice.flagged, etc.
    secret: Optional[str] = None


class WebhookConfigResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: List[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ──── Risk Configuration Schemas (SRS FR-706) ────
class RiskWeightsConfig(BaseModel):
    forgery_weight: float = 0.30
    duplicate_weight: float = 0.25
    anomaly_weight: float = 0.25
    rules_weight: float = 0.20


class RiskThresholdsConfig(BaseModel):
    low_max: int = 30
    medium_max: int = 60
    high_max: int = 85
    critical_max: int = 100
