"""
Audit Logger - Track all actions for compliance (SRS Section 11.3)
Immutable audit trail with user ID, timestamp, action type, IP address, and outcome.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import AuditLog

logger = logging.getLogger(__name__)


class AuditLogger:
    """Log all system actions for compliance and audit trail."""

    def log(
        self,
        db: Session,
        action: str,
        invoice_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ):
        """Create an immutable audit log entry."""
        try:
            log_entry = AuditLog(
                invoice_id=invoice_id,
                user_id=user_id,
                action=action,
                entity_type=entity_type or ("invoice" if invoice_id else "system"),
                entity_id=entity_id or (str(invoice_id) if invoice_id else None),
                details=details or {},
                ip_address=ip_address,
            )
            db.add(log_entry)
            db.commit()

            logger.info(f"Audit: {action} | entity={entity_type} | invoice={invoice_id} | user={user_id}")
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
            db.rollback()

    def log_upload(self, db: Session, invoice_id: uuid.UUID, user_id: uuid.UUID, filename: str, ip: str = None):
        self.log(db, "invoice_uploaded", invoice_id, user_id, "invoice", str(invoice_id), {"filename": filename}, ip)

    def log_processing(self, db: Session, invoice_id: uuid.UUID, step: str):
        self.log(db, f"processing_{step}", invoice_id, entity_type="invoice", details={"step": step})

    def log_review(self, db: Session, invoice_id: uuid.UUID, user_id: uuid.UUID, decision: str, notes: str = None):
        self.log(db, "invoice_reviewed", invoice_id, user_id, "invoice", str(invoice_id), {"decision": decision, "notes": notes})

    def log_login(self, db: Session, user_id: uuid.UUID, ip: str = None):
        self.log(db, "user_login", user_id=user_id, entity_type="user", entity_id=str(user_id), ip_address=ip)

    def log_model_retrain(self, db: Session, model_name: str, metrics: Dict):
        self.log(db, "model_retrained", entity_type="model", details={"model": model_name, "metrics": metrics})

    def log_config_change(self, db: Session, user_id: uuid.UUID, setting: str, value: Any):
        self.log(db, "config_changed", user_id=user_id, entity_type="config", details={"setting": setting, "value": str(value)})


# Singleton
audit_logger = AuditLogger()
