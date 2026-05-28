from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    title: str
    doc_type: Optional[str]
    version: Optional[str]
    effective_date: Optional[date]
    status: str
    original_filename: str
    file_size: int
    mime_type: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ProcessResult(BaseModel):
    document_id: str
    status: str
    chunks_created: int


class ChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    chapter: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentChunksResponse(BaseModel):
    document_id: str
    document_title: str
    document_status: str
    total: int
    limit: int
    offset: int
    chunks: list[ChunkOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=20)


class SourceOut(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    content: str
    chapter: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SourceOut]


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=20)


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceOut]
    qa_log_id: str


class FeedbackRequest(BaseModel):
    qa_log_id: str
    user_feedback: str = Field(pattern="^(helpful|not_helpful|unsafe|incorrect)$")
    feedback_note: Optional[str] = None


class FeedbackResponse(BaseModel):
    qa_log_id: str
    user_feedback: str
