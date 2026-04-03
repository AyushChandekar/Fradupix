"""
Invoice API Routes (SRS Section 6.1)
"""
import uuid
import hashlib
import zipfile
import io
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Invoice, InvoiceStatus, RiskLevel, UserRole,
    User, AuditReview, DuplicateResult, ForgeryResult,
)
from app.schemas import (
    InvoiceResponse, InvoiceListResponse, InvoiceUploadResponse,
    BatchUploadResponse, ReviewCreate, ReviewResponse,
    DuplicateMatchItem, DuplicateMatchResponse,
)
from app.api.auth import get_current_user, require_role
from app.utils.audit_logger import audit_logger
from app.config import get_settings

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])
settings = get_settings()

ALLOWED_MIME_TYPES = [
    "image/png", "image/jpeg", "image/tiff", "image/bmp",
    "application/pdf",
]


# ──── POST /api/v1/invoices/upload (SRS FR-101, FR-105, FR-106) ────
@router.post("/upload", response_model=InvoiceUploadResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.AUDITOR, UserRole.ANALYST)),
):
    """Upload a single invoice for processing. Returns tracking ID immediately."""
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {ALLOWED_MIME_TYPES}",
        )

    file_bytes = await file.read()
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    from app.utils.storage import storage_service
    object_name = f"{uuid.uuid4()}/{file.filename}"
    file_path = storage_service.upload_file(file_bytes, object_name, file.content_type or "application/octet-stream")

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

    audit_logger.log_upload(
        db, invoice.id, current_user.id, file.filename,
        request.client.host if request and request.client else None,
    )

    task_id = None
    try:
        from app.tasks.invoice_tasks import process_invoice
        task = process_invoice.delay(str(invoice.id), file_path)
        task_id = task.id
    except Exception:
        pass

    return InvoiceUploadResponse(
        id=invoice.id,
        filename=file.filename,
        status=invoice.status.value,
        message="Invoice uploaded and queued for processing",
        task_id=task_id,
    )


# ──── POST /api/v1/invoices/upload/batch (SRS FR-102) ────
@router.post("/upload/batch", response_model=BatchUploadResponse)
async def batch_upload_invoices(
    files: List[UploadFile] = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.AUDITOR, UserRole.ANALYST)),
):
    """Batch upload up to 1000 invoices per API call."""
    if len(files) > settings.BATCH_UPLOAD_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {settings.BATCH_UPLOAD_LIMIT})",
        )

    tracking_ids = []
    errors = []
    from app.utils.storage import storage_service

    for file in files:
        try:
            if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
                errors.append({"filename": file.filename, "error": f"Unsupported type: {file.content_type}"})
                continue

            file_bytes = await file.read()
            max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
            if len(file_bytes) > max_size:
                errors.append({"filename": file.filename, "error": "File too large"})
                continue

            file_hash = hashlib.sha256(file_bytes).hexdigest()
            object_name = f"{uuid.uuid4()}/{file.filename}"
            file_path = storage_service.upload_file(file_bytes, object_name, file.content_type or "application/octet-stream")

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

            task_id = None
            try:
                from app.tasks.invoice_tasks import process_invoice
                task = process_invoice.delay(str(invoice.id), file_path)
                task_id = task.id
            except Exception:
                pass

            tracking_ids.append({
                "id": str(invoice.id),
                "filename": file.filename,
                "task_id": task_id,
            })
        except Exception as e:
            errors.append({"filename": file.filename, "error": str(e)})

    return BatchUploadResponse(
        uploaded=len(tracking_ids),
        tracking_ids=tracking_ids,
        errors=errors,
    )


# ──── GET /api/v1/invoices/{id} ────
@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve invoice details with full analysis results."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return InvoiceResponse.model_validate(invoice)


