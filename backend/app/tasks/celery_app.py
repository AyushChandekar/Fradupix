"""
Celery Application Configuration (SRS Section 2.4)
Celery 5.x with Redis 7.x as message broker.
"""
import logging

logger = logging.getLogger(__name__)

celery_app = None

try:
    from celery import Celery
    from app.config import get_settings

    settings = get_settings()

    celery_app = Celery(
        "invoicefirewall",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.tasks.invoice_tasks",
        ],
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # SRS: 300s soft, 600s hard time limits
        task_soft_time_limit=300,
        task_time_limit=600,
        result_expires=3600,
        # SRS: 3 retries with exponential backoff (factor 2x)
        task_default_retry_delay=10,
        task_max_retries=3,
    )

    # SRS FR-604: Weekly model retraining + hourly cleanup
    celery_app.conf.beat_schedule = {
        "cleanup-old-results": {
            "task": "cleanup_old_results",
            "schedule": 3600.0,  # Hourly
        },
        "retrain-models-weekly": {
            "task": "retrain_models",
            "schedule": 604800.0,  # Weekly (7 days)
        },
    }
    logger.info("Celery configured with Redis broker")
except Exception as e:
    logger.warning(f"Celery not available ({e}), async tasks disabled")
