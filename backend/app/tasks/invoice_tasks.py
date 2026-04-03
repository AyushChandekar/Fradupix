"""
Celery Tasks - Invoice Processing Pipeline (SRS Appendix C)

Pipeline (simplified from SRS for reliability):
1. task_fingerprint: SHA-256 + pHash. If exact duplicate, terminate.
2. task_ocr_extract: Preprocessing + OCR ensemble, structured JSON.
3. task_forgery_detect: ELA, metadata, font consistency, heatmap.
4. task_duplicate_check: Hash, fuzzy, semantic, time-window.
5. task_anomaly_score: Isolation Forest + Autoencoder.
6. task_compute_risk_score: Aggregate all scores, classify, notify.

Steps 3-5 run in parallel via chord(), 6 is the chord callback.
"""
import io
import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from PIL import Image

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models import (
    Invoice, InvoiceStatus, RiskLevel,
    ExtractedData, ForgeryResult, DuplicateResult, AnomalyResult,
)

logger = logging.getLogger(__name__)


def _get_services():
    """Lazy import services to avoid circular imports at module level."""
    from app.services.ocr_service import ocr_service
    from app.services.fraud_service import forgery_detector
    from app.services.duplicate_service import duplicate_detector
    from app.services.risk_scoring import risk_scoring_service
    from app.ml.anomaly_detector import anomaly_detector
    return ocr_service, forgery_detector, duplicate_detector, risk_scoring_service, anomaly_detector


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="process_invoice", max_retries=3)
def process_invoice(self, invoice_id: str, file_path: str):
    """
    Main pipeline orchestrator.  Runs steps sequentially (1→2) then
    fans out steps 3-5 in parallel via chord, with step 6 as callback.
    """
    from celery import chord

    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return {"error": "Invoice not found"}

        invoice.status = InvoiceStatus.PROCESSING
        db.commit()
    finally:
        db.close()

    # Step 1: Fingerprint (synchronous – fast, decides whether to continue)
    fp_result = _run_fingerprint(invoice_id, file_path)
    if fp_result.get("duplicate"):
        return fp_result

    # Step 2: OCR (synchronous – must complete before analysis)
    _run_ocr(invoice_id, file_path)

    # Steps 3-5 in parallel, step 6 as callback
    try:
        analysis_chord = chord(
            [
                task_forgery_detect.si(invoice_id, file_path),
                task_duplicate_check.si(invoice_id, file_path),
                task_anomaly_score.si(invoice_id, file_path),
            ],
            task_compute_risk_score.si(invoice_id),
        )
        analysis_chord.apply_async()
    except Exception as e:
        # Fallback: run everything sequentially if chord fails
        logger.warning(f"Chord failed for {invoice_id}, running sequentially: {e}")
        task_forgery_detect(invoice_id, file_path)
        task_duplicate_check(invoice_id, file_path)
        task_anomaly_score(invoice_id, file_path)
        task_compute_risk_score(None, invoice_id)

    return {"invoice_id": invoice_id, "status": "processing"}


# ═══════════════════════════════════════════════════════════════════════
# STEP 1: FINGERPRINTING
# ═══════════════════════════════════════════════════════════════════════

