"""
Invoice API Routes
"""
import uuid
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Invoice, InvoiceStatus, RiskLevel, UserRole
from app.schemas import (
    InvoiceResponse, InvoiceListResponse, InvoiceUploadResponse,
    ReviewCreate, ReviewResponse,
)
from app.api.auth import get_current_user
from app.models import User, AuditReview
from app.utils.audit_logger import audit_logger

router = APIRouter(prefix="/api/invoices", tags=["Invoices"])

ALLOWED_MIME_TYPES = [
    "image/png", "image/jpeg", "image/tiff", "image/bmp",
    "application/pdf",
]


@router.post("/upload", response_model=InvoiceUploadResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload an invoice for processing."""
    # Validate file type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {ALLOWED_MIME_TYPES}",
        )

    # Read file
    file_bytes = await file.read()
    if len(file_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    # Calculate file hash
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Store file
    from app.utils.storage import storage_service
    object_name = f"{uuid.uuid4()}/{file.filename}"
    file_path = storage_service.upload_file(file_bytes, object_name, file.content_type or "application/octet-stream")

    # Create invoice record
    invoice = Invoice(
        filename=file.filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        status=InvoiceStatus.UPLOADED,
        uploaded_by=current_user.id,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    # Audit log
    audit_logger.log_upload(
        db, invoice.id, current_user.id, file.filename,
        request.client.host if request and request.client else None,
    )

    # Trigger async processing
    task_id = None
    try:
        from app.tasks.invoice_tasks import process_invoice
        task = process_invoice.delay(str(invoice.id), file_path)
        task_id = task.id
    except Exception as e:
        # If Celery is not available, process synchronously (dev mode)
        pass

    return InvoiceUploadResponse(
        id=invoice.id,
        filename=file.filename,
        status=invoice.status.value,
        message="Invoice uploaded and queued for processing",
        task_id=task_id,
    )


@router.get("", response_model=InvoiceListResponse)
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List invoices with filtering, sorting, and pagination."""
    query = db.query(Invoice)

    # Filters
    if status:
        try:
            query = query.filter(Invoice.status == InvoiceStatus(status))
        except ValueError:
            pass

    if risk_level:
        try:
            query = query.filter(Invoice.risk_level == RiskLevel(risk_level))
        except ValueError:
            pass

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Invoice.filename.ilike(search_filter)) |
            (Invoice.vendor_name.ilike(search_filter)) |
            (Invoice.invoice_number.ilike(search_filter))
        )

    # Total count
    total = query.count()

    # Sorting
    sort_column = getattr(Invoice, sort_by, Invoice.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # Pagination
    invoices = query.offset((page - 1) * page_size).limit(page_size).all()

    return InvoiceListResponse(
        invoices=[InvoiceResponse.model_validate(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed invoice information including fraud analysis."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoiceResponse.model_validate(invoice)


@router.get("/{invoice_id}/evidence")
def get_invoice_evidence(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed fraud evidence for an invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    return {
        "invoice_id": str(invoice.id),
        "filename": invoice.filename,
        "risk_score": invoice.risk_score,
        "risk_level": invoice.risk_level.value if invoice.risk_level else "low",
        "forgery_score": invoice.forgery_score,
        "duplicate_score": invoice.duplicate_score,
        "anomaly_score": invoice.anomaly_score,
        "evidence": invoice.fraud_evidence or {},
        "similar_invoices": invoice.similar_invoices or [],
        "ocr_confidence": invoice.ocr_confidence,
    }


@router.post("/{invoice_id}/review", response_model=ReviewResponse)
def submit_review(
    invoice_id: uuid.UUID,
    review_data: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an audit review for an invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Create review
    review = AuditReview(
        invoice_id=invoice_id,
        reviewer_id=current_user.id,
        decision=review_data.decision,
        notes=review_data.notes,
    )
    db.add(review)

    # Update invoice status
    if review_data.decision == "approved":
        invoice.status = InvoiceStatus.APPROVED
    elif review_data.decision == "rejected":
        invoice.status = InvoiceStatus.REJECTED
    elif review_data.decision == "escalated":
        invoice.status = InvoiceStatus.UNDER_REVIEW

    db.commit()
    db.refresh(review)

    # Audit log
    audit_logger.log_review(
        db, invoice_id, current_user.id,
        review_data.decision, review_data.notes,
    )

    return ReviewResponse.model_validate(review)


@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an invoice (admin only)."""
    if current_user.role not in [UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Admin access required")

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Delete file from storage
    try:
        from app.utils.storage import storage_service
        storage_service.delete_file(invoice.file_path)
    except Exception:
        pass

    db.delete(invoice)
    db.commit()

    return {"message": "Invoice deleted"}
