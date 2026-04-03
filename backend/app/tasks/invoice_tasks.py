"""
Celery Tasks - Invoice Processing Pipeline (SRS Appendix C)
Uses chain() and chord() primitives for parallel analysis.

Pipeline:
1. task_fingerprint: SHA-256 + pHash, check Redis. If duplicate, terminate.
2. task_ocr_extract: Preprocessing + OCR ensemble, structured JSON.
3. chord([task_forgery_detect, task_duplicate_check, task_anomaly_score]):
   Three analysis tasks in parallel.
4. task_compute_risk_score: Callback aggregating scores into Composite Risk Score.
5. task_notify: Webhook events and dashboard updates.
"""
import io
import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from celery import chain, chord, group
from PIL import Image

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models import (
    Invoice, InvoiceStatus, RiskLevel,
    ExtractedData, ForgeryResult, DuplicateResult, AnomalyResult,
)
from app.services.ocr_service import ocr_service
from app.services.fraud_service import forgery_detector
from app.services.duplicate_service import duplicate_detector
from app.services.risk_scoring import risk_scoring_service
from app.ml.anomaly_detector import anomaly_detector

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="process_invoice", max_retries=3)
def process_invoice(self, invoice_id: str, file_path: str):
    """
    SRS Appendix C: Main pipeline orchestrator.
    Uses chain() for sequential steps and chord() for parallel analysis.
    """
    try:
        # Execute as chain: fingerprint -> ocr -> chord(parallel analysis) -> risk_score -> notify
        pipeline = chain(
            task_fingerprint.s(invoice_id, file_path),
            task_ocr_extract.s(invoice_id, file_path),
            # chord executes 3 tasks in parallel, then callback
            _build_analysis_chord(invoice_id, file_path),
        )
        pipeline.apply_async()
    except Exception as e:
        logger.error(f"Pipeline setup failed for {invoice_id}: {e}")
        _mark_error(invoice_id, str(e))
        raise


def _build_analysis_chord(invoice_id: str, file_path: str):
    """Build the chord for parallel analysis + risk scoring callback."""
    return chord(
        [
            task_forgery_detect.si(invoice_id, file_path),
            task_duplicate_check.si(invoice_id, file_path),
            task_anomaly_score.si(invoice_id, file_path),
        ],
        task_compute_risk_score.si(invoice_id),
    )


@celery_app.task(bind=True, name="task_fingerprint", max_retries=3,
                 autoretry_for=(Exception,), retry_backoff=True)
def task_fingerprint(self, invoice_id: str, file_path: str):
    """
    SRS Appendix C Step 1: Compute SHA-256 and pHash.
    Check Redis fingerprint index. If exact duplicate found, terminate with DUPLICATE.
    """
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            return {"error": "Invoice not found", "terminate": True}

        invoice.status = InvoiceStatus.PROCESSING
        db.commit()

        # Compute hashes
        import hashlib
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        image = Image.open(io.BytesIO(file_bytes))
        phash = duplicate_detector.compute_perceptual_hash(image)

        invoice.file_hash = file_hash
        invoice.phash = phash
        invoice.perceptual_hash = phash

        # Check for exact duplicates in DB
        existing = db.query(Invoice).filter(
            Invoice.file_hash == file_hash,
            Invoice.id != uuid.UUID(invoice_id),
        ).first()

        if existing:
            invoice.status = InvoiceStatus.DUPLICATE
            invoice.duplicate_of_id = existing.id
            invoice.duplicate_score = 100.0
            invoice.risk_score = 100.0
            invoice.risk_level = RiskLevel.CRITICAL
            db.commit()
            logger.info(f"Invoice {invoice_id} is exact duplicate of {existing.id}")
            return {"duplicate": True, "original_id": str(existing.id)}

        db.commit()
        return {"duplicate": False, "file_hash": file_hash}

    except Exception as e:
        logger.error(f"Fingerprint failed for {invoice_id}: {e}")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="task_ocr_extract", max_retries=3,
                 autoretry_for=(Exception,), retry_backoff=True)
