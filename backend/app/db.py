from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


def get_engine() -> Engine:
    global engine
    if engine is None:
        settings = get_settings()
        engine = create_engine(settings.database_url, pool_pre_ping=True)
    return engine


def get_session_factory() -> sessionmaker:
    SessionLocal.configure(bind=get_engine())
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models inside the function to avoid circular import at module load time.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
