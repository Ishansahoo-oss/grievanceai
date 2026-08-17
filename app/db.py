"""
Database engine/session setup, plus a startup routine that ensures the
pgvector extension exists and creates all tables.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Run on application startup.
    1. Ensure the pgvector extension is installed in the database.
    2. Create any tables that don't already exist.

    NOTE: this import is local to avoid a circular import between
    db.py and models.py (models.py imports Base from this module).
    """
    from app import models  # noqa: F401  (ensures models are registered on Base)

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
