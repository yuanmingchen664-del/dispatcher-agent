from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from backend.app.models import document, qa_log  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_compatible_schema()


def ensure_compatible_schema() -> None:
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "document_metadata" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE documents ADD COLUMN document_metadata JSON DEFAULT '{}'"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
