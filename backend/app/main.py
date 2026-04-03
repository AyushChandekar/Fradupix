"""
InvoiceFirewall - AI-Powered Invoice Fraud & Duplicate Detection Engine
FastAPI Application Entry Point (SRS Section 2.4)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Create database tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created")
    except Exception as e:
        logger.error(f"Database table creation failed: {e}")

    yield

    logger.info("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-Powered Invoice Fraud & Duplicate Detection Engine (InvoiceFirewall)",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router (backward-compatible /api/auth prefix)
from app.api.auth import router as auth_router
app.include_router(auth_router)

# SRS v1 API routes (Section 6.1)
from app.api.invoices import router as invoices_router
from app.api.dashboard import router as dashboard_router
from app.api.documents import router as documents_router
from app.api.admin import router as admin_router

app.include_router(invoices_router)
app.include_router(dashboard_router)
app.include_router(documents_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