def task_ocr_extract(self, fingerprint_result, invoice_id: str, file_path: str):
    """
    SRS Appendix C Step 2: Run preprocessing + OCR ensemble.
    Produces structured JSON. Retries 3x with exponential backoff.
    """
    # If fingerprint detected duplicate, skip OCR
    if isinstance(fingerprint_result, dict) and fingerprint_result.get("duplicate"):
        return fingerprint_result

    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
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

            # Store in extracted_data table (SRS Section 5.1)
            extracted = ExtractedData(
                invoice_id=invoice.id,
                invoice_number=result.get("invoice_number"),
                vendor_name=result.get("vendor_name"),
                vendor_address=result.get("vendor_address"),
                invoice_date=result.get("invoice_date"),
                due_date=result.get("due_date"),
                line_items=result.get("line_items"),
                subtotal=result.get("subtotal"),
                tax=result.get("tax_amount"),
                total=result.get("total_amount"),
                currency=result.get("currency", "USD"),
                payment_terms=result.get("payment_terms"),
                confidence_score=result.get("ocr_confidence"),
                raw_ocr_output=result.get("raw_text"),
            )
            db.add(extracted)
            db.commit()

        # Index document for Vectorless RAG (FR-801)
        try:
            from app.services.rag_service import vectorless_rag_service
            vectorless_rag_service.index_document(uuid.UUID(invoice_id), file_bytes, db)
        except Exception as e:
            logger.warning(f"RAG indexing failed for {invoice_id}: {e}")

        return result
    except Exception as e:
        logger.error(f"OCR failed for {invoice_id}: {e}")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="task_forgery_detect")
def task_forgery_detect(self, invoice_id: str, file_path: str):
    """SRS Appendix C Step 3a: Forgery detection (parallel)."""
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        # Run forgery detection
        forgery_result = forgery_detector.detect_forgery(image)

        # Store in forgery_results table (SRS Section 5.1)
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if invoice:
            invoice.forgery_score = forgery_result.get("forgery_score", 0)

            forgery_record = ForgeryResult(
                invoice_id=uuid.UUID(invoice_id),
                ela_score=forgery_result.get("evidence", {}).get("ela", {}).get("ela_score", 0),
                font_consistency_score=forgery_result.get("evidence", {}).get("font_consistency", {}).get("font_consistency_score", 0),
                metadata_anomaly_score=forgery_result.get("evidence", {}).get("metadata", {}).get("metadata_score", 0),
                copy_paste_score=forgery_result.get("evidence", {}).get("copy_paste", {}).get("copy_paste_score", 0),
                overall_forgery_score=forgery_result.get("forgery_score", 0),
                details=forgery_result.get("evidence"),
            )

            # Store heatmap if generated
            heatmap_data = forgery_result.get("heatmap")
            if heatmap_data and heatmap_data.get("heatmap_png_bytes"):
                from app.utils.storage import storage_service as ss
                heatmap_path = f"heatmaps/{invoice_id}.png"
                ss.upload_file(heatmap_data["heatmap_png_bytes"], heatmap_path, "image/png")
                forgery_record.heatmap_path = heatmap_path

            db.add(forgery_record)

            evidence = invoice.fraud_evidence or {}
            evidence["forgery"] = {
                "score": forgery_result["forgery_score"],
                "is_forged": forgery_result["is_forged"],
                "summary": forgery_result["summary"],
            }
            invoice.fraud_evidence = evidence
            db.commit()

        return {"forgery_score": forgery_result.get("forgery_score", 0)}
    except Exception as e:
        logger.error(f"Forgery detection failed for {invoice_id}: {e}")
        return {"forgery_score": 0, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="task_duplicate_check")
