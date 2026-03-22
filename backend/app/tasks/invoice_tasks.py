"""
Celery Tasks - Invoice Processing Pipeline
Orchestrates OCR, fraud detection, and duplicate detection in async workflow
"""
import io
import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from celery import chain, group
from PIL import Image

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models import Invoice, InvoiceStatus, RiskLevel
from app.services.ocr_service import ocr_service
from app.services.fraud_service import forgery_detector
from app.services.duplicate_service import duplicate_detector
from app.services.risk_scoring import risk_scoring_service
from app.ml.anomaly_detector import anomaly_detector

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="process_invoice")
def process_invoice(self, invoice_id: str, file_path: str):
    """
    Main invoice processing pipeline.
    Orchestrates all analysis steps in sequence.
    """
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return {"error": "Invoice not found"}

        # Update status
        invoice.status = InvoiceStatus.PROCESSING
        db.commit()

        # Step 1: OCR
        self.update_state(state="PROGRESS", meta={"step": "ocr", "progress": 20})
        ocr_result = run_ocr(invoice_id, file_path)

        # Step 2: Fraud Detection (forgery + anomaly)
        self.update_state(state="PROGRESS", meta={"step": "fraud_detection", "progress": 50})
        fraud_result = run_fraud_detection(invoice_id, file_path)

        # Step 3: Duplicate Detection
        self.update_state(state="PROGRESS", meta={"step": "duplicate_detection", "progress": 75})
        duplicate_result = run_duplicate_detection(invoice_id, file_path)

        # Step 4: Risk Scoring
        self.update_state(state="PROGRESS", meta={"step": "risk_scoring", "progress": 90})
        
        # Refresh invoice data
        db.refresh(invoice)

        risk_result = risk_scoring_service.calculate_risk_score(
            forgery_score=invoice.forgery_score or 0,
            duplicate_score=invoice.duplicate_score or 0,
            anomaly_score=invoice.anomaly_score or 0,
            ocr_confidence=invoice.ocr_confidence or 50,
            metadata_flags=0,
        )

        # Update final scores
        invoice.risk_score = risk_result["risk_score"]
        invoice.risk_level = RiskLevel(risk_result["risk_level"])
        
        # Set final status based on risk
        if risk_result["risk_level"] == "critical":
            invoice.status = InvoiceStatus.FLAGGED
        elif risk_result["risk_level"] == "high":
            invoice.status = InvoiceStatus.FLAGGED
        elif risk_result["risk_level"] == "medium":
            invoice.status = InvoiceStatus.UNDER_REVIEW
        else:
            invoice.status = InvoiceStatus.ANALYZED

        invoice.processed_at = datetime.utcnow()
        
        # Store risk breakdown in fraud_evidence
        existing_evidence = invoice.fraud_evidence or {}
        existing_evidence["risk_breakdown"] = risk_result["breakdown"]
        existing_evidence["recommended_action"] = risk_result["recommended_action"]
        existing_evidence["dominant_risk"] = risk_result["dominant_risk"]
        invoice.fraud_evidence = existing_evidence
        
        db.commit()

        logger.info(
            f"Invoice {invoice_id} processed: "
            f"risk={risk_result['risk_score']}, level={risk_result['risk_level']}"
        )

        return {
            "invoice_id": invoice_id,
            "risk_score": risk_result["risk_score"],
            "risk_level": risk_result["risk_level"],
            "status": invoice.status.value,
        }

    except Exception as e:
        logger.error(f"Error processing invoice {invoice_id}: {e}")
        try:
            invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
            if invoice:
                invoice.status = InvoiceStatus.UPLOADED
                invoice.fraud_evidence = {"error": str(e)}
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


