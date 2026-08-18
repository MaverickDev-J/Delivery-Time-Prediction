"""
Database engine and session factory for DeliverIQ microservices.

Each service gets its own database (DB-per-service pattern).
Uses SQLite for offline/test mode and PostgreSQL for Docker Compose.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.logging import setup_logger

logger = setup_logger("core.database")


class Base(DeclarativeBase):
    """Shared declarative base for all service ORM models."""


def create_db_engine(database_url: str, echo: bool = False):
    """Create a SQLAlchemy engine from a connection URL.

    Supports:
      - sqlite:///path/to/db.sqlite  (offline/test)
      - postgresql://user:pass@host/dbname  (Docker Compose)
    """
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    # SQLite: enable WAL mode and foreign keys
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Context manager yielding a database session with auto-rollback on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_tables(engine, base: type[DeclarativeBase] = Base):
    """Create all tables for the given base — used at service startup."""
    base.metadata.create_all(bind=engine)
    logger.info(f"Database tables initialized for engine: {engine.url}")