def _run_fingerprint(invoice_id: str, file_path: str) -> dict:
    """Compute SHA-256 + pHash. Check for exact duplicates."""
    import hashlib
    _, _, duplicate_detector, _, _ = _get_services()
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            return {"error": "Invoice not found"}

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        image = Image.open(io.BytesIO(file_bytes))
        phash = duplicate_detector.compute_perceptual_hash(image)

        invoice.file_hash = file_hash
        invoice.phash = phash
        invoice.perceptual_hash = phash

        # Check exact duplicate in DB
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
            invoice.risk_class = "critical"
            invoice.processed_at = datetime.utcnow()
            db.commit()
            logger.info(f"Invoice {invoice_id} is exact duplicate of {existing.id}")
            return {"duplicate": True, "original_id": str(existing.id)}

        db.commit()
        return {"duplicate": False, "file_hash": file_hash}
    except Exception as e:
        logger.error(f"Fingerprint failed for {invoice_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# STEP 2: OCR EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def _run_ocr(invoice_id: str, file_path: str) -> dict:
    """Run OCR and store structured results."""
    ocr_service, _, _, _, _ = _get_services()
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        result = ocr_service.extract_structured_data(image)

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

        # Index for Vectorless RAG
        try:
            from app.services.rag_service import vectorless_rag_service
            vectorless_rag_service.index_document(uuid.UUID(invoice_id), file_bytes, db)
        except Exception as e:
            logger.warning(f"RAG indexing failed for {invoice_id}: {e}")

        return result
    except Exception as e:
        logger.error(f"OCR failed for {invoice_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# STEP 3a: FORGERY DETECTION  (runs in parallel)
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="task_forgery_detect")
def task_forgery_detect(invoice_id: str, file_path: str):
    """Forgery detection — ELA, metadata, font consistency, heatmap."""
    _, forgery_detector, _, _, _ = _get_services()
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        forgery_result = forgery_detector.detect_forgery(image)

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if invoice:
            invoice.forgery_score = forgery_result.get("forgery_score", 0)

            evidence_detail = forgery_result.get("evidence", {})
            forgery_record = ForgeryResult(
                invoice_id=uuid.UUID(invoice_id),
                ela_score=evidence_detail.get("ela", {}).get("ela_score", 0),
                font_consistency_score=evidence_detail.get("font_consistency", {}).get("font_consistency_score", 0),
                metadata_anomaly_score=evidence_detail.get("metadata", {}).get("metadata_score", 0),
                copy_paste_score=evidence_detail.get("copy_paste", {}).get("copy_paste_score", 0),
                overall_forgery_score=forgery_result.get("forgery_score", 0),
                details=evidence_detail,
            )

            # Store heatmap if generated
            heatmap_data = forgery_result.get("heatmap")
            if heatmap_data and isinstance(heatmap_data, dict) and heatmap_data.get("heatmap_png_bytes"):
                heatmap_path = f"heatmaps/{invoice_id}.png"
                storage_service.upload_file(heatmap_data["heatmap_png_bytes"], heatmap_path, "image/png")
                forgery_record.heatmap_path = heatmap_path

            db.add(forgery_record)

            evidence = invoice.fraud_evidence or {}
            evidence["forgery"] = {
                "score": forgery_result.get("forgery_score", 0),
                "is_forged": forgery_result.get("is_forged", False),
                "summary": forgery_result.get("summary", ""),
            }
            invoice.fraud_evidence = evidence
            db.commit()

        return {"forgery_score": forgery_result.get("forgery_score", 0)}
    except Exception as e:
        logger.error(f"Forgery detection failed for {invoice_id}: {e}")
        return {"forgery_score": 0, "error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# STEP 3b: DUPLICATE DETECTION  (runs in parallel)
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="task_duplicate_check")
def task_duplicate_check(invoice_id: str, file_path: str):
    """Duplicate detection — hash, fuzzy, TF-IDF semantic, time-window."""
    _, _, duplicate_detector, _, _ = _get_services()
    db = SessionLocal()
    try:
        from app.utils.storage import storage_service
        file_bytes = storage_service.download_file(file_path)
        image = Image.open(io.BytesIO(file_bytes))

        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()

        # Known invoices for comparison (limit 1000)
        known_query = db.query(Invoice).filter(
            Invoice.id != uuid.UUID(invoice_id),
            Invoice.status != InvoiceStatus.UPLOADED,
        ).limit(1000).all()

        known_hashes = {str(inv.id): inv.file_hash for inv in known_query if inv.file_hash}
        known_invoices = [
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "total_amount": inv.total_amount,
                "invoice_date": inv.invoice_date,
                "raw_text": (inv.raw_text or "")[:500],
            }
            for inv in known_query
        ]

        invoice_data = {
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
            "total_amount": invoice.total_amount,
            "invoice_date": invoice.invoice_date,
            "raw_text": (invoice.raw_text or "")[:500],
        }

        result = duplicate_detector.detect_duplicates(
            file_bytes=file_bytes,
            image=image,
            invoice_data=invoice_data,
            known_hashes=known_hashes,
            known_invoices=known_invoices,
        )

        if invoice:
            invoice.duplicate_score = result.get("duplicate_score", 0)
            invoice.fingerprint_vector = result["fingerprint"].tobytes()
            invoice.similar_invoices = [
                {"invoice_id": m["invoice_id"], "score": m["similarity_score"]}
                for m in result.get("fuzzy_matches", {}).get("matches", [])
            ]

            # Store in duplicate_results table
            for match in result.get("fuzzy_matches", {}).get("matches", [])[:10]:
                try:
                    dup_record = DuplicateResult(
                        invoice_id=uuid.UUID(invoice_id),
                        matched_invoice_id=uuid.UUID(match["invoice_id"]),
                        levenshtein_score=match.get("components", {}).get("vendor_name", 0),
                        semantic_score=match.get("components", {}).get("raw_text", 0),
                        duplicate_probability=match["similarity_score"],
                        match_type="fuzzy",
                    )
                    db.add(dup_record)
                except Exception:
                    pass

            evidence = invoice.fraud_evidence or {}
            evidence["duplicate"] = {
                "score": result.get("duplicate_score", 0),
                "is_duplicate": result.get("is_duplicate", False),
                "summary": result.get("summary", ""),
            }
            invoice.fraud_evidence = evidence
            db.commit()

        duplicate_detector.add_to_index(invoice_id, result["fingerprint"])
        return {"duplicate_score": result.get("duplicate_score", 0)}
    except Exception as e:
        logger.error(f"Duplicate detection failed for {invoice_id}: {e}")
        return {"duplicate_score": 0, "error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# STEP 3c: ANOMALY DETECTION  (runs in parallel)
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="task_anomaly_score")
def task_anomaly_score(invoice_id: str, file_path: str):
    """ML anomaly detection — Isolation Forest + Autoencoder."""
    _, _, _, _, anomaly_detector = _get_services()
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
            "raw_text": invoice.raw_text or "",
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
        }

        anomaly_result = anomaly_detector.detect_anomaly(invoice_data)

        if invoice:
            invoice.anomaly_score = anomaly_result.get("anomaly_score", 0)

            anomaly_record = AnomalyResult(
                invoice_id=uuid.UUID(invoice_id),
                isolation_forest_score=(
                    anomaly_result.get("isolation_forest", {}).get("normalized_score", 0)
                    if anomaly_result.get("isolation_forest") else 0
                ),
                autoencoder_error=(
                    anomaly_result.get("autoencoder", {}).get("reconstruction_error", 0)
                    if anomaly_result.get("autoencoder") else 0
                ),
                combined_anomaly_score=anomaly_result.get("anomaly_score", 0),
                feature_importances=anomaly_result.get("feature_importance"),
                heuristic_flags=anomaly_result.get("heuristic"),
            )
            db.add(anomaly_record)

            evidence = invoice.fraud_evidence or {}
            evidence["anomaly"] = {
                "score": anomaly_result.get("anomaly_score", 0),
                "is_anomalous": anomaly_result.get("is_anomalous", False),
                "feature_importance": anomaly_result.get("feature_importance", {}),
            }
            invoice.fraud_evidence = evidence
            db.commit()

        return {"anomaly_score": anomaly_result.get("anomaly_score", 0)}
    except Exception as e:
        logger.error(f"Anomaly detection failed for {invoice_id}: {e}")
        return {"anomaly_score": 0, "error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# STEP 4: RISK SCORING + NOTIFICATION  (chord callback)
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="task_compute_risk_score")
def task_compute_risk_score(analysis_results, invoice_id: str):
    """
    Chord callback — receives list of results from parallel tasks.
    Aggregates all scores into Composite Risk Score and classifies.
    """
    _, _, _, risk_scoring_service, _ = _get_services()
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == uuid.UUID(invoice_id)).first()
        if not invoice:
            return {"error": "Invoice not found"}

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

        invoice.risk_score = risk_result["risk_score"]
        invoice.risk_level = RiskLevel(risk_result["risk_level"])
        invoice.risk_class = risk_result["risk_level"]

        # Status based on risk (FR-703/704/705)
        if risk_result["risk_level"] in ("critical", "high"):
            invoice.status = InvoiceStatus.FLAGGED
        elif risk_result["risk_level"] == "medium":
            invoice.status = InvoiceStatus.UNDER_REVIEW
        else:
            invoice.status = InvoiceStatus.ANALYZED

        invoice.processed_at = datetime.utcnow()

        evidence = invoice.fraud_evidence or {}
        evidence["risk_breakdown"] = risk_result["breakdown"]
        evidence["recommended_action"] = risk_result["recommended_action"]
        evidence["dominant_risk"] = risk_result["dominant_risk"]
        invoice.fraud_evidence = evidence
        db.commit()

        # Webhook notifications (SRS Section 6.2)
        _send_notifications(db, str(invoice.id), risk_result)

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
        return {"error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _send_notifications(db, invoice_id: str, risk_result: Dict):
    try:
        from app.services.webhook_service import webhook_service
        webhook_service.invoice_processed(db, invoice_id, risk_result["risk_score"], risk_result["risk_level"])
        if risk_result["risk_level"] in ("high", "critical"):
            webhook_service.invoice_flagged(db, invoice_id, risk_result["risk_score"], risk_result["risk_level"], risk_result["breakdown"])
    except Exception as e:
        logger.warning(f"Webhook notification failed for {invoice_id}: {e}")


def _mark_error(invoice_id: str, error_msg: str):
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


# ═══════════════════════════════════════════════════════════════════════
# PERIODIC TASKS
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="retrain_models")
def retrain_models():
    """FR-604: Periodic model retraining with labeled data."""
    _, _, _, _, anomaly_detector = _get_services()
    db = SessionLocal()
    try:
        confirmed = db.query(Invoice).filter(
            Invoice.status.in_([InvoiceStatus.APPROVED, InvoiceStatus.REJECTED]),
        ).all()

        if len(confirmed) < 50:
            logger.info("Not enough labeled data for retraining")
            return {"status": "skipped", "reason": "insufficient_data"}

        training_data = [
            {
                "total_amount": inv.total_amount, "tax_amount": inv.tax_amount,
                "subtotal": inv.subtotal, "invoice_date": inv.invoice_date,
                "due_date": inv.due_date, "ocr_confidence": inv.ocr_confidence,
                "raw_text": inv.raw_text or "", "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
            }
            for inv in confirmed
        ]

        anomaly_detector.train(training_data)
        import os
        os.makedirs("ml_models", exist_ok=True)
        anomaly_detector.save_models("ml_models")

        return {"status": "success", "training_samples": len(training_data)}
    except Exception as e:
        logger.error(f"Model retraining failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="cleanup_old_results")
def cleanup_old_results():
    """Periodic cleanup."""
    logger.info("Running cleanup task")