def run_ocr(invoice_id: str, file_path: str) -> Dict[str, Any]:
    """Run OCR on invoice image."""
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        
        # Download file from storage
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        # Run OCR
        result = ocr_service.extract_structured_data(image)

        # Update invoice with OCR results
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if invoice:
            invoice.vendor_name = result.get("vendor_name")
            invoice.invoice_number = result.get("invoice_number")
            invoice.invoice_date = result.get("invoice_date")
            invoice.due_date = result.get("due_date")
            invoice.total_amount = result.get("total_amount")
            invoice.tax_amount = result.get("tax_amount")
            invoice.subtotal = result.get("subtotal")
            invoice.buyer_name = result.get("buyer_name")
            invoice.raw_text = result.get("raw_text")
            invoice.ocr_confidence = result.get("ocr_confidence")
            invoice.extracted_data = result.get("extracted_fields")
            invoice.status = InvoiceStatus.OCR_COMPLETE
            db.commit()

        return result
    except Exception as e:
        logger.error(f"OCR failed for {invoice_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def run_fraud_detection(invoice_id: str, file_path: str) -> Dict[str, Any]:
    """Run forgery and anomaly detection."""
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service

        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        # Forgery detection
        forgery_result = forgery_detector.detect_forgery(image)

        # Anomaly detection (using OCR data)
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        invoice_data = {
            "total_amount": invoice.total_amount,
            "tax_amount": invoice.tax_amount,
            "subtotal": invoice.subtotal,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "ocr_confidence": invoice.ocr_confidence,
            "raw_text": invoice.raw_text,
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
        }
        anomaly_result = anomaly_detector.detect_anomaly(invoice_data)

        # Update invoice
        if invoice:
            invoice.forgery_score = forgery_result.get("forgery_score", 0)
            invoice.anomaly_score = anomaly_result.get("anomaly_score", 0)
            
            evidence = invoice.fraud_evidence or {}
            evidence["forgery"] = {
                "score": forgery_result["forgery_score"],
                "is_forged": forgery_result["is_forged"],
                "summary": forgery_result["summary"],
                "ela_score": forgery_result["evidence"]["ela"].get("ela_score"),
                "suspicious_regions": forgery_result["evidence"]["ela"].get("suspicious_regions", []),
            }
            evidence["anomaly"] = {
                "score": anomaly_result["anomaly_score"],
                "is_anomalous": anomaly_result["is_anomalous"],
                "feature_importance": anomaly_result["feature_importance"],
            }
            invoice.fraud_evidence = evidence
            db.commit()

        return {
            "forgery": forgery_result,
            "anomaly": anomaly_result,
        }
    except Exception as e:
        logger.error(f"Fraud detection failed for {invoice_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def run_duplicate_detection(invoice_id: str, file_path: str) -> Dict[str, Any]:
    """Run duplicate detection pipeline."""
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service

        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        
        # Get known hashes and invoices for comparison
        known_invoices_query = db.query(Invoice).filter(
            Invoice.id != uuid.UUID(invoice_id),
            Invoice.status != InvoiceStatus.UPLOADED,
        ).all()

        known_hashes = {
            str(inv.id): inv.file_hash
            for inv in known_invoices_query
            if inv.file_hash
        }

        known_invoices = [
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "total_amount": inv.total_amount,
                "invoice_date": inv.invoice_date,
                "raw_text": inv.raw_text[:500] if inv.raw_text else "",
            }
            for inv in known_invoices_query
        ]

        invoice_data = {
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
            "total_amount": invoice.total_amount,
            "invoice_date": invoice.invoice_date,
            "raw_text": invoice.raw_text[:500] if invoice.raw_text else "",
        }

        result = duplicate_detector.detect_duplicates(
            file_bytes=file_bytes,
            image=image,
            invoice_data=invoice_data,
            known_hashes=known_hashes,
            known_invoices=known_invoices,
        )

        # Update invoice
        if invoice:
            invoice.file_hash = result["file_hash"]
            invoice.perceptual_hash = result["perceptual_hash"]
            invoice.fingerprint_vector = result["fingerprint"].tobytes()
            invoice.duplicate_score = result["duplicate_score"]
            
            if result["exact_match"]["is_exact_duplicate"]:
                invoice.duplicate_of_id = uuid.UUID(result["exact_match"]["duplicate_of"])

            similar = []
            for match in result.get("fuzzy_matches", {}).get("matches", []):
                similar.append({
                    "invoice_id": match["invoice_id"],
                    "score": match["similarity_score"],
                })
            invoice.similar_invoices = similar

            evidence = invoice.fraud_evidence or {}
            evidence["duplicate"] = {
                "score": result["duplicate_score"],
                "is_duplicate": result["is_duplicate"],
                "summary": result["summary"],
                "exact_match": result["exact_match"]["is_exact_duplicate"],
                "fuzzy_match_count": result["fuzzy_matches"]["total_matches"],
            }
            invoice.fraud_evidence = evidence
            db.commit()

        # Add to FAISS index for future queries
        duplicate_detector.add_to_index(invoice_id, result["fingerprint"])

        return result
    except Exception as e:
        logger.error(f"Duplicate detection failed for {invoice_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="cleanup_old_results")
def cleanup_old_results():
    """Periodic task to clean up old processing results."""
    logger.info("Running cleanup task")
    # Placeholder for cleanup logic
    pass
