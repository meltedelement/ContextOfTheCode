"""Database engine and session setup."""

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Expected format: mysql+pymysql://user:pass@host/dbname"
    )

engine = create_engine(
    DATABASE_URL,
    pool_recycle=280,   # Reconnect before MySQL's default 5-min idle timeout
    pool_pre_ping=True, # Test connection health before use (prevents 'gone away' errors)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_db():
    """
    Provide a transactional database session.

    Commits on success, rolls back on any exception, always closes the session.
    Usage:
        with get_db() as db:
            db.add(record)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
