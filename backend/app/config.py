import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_NAME: str = "InvoiceFirewall - Invoice Fraud Detection"
    APP_VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = "postgresql://fradupix:fradupix_secure_2024@localhost:5432/fradupix"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT (SRS Section 11.1)
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 15  # SRS: 15-minute access tokens
    JWT_REFRESH_EXPIRATION_DAYS: int = 7  # SRS: 7-day refresh tokens

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_CONCURRENCY: int = 4  # SRS Appendix D

    # MinIO / S3 (SRS Appendix D)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = "minioadmin123"
    MINIO_BUCKET: str = "invoices"
    MINIO_SECURE: bool = False
    S3_ENDPOINT: str = "http://minio:9000"

    # OCR Service (SRS Appendix D)
    OCR_SERVICE_URL: str = "http://invoicefirewall-ocr:8001"

    # ML Service (SRS Appendix D)
    ML_SERVICE_URL: str = "http://invoicefirewall-ml:8002"

    # Encryption (SRS Section 11.2)
    ENCRYPTION_KEY: str = ""

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # Risk Score Weights (SRS Appendix A & D)
    RISK_WEIGHT_FORGERY: float = 0.30
    RISK_WEIGHT_DUPLICATE: float = 0.25
    RISK_WEIGHT_ANOMALY: float = 0.25
    RISK_WEIGHT_RULES: float = 0.20

    # Risk Classification Thresholds (SRS Section 3.7 FR-702)
    RISK_THRESHOLD_LOW: int = 30
    RISK_THRESHOLD_MEDIUM: int = 60
    RISK_THRESHOLD_HIGH: int = 85
    RISK_THRESHOLD_CRITICAL: int = 100

    # Duplicate Detection (SRS Section 3.5)
    DUPLICATE_TIME_WINDOW_DAYS: int = 90
    FUZZY_MATCH_THRESHOLD: float = 0.15
    SEMANTIC_SIMILARITY_THRESHOLD: float = 0.85

    # ML Model paths
    ANOMALY_MODEL_PATH: str = "ml_models/anomaly_model.pkl"
    AUTOENCODER_MODEL_PATH: str = "ml_models/autoencoder_model.pt"

    # File Upload (SRS FR-101)
    MAX_FILE_SIZE_MB: int = 50
    BATCH_UPLOAD_LIMIT: int = 1000

    # Logging (SRS Appendix D)
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
