"""
Webhook & Event System (SRS Section 6.2)
Publishes events to configured webhook endpoints for integration with external systems.

Events:
- invoice.processed: Invoice completes analysis pipeline
- invoice.flagged: Invoice classified as High or Critical risk
- invoice.approved / invoice.rejected: Auditor decision
- model.retrained: ML model retraining complete
- system.alert: System health issues
"""
import json
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

import requests
from sqlalchemy.orm import Session

from app.models import WebhookConfig

logger = logging.getLogger(__name__)

# Thread pool for non-blocking webhook delivery
_executor = ThreadPoolExecutor(max_workers=4)


class WebhookService:
    """Publish events to configured webhook endpoints."""

    EVENT_TYPES = [
        "invoice.processed",
        "invoice.flagged",
        "invoice.approved",
        "invoice.rejected",
        "model.retrained",
        "system.alert",
    ]

    def publish_event(self, db: Session, event_type: str, payload: Dict[str, Any]):
        """Publish an event to all subscribed webhooks."""
        if event_type not in self.EVENT_TYPES:
            logger.warning(f"Unknown event type: {event_type}")
            return

        # Find active webhooks subscribed to this event
        configs = db.query(WebhookConfig).filter(
            WebhookConfig.is_active == True,
        ).all()

        for config in configs:
            events = config.events or []
            if event_type in events or "*" in events:
                _executor.submit(
                    self._deliver_webhook, config.url, config.secret,
                    event_type, payload
                )

    def _deliver_webhook(
        self, url: str, secret: Optional[str],
        event_type: str, payload: Dict[str, Any]
    ):
        """Deliver a webhook payload to a URL with optional HMAC signature."""
        body = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload,
        }
        body_json = json.dumps(body, default=str)

        headers = {
            "Content-Type": "application/json",
            "X-InvoiceFirewall-Event": event_type,
        }

        # HMAC signature for verification
        if secret:
            signature = hmac.new(
                secret.encode(), body_json.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-InvoiceFirewall-Signature"] = f"sha256={signature}"

        try:
            response = requests.post(
                url, data=body_json, headers=headers, timeout=10
            )
            if response.status_code >= 400:
                logger.warning(
                    f"Webhook delivery failed: {url} returned {response.status_code}"
                )
            else:
                logger.info(f"Webhook delivered: {event_type} -> {url}")
        except Exception as e:
            logger.error(f"Webhook delivery error: {url} - {e}")

    # ──── Convenience methods for common events ────

    def invoice_processed(self, db: Session, invoice_id: str,
                          risk_score: float, risk_level: str):
        """SRS 6.2: Fired when invoice completes analysis pipeline."""
        self.publish_event(db, "invoice.processed", {
            "invoice_id": invoice_id,
            "risk_score": risk_score,
            "risk_level": risk_level,
        })

    def invoice_flagged(self, db: Session, invoice_id: str,
                        risk_score: float, risk_level: str,
                        risk_breakdown: Dict[str, Any]):
        """SRS 6.2: Fired when invoice classified as High or Critical."""
        self.publish_event(db, "invoice.flagged", {
            "invoice_id": invoice_id,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "breakdown": risk_breakdown,
        })

    def invoice_approved(self, db: Session, invoice_id: str,
                         auditor_id: str, comments: str):
        """SRS 6.2: Fired on auditor approval."""
        self.publish_event(db, "invoice.approved", {
            "invoice_id": invoice_id,
            "auditor_id": auditor_id,
            "comments": comments,
        })

    def invoice_rejected(self, db: Session, invoice_id: str,
                         auditor_id: str, comments: str):
        """SRS 6.2: Fired on auditor rejection."""
        self.publish_event(db, "invoice.rejected", {
            "invoice_id": invoice_id,
            "auditor_id": auditor_id,
            "comments": comments,
        })

    def model_retrained(self, db: Session, model_name: str,
                        metrics: Dict[str, float]):
        """SRS 6.2: Fired upon successful ML model retraining."""
        self.publish_event(db, "model.retrained", {
            "model_name": model_name,
            "metrics": metrics,
        })

    def system_alert(self, db: Session, alert_type: str, message: str):
        """SRS 6.2: Fired on system health issues."""
        self.publish_event(db, "system.alert", {
            "alert_type": alert_type,
            "message": message,
        })


# Singleton
webhook_service = WebhookService()
