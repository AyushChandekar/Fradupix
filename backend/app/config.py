import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_NAME: str = "Fradupix - Invoice Fraud Detection"
    APP_VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = "postgresql://fradupix:fradupix_secure_2024@localhost:5432/fradupix"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = "minioadmin123"
    MINIO_BUCKET: str = "invoices"
    MINIO_SECURE: bool = False

    # Encryption
    ENCRYPTION_KEY: str = ""

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # ML Model paths
    ANOMALY_MODEL_PATH: str = "ml_models/anomaly_model.pkl"
    AUTOENCODER_MODEL_PATH: str = "ml_models/autoencoder_model.pt"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