# ──── GET /api/v1/invoices ────
@router.get("", response_model=InvoiceListResponse)
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    risk_class: Optional[str] = None,
    vendor: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List invoices with filtering (status, risk_class, date range, vendor)."""
    query = db.query(Invoice)

    if status:
        try:
            query = query.filter(Invoice.status == InvoiceStatus(status))
        except ValueError:
            pass

    if risk_level or risk_class:
        level = risk_level or risk_class
        try:
            query = query.filter(Invoice.risk_level == RiskLevel(level))
        except ValueError:
            pass

    if vendor:
        query = query.filter(Invoice.vendor_name.ilike(f"%{vendor}%"))

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Invoice.filename.ilike(search_filter)) |
            (Invoice.vendor_name.ilike(search_filter)) |
            (Invoice.invoice_number.ilike(search_filter))
        )

    if date_from:
        query = query.filter(Invoice.created_at >= date_from)
    if date_to:
        query = query.filter(Invoice.created_at <= date_to)

    total = query.count()

    sort_column = getattr(Invoice, sort_by, Invoice.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    invoices = query.offset((page - 1) * page_size).limit(page_size).all()

    return InvoiceListResponse(
        invoices=[InvoiceResponse.model_validate(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
    )


# ──── PATCH /api/v1/invoices/{id}/review (SRS FR-903) ────
@router.patch("/{invoice_id}/review", response_model=ReviewResponse)
def submit_review(
    invoice_id: uuid.UUID,
    review_data: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.AUDITOR)),
):
    """Submit auditor decision (approve/reject/escalate) with comments."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    review = AuditReview(
        invoice_id=invoice_id,
        reviewer_id=current_user.id,
        decision=review_data.decision,
        notes=review_data.notes,
    )
    db.add(review)

    if review_data.decision == "approved":
        invoice.status = InvoiceStatus.APPROVED
    elif review_data.decision == "rejected":
        invoice.status = InvoiceStatus.REJECTED
    elif review_data.decision == "escalated":
        invoice.status = InvoiceStatus.UNDER_REVIEW

    db.commit()
    db.refresh(review)

    audit_logger.log_review(db, invoice_id, current_user.id, review_data.decision, review_data.notes)

    # Webhook notification (SRS Section 6.2)
    try:
        from app.services.webhook_service import webhook_service
        if review_data.decision == "approved":
            webhook_service.invoice_approved(db, str(invoice_id), str(current_user.id), review_data.notes or "")
        elif review_data.decision == "rejected":
            webhook_service.invoice_rejected(db, str(invoice_id), str(current_user.id), review_data.notes or "")
    except Exception:
        pass

    return ReviewResponse.model_validate(review)


# ──── GET /api/v1/invoices/{id}/heatmap (SRS FR-405) ────
@router.get("/{invoice_id}/heatmap")
def get_invoice_heatmap(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve forgery detection heatmap overlay image."""
    forgery = db.query(ForgeryResult).filter(
        ForgeryResult.invoice_id == invoice_id
    ).first()

    if not forgery or not forgery.heatmap_path:
        raise HTTPException(status_code=404, detail="Heatmap not available")

    try:
        from app.utils.storage import storage_service
        heatmap_bytes = storage_service.download_file(forgery.heatmap_path)
        return Response(content=heatmap_bytes, media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Heatmap file not found")


# ──── GET /api/v1/invoices/{id}/duplicates (SRS FR-505) ────
@router.get("/{invoice_id}/duplicates", response_model=DuplicateMatchResponse)
def get_invoice_duplicates(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List suspected duplicate matches with similarity scores."""
    duplicates = db.query(DuplicateResult).filter(
        DuplicateResult.invoice_id == invoice_id
    ).order_by(DuplicateResult.duplicate_probability.desc()).all()

    matches = [
        DuplicateMatchItem(
            matched_invoice_id=d.matched_invoice_id,
            match_type=d.match_type or "fuzzy",
            levenshtein_score=d.levenshtein_score or 0,
            semantic_score=d.semantic_score or 0,
            duplicate_probability=d.duplicate_probability or 0,
        )
        for d in duplicates
    ]

    return DuplicateMatchResponse(
        invoice_id=invoice_id,
        matches=matches,
        total_matches=len(matches),
    )


# ──── GET /api/v1/invoices/{id}/evidence ────
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


# ──── DELETE /api/v1/invoices/{id} ────
@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Delete an invoice (admin only)."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    try:
        from app.utils.storage import storage_service
        storage_service.delete_file(invoice.file_path)
    except Exception:
        pass

    db.delete(invoice)
    db.commit()

    return {"message": "Invoice deleted"}
