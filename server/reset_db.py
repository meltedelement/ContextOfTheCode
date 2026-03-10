"""One-shot script to drop and recreate all database tables.

Use this when the schema has changed in a way that requires a clean slate
(e.g. adding non-nullable columns to an existing MySQL database).

WARNING: This destroys all data. Only run against a test/dev database.

Usage:
    DATABASE_URL=mysql+pymysql://user:pass@host/dbname python -m server.reset_db
"""

from server.database import Base, engine
from server.models import Aggregator, Device, Snapshot, Metric  # noqa: F401 — registers models
from sharedUtils.logger.logger import get_logger

logger = get_logger(__name__)


def reset():
    logger.warning("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("Recreating all tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Done. Database reset complete.")


if __name__ == "__main__":
    reset()
