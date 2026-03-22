"""
Celery Application Configuration
Falls back gracefully when Redis is unavailable (local dev without Docker)
"""
import logging

logger = logging.getLogger(__name__)

celery_app = None

try:
    from celery import Celery
    from app.config import get_settings

    settings = get_settings()

    celery_app = Celery(
        "aidetect",
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
        task_soft_time_limit=300,
        task_time_limit=600,
        result_expires=3600,
    )

    celery_app.conf.beat_schedule = {
        "cleanup-old-results": {
            "task": "app.tasks.invoice_tasks.cleanup_old_results",
            "schedule": 3600.0,
        },
    }
    logger.info("✅ Celery configured")
except Exception as e:
    logger.warning(f"⚠️ Celery not available ({e}), async tasks disabled")