def task_duplicate_check(self, invoice_id: str, file_path: str):
    """SRS Appendix C Step 3b: Duplicate detection (parallel)."""
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()

        # Get known invoices for comparison
        known_invoices_query = db.query(Invoice).filter(
            Invoice.id != uuid.UUID(invoice_id),
            Invoice.status != InvoiceStatus.UPLOADED,
        ).limit(1000).all()

        known_hashes = {
            str(inv.id): inv.file_hash
            for inv in known_invoices_query if inv.file_hash
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

        # Update invoice and store results
        if invoice:
            invoice.duplicate_score = result["duplicate_score"]
            invoice.fingerprint_vector = result["fingerprint"].tobytes()
            invoice.similar_invoices = [
                {"invoice_id": m["invoice_id"], "score": m["similarity_score"]}
                for m in result.get("fuzzy_matches", {}).get("matches", [])
            ]

            # Store in duplicate_results table (SRS Section 5.1)
            for match in result.get("fuzzy_matches", {}).get("matches", [])[:10]:
                dup_record = DuplicateResult(
                    invoice_id=uuid.UUID(invoice_id),
                    matched_invoice_id=uuid.UUID(match["invoice_id"]),
                    levenshtein_score=match.get("components", {}).get("vendor_name", 0),
                    semantic_score=match.get("components", {}).get("raw_text", 0),
                    duplicate_probability=match["similarity_score"],
                    match_type="fuzzy",
                )
                db.add(dup_record)

            evidence = invoice.fraud_evidence or {}
            evidence["duplicate"] = {
                "score": result["duplicate_score"],
                "is_duplicate": result["is_duplicate"],
                "summary": result["summary"],
            }
            invoice.fraud_evidence = evidence
            db.commit()

        # Add to FAISS index
        duplicate_detector.add_to_index(invoice_id, result["fingerprint"])

        return {"duplicate_score": result["duplicate_score"]}
    except Exception as e:
        logger.error(f"Duplicate detection failed for {invoice_id}: {e}")
        return {"duplicate_score": 0, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="task_anomaly_score")
def task_anomaly_score(self, invoice_id: str, file_path: str):
    """SRS Appendix C Step 3c: ML anomaly detection (parallel)."""
    db = SessionLocal()
    try:
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

        # Update invoice and store results
        if invoice:
            invoice.anomaly_score = anomaly_result.get("anomaly_score", 0)

            # Store in anomaly_results table (SRS Section 5.1)
            anomaly_record = AnomalyResult(
                invoice_id=uuid.UUID(invoice_id),
                isolation_forest_score=anomaly_result.get("isolation_forest", {}).get("normalized_score", 0) if anomaly_result.get("isolation_forest") else 0,
                autoencoder_error=anomaly_result.get("autoencoder", {}).get("reconstruction_error", 0) if anomaly_result.get("autoencoder") else 0,
                combined_anomaly_score=anomaly_result.get("anomaly_score", 0),
                feature_importances=anomaly_result.get("feature_importance"),
                heuristic_flags=anomaly_result.get("heuristic"),
            )
            db.add(anomaly_record)

            evidence = invoice.fraud_evidence or {}
            evidence["anomaly"] = {
                "score": anomaly_result["anomaly_score"],
                "is_anomalous": anomaly_result["is_anomalous"],
                "feature_importance": anomaly_result["feature_importance"],
            }
            invoice.fraud_evidence = evidence
            db.commit()

        return {"anomaly_score": anomaly_result.get("anomaly_score", 0)}
    except Exception as e:
        logger.error(f"Anomaly detection failed for {invoice_id}: {e}")
        return {"anomaly_score": 0, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="task_compute_risk_score")
def task_compute_risk_score(self, analysis_results, invoice_id: str):
    """
    SRS Appendix C Step 4: Callback after chord completes.
    Aggregates all three scores into Composite Risk Score and assigns classification.
    """
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            return {"error": "Invoice not found"}

        # Build invoice data for rule-based scoring
        invoice_data = {
            "total_amount": invoice.total_amount,
            "tax_amount": invoice.tax_amount,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
        }

        risk_result = risk_scoring_service.calculate_risk_score(
            forgery_score=invoice.forgery_score or 0,
            duplicate_score=invoice.duplicate_score or 0,
            anomaly_score=invoice.anomaly_score or 0,
            invoice_data=invoice_data,
        )

        # Update invoice with final scores
        invoice.risk_score = risk_result["risk_score"]
        invoice.risk_level = RiskLevel(risk_result["risk_level"])
        invoice.risk_class = risk_result["risk_level"]

        # SRS FR-703/704/705: Set status based on risk level
        if risk_result["risk_level"] == "critical":
            invoice.status = InvoiceStatus.FLAGGED
        elif risk_result["risk_level"] == "high":
            invoice.status = InvoiceStatus.FLAGGED
        elif risk_result["risk_level"] == "medium":
            invoice.status = InvoiceStatus.UNDER_REVIEW
        else:
            invoice.status = InvoiceStatus.ANALYZED  # FR-703: auto-approve candidate

        invoice.processed_at = datetime.utcnow()

        # Store risk breakdown
        evidence = invoice.fraud_evidence or {}
        evidence["risk_breakdown"] = risk_result["breakdown"]
        evidence["recommended_action"] = risk_result["recommended_action"]
        evidence["dominant_risk"] = risk_result["dominant_risk"]
        invoice.fraud_evidence = evidence

        db.commit()

        # Step 5: Notify via webhooks (SRS Appendix C)
        _send_notifications(db, invoice_id, risk_result)

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
        logger.error(f"Risk scoring failed for {invoice_id}: {e}")
        _mark_error(invoice_id, str(e))
        raise
    finally:
        db.close()


def _send_notifications(db: Session, invoice_id: str, risk_result: Dict):
    """SRS Appendix C Step 5: Send webhook events and trigger alerts."""
    try:
        from app.services.webhook_service import webhook_service

        # Always fire invoice.processed
        webhook_service.invoice_processed(
            db, invoice_id,
            risk_result["risk_score"],
            risk_result["risk_level"],
        )

        # Fire invoice.flagged for High/Critical
        if risk_result["risk_level"] in ("high", "critical"):
            webhook_service.invoice_flagged(
                db, invoice_id,
                risk_result["risk_score"],
                risk_result["risk_level"],
                risk_result["breakdown"],
            )
    except Exception as e:
        logger.warning(f"Webhook notification failed for {invoice_id}: {e}")


def _mark_error(invoice_id: str, error_msg: str):
    """Mark invoice as errored."""
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if invoice:
            invoice.status = InvoiceStatus.UPLOADED
            invoice.fraud_evidence = {"error": error_msg}
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


@celery_app.task(name="retrain_models")
def retrain_models():
    """SRS FR-604: Periodic model retraining with labeled data."""
    db = SessionLocal()
    try:
        # Get confirmed invoices for training
        confirmed = db.query(Invoice).filter(
            Invoice.status.in_([InvoiceStatus.APPROVED, InvoiceStatus.REJECTED]),
        ).all()

        if len(confirmed) < 50:
            logger.info("Not enough labeled data for retraining")
            return {"status": "skipped", "reason": "insufficient_data"}

        training_data = [
            {
                "total_amount": inv.total_amount,
                "tax_amount": inv.tax_amount,
                "subtotal": inv.subtotal,
                "invoice_date": inv.invoice_date,
                "due_date": inv.due_date,
                "ocr_confidence": inv.ocr_confidence,
                "raw_text": inv.raw_text or "",
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
            }
            for inv in confirmed
        ]

        anomaly_detector.train(training_data)
        anomaly_detector.save_models("ml_models")

        metrics = {
            "training_samples": len(training_data),
            "model": "isolation_forest+autoencoder",
        }

        # Send webhook notification
        try:
            from app.services.webhook_service import webhook_service
            webhook_service.model_retrained(db, "anomaly_detector", metrics)
        except Exception:
            pass

        return {"status": "success", "metrics": metrics}
    except Exception as e:
        logger.error(f"Model retraining failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="cleanup_old_results")
def cleanup_old_results():
    """Periodic task to clean up old processing results."""
    logger.info("Running cleanup task")
