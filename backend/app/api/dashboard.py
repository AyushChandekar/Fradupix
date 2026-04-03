"""
Dashboard & Analytics API Routes (SRS Section 6.1)
"""
from datetime import datetime, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_

from app.database import get_db
from app.models import Invoice, InvoiceStatus, RiskLevel, User, UserRole
from app.schemas import (
    DashboardStats, AlertItem, AlertsResponse,
    VendorRiskItem, VendorAnalyticsResponse,
)
from app.api.auth import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["Dashboard"])


# ──── GET /api/v1/analytics/dashboard (SRS FR-904) ────
@router.get("/analytics/dashboard", response_model=DashboardStats)
def get_dashboard_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate analytics: volume, detection rate, false positives, trends."""
    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(Invoice).filter(Invoice.created_at >= since)

    total = query.count()
    flagged = query.filter(Invoice.status == InvoiceStatus.FLAGGED).count()
    approved = query.filter(Invoice.status == InvoiceStatus.APPROVED).count()
    rejected = query.filter(Invoice.status == InvoiceStatus.REJECTED).count()
    high_risk = query.filter(Invoice.risk_level == RiskLevel.HIGH).count()
    critical = query.filter(Invoice.risk_level == RiskLevel.CRITICAL).count()

    avg_risk = db.query(func.avg(Invoice.risk_score)).filter(
        Invoice.created_at >= since,
        Invoice.risk_score.isnot(None),
    ).scalar() or 0

    total_amount = db.query(func.sum(Invoice.total_amount)).filter(
        Invoice.created_at >= since,
        Invoice.total_amount.isnot(None),
    ).scalar() or 0

    duplicates = query.filter(Invoice.duplicate_score > 80).count()

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    invoices_today = query.filter(Invoice.created_at >= today).count()

    return DashboardStats(
        total_invoices=total,
        flagged_invoices=flagged,
        approved_invoices=approved,
        rejected_invoices=rejected,
        avg_risk_score=round(float(avg_risk), 2),
        high_risk_count=high_risk,
        critical_count=critical,
        total_amount_processed=round(float(total_amount), 2),
        duplicates_detected=duplicates,
        invoices_today=invoices_today,
    )


# ──── GET /api/v1/analytics/vendors (SRS Section 6.1) ────
@router.get("/analytics/vendors", response_model=VendorAnalyticsResponse)
def get_vendor_analytics(
    days: int = Query(90, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.AUDITOR)),
):
    """Vendor risk rankings and flagging frequency."""

    since = datetime.utcnow() - timedelta(days=days)

    vendor_stats = db.query(
        Invoice.vendor_name,
        func.count(Invoice.id).label("total_invoices"),
        func.sum(case(
            (Invoice.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]), 1),
            else_=0
        )).label("flagged_count"),
        func.avg(Invoice.risk_score).label("avg_risk_score"),
        func.sum(Invoice.total_amount).label("total_amount"),
    ).filter(
        Invoice.created_at >= since,
        Invoice.vendor_name.isnot(None),
        Invoice.vendor_name != "",
    ).group_by(Invoice.vendor_name).order_by(
        func.avg(Invoice.risk_score).desc()
    ).all()

    total = len(vendor_stats)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = vendor_stats[start:end]

    vendors = []
    for v in paginated:
        total_inv = v.total_invoices or 1
        vendors.append(VendorRiskItem(
            vendor_name=v.vendor_name,
            total_invoices=v.total_invoices,
            flagged_count=v.flagged_count or 0,
            avg_risk_score=round(float(v.avg_risk_score or 0), 2),
            total_amount=round(float(v.total_amount or 0), 2),
            flag_rate=round((v.flagged_count or 0) / total_inv * 100, 2),
        ))

    return VendorAnalyticsResponse(vendors=vendors, total=total)


# ──── Dashboard Alerts ────
@router.get("/dashboard/alerts", response_model=AlertsResponse)
def get_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get active fraud alerts (high and critical risk invoices)."""
    query = db.query(Invoice).filter(
        Invoice.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]),
        Invoice.status.in_([InvoiceStatus.FLAGGED, InvoiceStatus.UNDER_REVIEW]),
    ).order_by(Invoice.risk_score.desc())

    total = query.count()
    invoices = query.offset((page - 1) * page_size).limit(page_size).all()

    alerts = []
    for inv in invoices:
        scores = {
            "forgery": inv.forgery_score or 0,
            "duplicate": inv.duplicate_score or 0,
            "anomaly": inv.anomaly_score or 0,
        }
        alert_type = max(scores, key=scores.get)

        evidence = inv.fraud_evidence or {}
        description = evidence.get(alert_type, {}).get(
            "summary", f"High {alert_type} risk detected"
        )

        alerts.append(AlertItem(
            id=inv.id,
            invoice_id=inv.id,
            filename=inv.filename,
            risk_score=inv.risk_score or 0,
            risk_level=inv.risk_level.value if inv.risk_level else "high",
            alert_type=alert_type,
            description=str(description)[:200],
            created_at=inv.created_at,
        ))

    return AlertsResponse(alerts=alerts, total=total)


# ──── Risk Distribution Chart Data ────
@router.get("/dashboard/risk-distribution")
def get_risk_distribution(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get risk level distribution for chart visualization."""
    since = datetime.utcnow() - timedelta(days=days)

    distribution = db.query(
        Invoice.risk_level,
        func.count(Invoice.id),
    ).filter(
        Invoice.created_at >= since,
        Invoice.risk_level.isnot(None),
    ).group_by(Invoice.risk_level).all()

    return {
        level.value if level else "unknown": count
        for level, count in distribution
    }


# ──── Timeline Chart Data ────
@router.get("/dashboard/timeline")
def get_timeline(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get invoice processing timeline for chart visualization."""
    since = datetime.utcnow() - timedelta(days=days)

    invoices = db.query(
        func.date(Invoice.created_at).label("date"),
        func.count(Invoice.id).label("total"),
        func.sum(case(
            (Invoice.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]), 1),
            else_=0
        )).label("flagged"),
    ).filter(
        Invoice.created_at >= since,
    ).group_by(func.date(Invoice.created_at)).order_by("date").all()

    return [
        {"date": str(row.date), "total": row.total, "flagged": row.flagged}
        for row in invoices
    ]


# ──── Dashboard Stats (legacy route for frontend compatibility) ────
@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats_legacy(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Legacy stats endpoint for frontend compatibility."""
    return get_dashboard_stats(days=days, db=db, current_user=current_user)
