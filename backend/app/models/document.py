import enum
import uuid
from datetime import date, datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.config import get_settings
from backend.app.db.session import Base


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"
    archived = "archived"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), index=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    version: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.uploaded, index=True
    )

    storage_provider: Mapped[str] = mapped_column(String(40))
    bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    object_key: Mapped[str] = mapped_column(String(1024))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    document_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    chapter: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().embedding_dimensions))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")
