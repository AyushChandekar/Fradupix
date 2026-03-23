import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _create_engine():
    """Create DB engine with SQLite fallback for local development."""
    db_url = settings.DATABASE_URL

    # Try PostgreSQL first
    if db_url.startswith("postgresql"):
        try:
            eng = create_engine(
                db_url,
                pool_size=20,
                max_overflow=10,
                pool_pre_ping=True,
            )
            # Test connection
            with eng.connect() as conn:
                conn.execute(conn.default_isolation_level if False else eng.dialect.do_ping(conn.connection))
            logger.info("✅ Connected to PostgreSQL")
            return eng
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL unavailable ({e}), falling back to SQLite")

    # Fallback to SQLite
    sqlite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fradupix.db")
    sqlite_url = f"sqlite:///{sqlite_path}"
    eng = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL mode for better concurrent access
    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    logger.info(f"✅ Using SQLite database: {sqlite_path}")
    return eng


engine = _create_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
