from sqlalchemy import select, text
from sqlalchemy.orm import Session
from typing import Optional

from backend.app.models.document import Document, DocumentChunk, DocumentStatus
from backend.app.schemas import SourceOut
from backend.app.services.evidence import build_evidence_card, document_source_metadata


def search_chunks(
    db: Session,
    query: str,
    query_embedding: list[float],
    top_k: int,
) -> list[SourceOut]:
    try:
        return _vector_search(db, query_embedding, top_k)
    except Exception:
        db.rollback()
        return _keyword_search(db, query, top_k)


def _vector_search(db: Session, query_embedding: list[float], top_k: int) -> list[SourceOut]:
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(DocumentChunk, Document, distance)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == DocumentStatus.ready)
        .order_by(distance)
        .limit(top_k)
    )
    rows = db.execute(stmt).all()
    return [_to_source(chunk, document, float(1 - distance_value)) for chunk, document, distance_value in rows]


def _keyword_search(db: Session, query: str, top_k: int) -> list[SourceOut]:
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == DocumentStatus.ready)
        .where(text("document_chunks.content ILIKE :pattern"))
        .limit(top_k)
    )
    rows = db.execute(stmt, {"pattern": f"%{query}%"}).all()
    return [_to_source(chunk, document, None) for chunk, document in rows]


def _to_source(
    chunk: DocumentChunk,
    document: Document,
    score: Optional[float],
) -> SourceOut:
    return SourceOut(
        document_id=document.id,
        document_title=document.title,
        chunk_id=chunk.id,
        content=chunk.content,
        chapter=chunk.chapter,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        score=score,
        evidence=build_evidence_card(document, chunk),
        metadata={
            **(chunk.chunk_metadata or {}),
            **document_source_metadata(document),
            "doc_type": document.doc_type,
            "version": document.version,
            "effective_date": (
                document.effective_date.isoformat() if document.effective_date else None
            ),
        },
    )
