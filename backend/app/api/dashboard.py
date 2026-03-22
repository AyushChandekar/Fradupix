"""
Dashboard API Routes
"""
from datetime import datetime, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_

from app.database import get_db
from app.models import Invoice, InvoiceStatus, RiskLevel
from app.schemas import DashboardStats, AlertItem, AlertsResponse
from app.api.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get dashboard statistics for the specified time range."""
    since = datetime.utcnow() - timedelta(days=days)
    
    query = db.query(Invoice).filter(Invoice.created_at >= since)
    
    total = query.count()
    
    flagged = query.filter(Invoice.status == InvoiceStatus.FLAGGED).count()
    approved = query.filter(Invoice.status == InvoiceStatus.APPROVED).count()
    rejected = query.filter(Invoice.status == InvoiceStatus.REJECTED).count()
    
    # Risk counts
    high_risk = query.filter(Invoice.risk_level == RiskLevel.HIGH).count()
    critical = query.filter(Invoice.risk_level == RiskLevel.CRITICAL).count()
    
    # Calculate averages
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


@router.get("/alerts", response_model=AlertsResponse)
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
        # Determine primary alert type
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


@router.get("/risk-distribution")
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


@router.get("/timeline")
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
        func.sum(case((Invoice.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]), 1), else_=0)).label("flagged"),
    ).filter(
        Invoice.created_at >= since,
    ).group_by(func.date(Invoice.created_at)).order_by("date").all()

    return [
        {
            "date": str(row.date),
            "total": row.total,
            "flagged": row.flagged,
        }
        for row in invoices
    ]
