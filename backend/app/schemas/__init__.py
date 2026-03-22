import uuid
from datetime import datetime, date
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, Field


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


# ──── Review Schemas ────
class ReviewCreate(BaseModel):
    decision: str  # approved, rejected, escalated
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
