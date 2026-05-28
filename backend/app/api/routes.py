from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_db
from backend.app.models.document import Document, DocumentChunk, DocumentStatus
from backend.app.models.qa_log import QALog
from backend.app.schemas import (
    AskRequest,
    AskResponse,
    ChunkOut,
    DocumentChunksResponse,
    DocumentOut,
    FeedbackRequest,
    FeedbackResponse,
    ProcessResult,
    SearchRequest,
    SearchResponse,
)
from backend.app.services.chunker import split_pages_into_chunks
from backend.app.services.parser import parse_document
from backend.app.services.providers import get_embedding_provider, get_llm_provider
from backend.app.services.retrieval import search_chunks
from backend.app.services.storage import get_storage

router = APIRouter()


def parse_optional_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def root() -> dict[str, str]:
    return {
        "message": "签派助手后端已启动",
        "api_docs": "/docs",
        "health": "/health",
    }


@router.post("/documents/upload", response_model=DocumentOut)
def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    doc_type: Optional[str] = Form(default=None),
    version: Optional[str] = Form(default=None),
    effective_date: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    storage = get_storage(settings)
    stored = storage.save(file.file, file.filename or "manual")
    document = Document(
        title=title or Path(file.filename or "manual").stem,
        doc_type=doc_type,
        version=version,
        effective_date=parse_optional_date(effective_date),
        storage_provider=stored.provider,
        bucket=stored.bucket,
        object_key=stored.object_key,
        original_filename=file.filename or "manual",
        file_hash=stored.file_hash,
        file_size=stored.file_size,
        mime_type=file.content_type,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.created_at.desc())).all()


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
def list_document_chunks(
    document_id: str,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit 应在 1 到 100 之间")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset 不能小于 0")

    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    total = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .count()
    )
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    chunks = [
        ChunkOut(
            id=row.id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            chapter=row.chapter,
            page_start=row.page_start,
            page_end=row.page_end,
            metadata=row.chunk_metadata or {},
            created_at=row.created_at,
        )
        for row in rows
    ]
    return DocumentChunksResponse(
        document_id=document.id,
        document_title=document.title,
        document_status=document.status.value,
        total=total,
        limit=limit,
        offset=offset,
        chunks=chunks,
    )


@router.post("/documents/{document_id}/process", response_model=ProcessResult)
def process_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document.status = DocumentStatus.processing
    document.error_message = None
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    db.commit()

    try:
        storage = get_storage(settings)
        temp_path = storage.download_to_temp(document.object_key)
        pages = parse_document(temp_path, document.mime_type)
        chunks = split_pages_into_chunks(
            pages,
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
        embeddings = get_embedding_provider(settings).embed([chunk.content for chunk in chunks])

        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk.content,
                    chapter=chunk.chapter,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_metadata=chunk.metadata,
                    embedding=embedding,
                )
            )
        document.status = DocumentStatus.ready
        db.commit()
        return ProcessResult(document_id=document.id, status=document.status.value, chunks_created=len(chunks))
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        document.status = DocumentStatus.failed
        document.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    top_k = request.top_k or settings.top_k
    query_embedding = get_embedding_provider(settings).embed([request.query])[0]
    results = search_chunks(db, request.query, query_embedding, top_k)
    return SearchResponse(query=request.query, results=results)


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    top_k = request.top_k or settings.top_k
    query_embedding = get_embedding_provider(settings).embed([request.question])[0]
    sources = search_chunks(db, request.question, query_embedding, top_k)
    answer = get_llm_provider(settings).answer(request.question, sources)
    log = QALog(
        question=request.question,
        answer=answer,
        sources=[source.model_dump() for source in sources],
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return AskResponse(question=request.question, answer=answer, sources=sources, qa_log_id=log.id)


@router.post("/feedback", response_model=FeedbackResponse)
def feedback(request: FeedbackRequest, db: Session = Depends(get_db)):
    log = db.get(QALog, request.qa_log_id)
    if not log:
        raise HTTPException(status_code=404, detail="QA log not found")
    log.user_feedback = request.user_feedback
    log.feedback_note = request.feedback_note
    db.commit()
    return FeedbackResponse(qa_log_id=log.id, user_feedback=log.user_feedback)
