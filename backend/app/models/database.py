"""Database engine and session factory for SQLAlchemy."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from ..config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite needs this for multi-thread
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    """Dependency for FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database() -> None:
    """Create all tables.

    Models must be imported before create_all() so they register with Base.metadata.
    """
    from . import sensor_reading  # noqa: F401
    from . import station_config  # noqa: F401
    from . import archive_record  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Enable WAL mode so the logger and web app can access the DB concurrently
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.commit()

    # Migrate: add rain_yearly column if missing
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT rain_yearly FROM sensor_readings LIMIT 1"))
        except Exception:
            conn.execute(text(
                "ALTER TABLE sensor_readings ADD COLUMN rain_yearly INTEGER"
            ))
            conn.commit()
