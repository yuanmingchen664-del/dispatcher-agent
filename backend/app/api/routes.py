from datetime import date
from enum import Enum
from io import BytesIO
from pathlib import Path
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_db
from backend.app.models.document import Document, DocumentChunk, DocumentStatus
from backend.app.models.qa_log import QALog
from backend.app.schemas import (
    AgentMessageRequest,
    AgentMessageResponse,
    AskRequest,
    AskResponse,
    ChunkOut,
    DocumentChunksResponse,
    DocumentOut,
    DocumentOutlineResponse,
    FeedbackRequest,
    FeedbackResponse,
    NoteCreateRequest,
    NoteCreateResponse,
    OutlineItem,
    ProcessResult,
    SearchRequest,
    SearchResponse,
    SourceOut,
)
from backend.app.services.chunker import (
    TextPage,
    extract_article_numbers_from_content,
    is_appendix_heading,
    is_chapter_heading,
    normalize_heading,
    split_pages_into_chunks,
)
from backend.app.services.evidence import (
    build_document_metadata,
    build_evidence_card,
    document_source_metadata,
)
from backend.app.services.note_analyzer import analyze_note_message
from backend.app.services.parser import parse_document
from backend.app.services.providers import get_embedding_provider, get_llm_provider
from backend.app.services.retrieval import search_chunks
from backend.app.services.storage import get_storage

router = APIRouter()


class QuestionIntent(str, Enum):
    CHAPTER_EXISTENCE = "chapter_existence"
    CHAPTER_CONTENT = "chapter_content"
    OUTLINE = "outline"
    APPROACH_MINIMA_OVERVIEW = "approach_minima_overview"
    APPROACH_MINIMA_CALCULATION = "approach_minima_calculation"
    ARTICLE_LOOKUP = "article_lookup"
    RAG = "rag"


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
    source_type: Optional[str] = Form(default=None),
    author: Optional[str] = Form(default=None),
    department: Optional[str] = Form(default=None),
    scenario: Optional[str] = Form(default=None),
    reliability: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    storage = get_storage(settings)
    stored = storage.save(file.file, file.filename or "manual")
    document = Document(
        title=title or Path(file.filename or "manual").stem,
        doc_type=doc_type or source_type,
        version=version,
        effective_date=parse_optional_date(effective_date),
        document_metadata=build_document_metadata(
            source_type=source_type or doc_type,
            author=author,
            department=department,
            scenario=scenario,
            reliability=reliability,
        ),
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


@router.put("/documents/{document_id}/replace", response_model=DocumentOut)
def replace_document(
    document_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    doc_type: Optional[str] = Form(default=None),
    version: Optional[str] = Form(default=None),
    effective_date: Optional[str] = Form(default=None),
    source_type: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage(settings)
    old_object_key = document.object_key
    stored = storage.save(file.file, file.filename or document.original_filename)

    document.title = title or document.title
    document.doc_type = doc_type or source_type or document.doc_type
    document.version = version if version is not None else document.version
    document.effective_date = parse_optional_date(effective_date) if effective_date else document.effective_date
    if source_type or doc_type:
        document.document_metadata = {
            **(document.document_metadata or {}),
            **build_document_metadata(source_type=source_type or doc_type),
        }
    document.storage_provider = stored.provider
    document.bucket = stored.bucket
    document.object_key = stored.object_key
    document.original_filename = file.filename or document.original_filename
    document.file_hash = stored.file_hash
    document.file_size = stored.file_size
    document.mime_type = file.content_type
    document.status = DocumentStatus.uploaded
    document.error_message = None
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    db.commit()
    db.refresh(document)

    try:
        storage.delete(old_object_key)
    except Exception:
        # 文件对象删除失败不影响数据库替换结果；后续可通过对象存储生命周期清理。
        pass
    return document


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    object_key = document.object_key
    db.delete(document)
    db.commit()

    try:
        get_storage(settings).delete(object_key)
    except Exception:
        # 文档记录已删除；文件对象删除失败不阻塞用户操作。
        pass
    return {"document_id": document_id, "status": "deleted"}


@router.post("/agent/message", response_model=AgentMessageResponse)
def agent_message(
    request: AgentMessageRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    analyzed_note = analyze_note_message(request.message)
    if analyzed_note:
        note_response = create_note(
            NoteCreateRequest(
                title=analyzed_note.title,
                content=analyzed_note.content,
                source_type=analyzed_note.source_type,
                scenario=analyzed_note.scenario,
                author=request.author or "我",
                department=request.department,
                reliability=analyzed_note.reliability,
                effective_date=request.effective_date,
            ),
            db=db,
            settings=settings,
        )
        label = note_response.document.document_metadata.get("scenario") or note_response.document.title
        return AgentMessageResponse(
            action="note_saved",
            message=f"已保存为个人经验：{label}",
            document=note_response.document,
            chunks_created=note_response.chunks_created,
        )

    ask_response = ask(
        AskRequest(question=request.message, top_k=request.top_k),
        db=db,
        settings=settings,
    )
    return AgentMessageResponse(
        action="answered",
        message="已根据知识库生成回答。",
        answer=ask_response.answer,
        intent=ask_response.intent,
        sources=ask_response.sources,
        qa_log_id=ask_response.qa_log_id,
    )


@router.post("/notes", response_model=NoteCreateResponse)
def create_note(
    request: NoteCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    content_bytes = request.content.encode("utf-8")
    storage = get_storage(settings)
    stored = storage.save(BytesIO(content_bytes), f"{request.title}.txt")
    document = Document(
        title=request.title,
        doc_type=request.source_type,
        version=request.version,
        effective_date=request.effective_date,
        document_metadata=build_document_metadata(
            source_type=request.source_type,
            author=request.author,
            department=request.department,
            scenario=request.scenario,
            reliability=request.reliability,
        ),
        storage_provider=stored.provider,
        bucket=stored.bucket,
        object_key=stored.object_key,
        original_filename=f"{request.title}.txt",
        file_hash=stored.file_hash,
        file_size=stored.file_size,
        mime_type="text/plain",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        chunks_created = index_document_pages(
            db,
            document,
            [TextPage(page_number=1, text=request.content)],
            settings,
        )
        return NoteCreateResponse(document=document, chunks_created=chunks_created)
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document.id)
        document.status = DocumentStatus.failed
        document.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
def list_document_chunks(
    document_id: str,
    limit: int = 20,
    offset: int = 0,
    article: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit 应在 1 到 100 之间")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset 不能小于 0")

    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    query = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id)
    if article:
        normalized_article = normalize_article_number(article)
        query = query.filter(DocumentChunk.content.contains(normalized_article))

    total = query.count()
    rows = query.order_by(DocumentChunk.chunk_index.asc()).offset(offset).limit(limit).all()
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


@router.get("/documents/{document_id}/outline", response_model=DocumentOutlineResponse)
def get_document_outline(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    chapters = _extract_outline_items(rows, kind="chapter")
    appendices = _extract_outline_items(rows, kind="appendix")
    return DocumentOutlineResponse(
        document_id=document.id,
        document_title=document.title,
        document_status=document.status.value,
        chapter_count=len(chapters),
        appendix_count=len(appendices),
        chapters=chapters,
        appendices=appendices,
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
        pages = parse_document(temp_path, document.mime_type, settings)
        chunks_created = index_document_pages(db, document, pages, settings)
        return ProcessResult(document_id=document.id, status=document.status.value, chunks_created=chunks_created)
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
    intent = classify_question(request.question)
    routed_answer = try_answer_by_intent(db, request.question, settings, top_k, intent)
    if routed_answer:
        answer, sources = routed_answer
        return save_ask_response(db, request.question, answer, sources, intent)

    return answer_with_rag(db, request.question, settings, top_k)


@router.post("/feedback", response_model=FeedbackResponse)
def feedback(request: FeedbackRequest, db: Session = Depends(get_db)):
    log = db.get(QALog, request.qa_log_id)
    if not log:
        raise HTTPException(status_code=404, detail="QA log not found")
    log.user_feedback = request.user_feedback
    log.feedback_note = request.feedback_note
    db.commit()
    return FeedbackResponse(qa_log_id=log.id, user_feedback=log.user_feedback)


def classify_question(question: str) -> QuestionIntent:
    if is_approach_facility_minima_overview_question(question):
        return QuestionIntent.APPROACH_MINIMA_OVERVIEW
    if is_approach_facility_minima_calculation_question(question):
        return QuestionIntent.APPROACH_MINIMA_CALCULATION
    if extract_article_numbers(question):
        return QuestionIntent.ARTICLE_LOOKUP
    if is_chapter_existence_question(question):
        return QuestionIntent.CHAPTER_EXISTENCE
    if is_chapter_summary_question(question):
        return QuestionIntent.CHAPTER_CONTENT
    if is_outline_question(question):
        return QuestionIntent.OUTLINE
    return QuestionIntent.RAG


def try_answer_by_intent(
    db: Session,
    question: str,
    settings: Settings,
    top_k: int,
    intent: QuestionIntent,
) -> Optional[tuple[str, list[SourceOut]]]:
    if intent == QuestionIntent.APPROACH_MINIMA_OVERVIEW:
        return try_answer_approach_facility_minima_overview_question(db, question)
    if intent == QuestionIntent.APPROACH_MINIMA_CALCULATION:
        return try_answer_approach_facility_minima_question(db, question)
    if intent == QuestionIntent.ARTICLE_LOOKUP:
        return try_answer_article_question(db, question, settings)
    if intent == QuestionIntent.CHAPTER_EXISTENCE:
        return try_answer_chapter_existence_question(db, question)
    if intent == QuestionIntent.CHAPTER_CONTENT:
        return try_answer_chapter_question(db, question, settings, top_k)
    if intent == QuestionIntent.OUTLINE:
        return try_answer_outline_question(db, question)
    return None


def answer_with_rag(
    db: Session,
    question: str,
    settings: Settings,
    top_k: int,
) -> AskResponse:
    query_embedding = get_embedding_provider(settings).embed([question])[0]
    sources = search_chunks(db, question, query_embedding, top_k)
    answer = get_llm_provider(settings).answer(question, sources)
    return save_ask_response(db, question, answer, sources, QuestionIntent.RAG)


def save_ask_response(
    db: Session,
    question: str,
    answer: str,
    sources: list[SourceOut],
    intent: QuestionIntent,
) -> AskResponse:
    log = QALog(
        question=question,
        answer=answer,
        sources=[source.model_dump() for source in sources],
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return AskResponse(
        question=question,
        answer=answer,
        intent=intent.value,
        sources=sources,
        qa_log_id=log.id,
    )


def index_document_pages(
    db: Session,
    document: Document,
    pages: list[TextPage],
    settings: Settings,
) -> int:
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
    chunks = split_pages_into_chunks(
        pages,
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    embeddings = get_embedding_provider(settings).embed([chunk.content for chunk in chunks])

    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_metadata = {
            **chunk.metadata,
            **document_source_metadata(document),
        }
        db.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk.content,
                chapter=chunk.chapter,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                chunk_metadata=chunk_metadata,
                embedding=embedding,
            )
        )
    document.status = DocumentStatus.ready
    db.commit()
    db.refresh(document)
    return len(chunks)


def _extract_outline_items(rows: list[DocumentChunk], kind: str) -> list[OutlineItem]:
    seen: set[str] = set()
    items: list[OutlineItem] = []
    for row in rows:
        for line in row.content.splitlines():
            title = normalize_heading(line)
            if not title:
                continue
            is_match = is_chapter_heading(title) if kind == "chapter" else is_appendix_heading(title)
            if not is_match or title in seen:
                continue
            seen.add(title)
            items.append(
                OutlineItem(
                    title=title,
                    kind=kind,
                    first_chunk_index=row.chunk_index,
                    page_start=row.page_start,
                    page_end=row.page_end,
                )
            )
    return items


def try_answer_outline_question(
    db: Session,
    question: str,
) -> Optional[tuple[str, list[SourceOut]]]:
    if not is_outline_question(question):
        return None

    document = find_document_for_question(db, question)
    if not document:
        return None

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not rows:
        return None

    chapters = _extract_outline_items(rows, kind="chapter")
    appendices = _extract_outline_items(rows, kind="appendix")
    if not chapters and not appendices:
        return None

    chapter_keyword = extract_chapter_filter_keyword(question)
    if chapter_keyword:
        answer = build_filtered_chapter_answer(document, chapters, chapter_keyword)
        source = build_filtered_chapter_source(document, rows[0], chapters, chapter_keyword)
        return answer, [source]

    answer = build_outline_answer(document, chapters, appendices)
    source = build_outline_source(document, rows[0], chapters, appendices)
    return answer, [source]


def is_outline_question(question: str) -> bool:
    if extract_chapter_key(question):
        return False
    keywords = ["多少章", "几章", "章节", "目录", "大纲", "附件", "附录", "有哪些章"]
    return any(keyword in question for keyword in keywords)


def extract_chapter_filter_keyword(question: str) -> Optional[str]:
    if not any(keyword in question for keyword in ["提到", "包含", "涉及", "关于"]):
        return None
    if not any(keyword in question for keyword in ["章节", "章"]):
        return None

    patterns = [
        r"(?:提到|包含|涉及|关于)(.+?)(?:的)?章节",
        r"(?:提到|包含|涉及|关于)(.+?)(?:的)?章",
        r"(?:哪几章|哪些章|有哪些章|章节).{0,8}(?:关于|涉及|包含|提到)(.+?)(?:的)?(?:\？|\?|，|,|。|；|;|$)",
        r"(?:关于|涉及|包含|提到)(.+?)(?:的)?(?:哪几章|哪些章|有哪些章|章节)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        keyword = cleanup_filter_keyword(match.group(1))
        if keyword:
            return keyword
    return None


def cleanup_filter_keyword(value: str) -> str:
    cleaned = value.strip(" ：:，,。？?的")
    cleaned = re.sub(r"^(CCAR121|ccar121|121部|部)\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?:相关|有关)?(?:内容|要求|规定)$", "", cleaned).strip(" 的")
    return cleaned


def find_document_for_question(db: Session, question: str) -> Optional[Document]:
    documents = (
        db.query(Document)
        .filter(Document.status == DocumentStatus.ready)
        .order_by(Document.created_at.desc())
        .all()
    )
    if not documents:
        return None

    normalized_question = question.lower().replace("-", "").replace("_", "").replace(" ", "")
    for document in documents:
        title = document.title.lower().replace("-", "").replace("_", "").replace(" ", "")
        filename = document.original_filename.lower().replace("-", "").replace("_", "").replace(" ", "")
        if title and title in normalized_question:
            return document
        if filename and Path(filename).stem in normalized_question:
            return document

    return documents[0] if len(documents) == 1 else None


def build_outline_answer(
    document: Document,
    chapters: list[OutlineItem],
    appendices: list[OutlineItem],
) -> str:
    lines = [
        f"{document.title} 共识别到 {len(chapters)} 章，{len(appendices)} 个附件/附录。",
    ]
    if chapters:
        lines.append("")
        lines.append("章节：")
        lines.extend(f"{index}. {item.title}" for index, item in enumerate(chapters, start=1))
    if appendices:
        lines.append("")
        lines.append("附件/附录：")
        lines.extend(f"{index}. {item.title}" for index, item in enumerate(appendices, start=1))
    lines.append("")
    lines.append("说明：该结果来自文档解析后的大纲识别，建议结合原文目录复核。")
    return "\n".join(lines)


def build_filtered_chapter_answer(
    document: Document,
    chapters: list[OutlineItem],
    keyword: str,
) -> str:
    matched = filter_chapters_by_keyword(chapters, keyword)
    lines = [
        f"{document.title} 的章节标题中，与“{keyword}”相关的章节共 {len(matched)} 章。"
    ]
    if matched:
        lines.append("")
        lines.append("匹配章节：")
        lines.extend(f"{index}. {item.title}" for index, item in enumerate(matched, start=1))
    lines.append("")
    lines.append("说明：该结果基于文档大纲标题匹配，不代表正文中所有出现该词的条款统计。")
    return "\n".join(lines)


def filter_chapters_by_keyword(chapters: list[OutlineItem], keyword: str) -> list[OutlineItem]:
    tokens = chapter_keyword_tokens(keyword)
    matched: list[OutlineItem] = []
    for item in chapters:
        title = normalize_for_match(item.title)
        if all(token in title for token in tokens):
            matched.append(item)
            continue
        # “飞行签派”这类业务词允许命中“飞行签派员”和“签派和飞行放行”两种标题写法。
        if keyword == "飞行签派" and "签派" in title and ("飞行" in title or "签派员" in title):
            matched.append(item)
    return matched


def chapter_keyword_tokens(keyword: str) -> list[str]:
    normalized = normalize_for_match(keyword)
    if "签派" in normalized and "放行" in normalized:
        return ["签派", "放行"]
    if normalized == "飞行签派":
        return ["签派"]
    return [normalized] if normalized else []


def normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("员", "")).lower()


def build_outline_source(
    document: Document,
    first_chunk: DocumentChunk,
    chapters: list[OutlineItem],
    appendices: list[OutlineItem],
) -> SourceOut:
    content_lines = ["文档大纲识别结果："]
    content_lines.extend(item.title for item in chapters)
    content_lines.extend(item.title for item in appendices)
    return SourceOut(
        document_id=document.id,
        document_title=document.title,
        chunk_id=first_chunk.id,
        content="\n".join(content_lines),
        chapter=None,
        page_start=first_chunk.page_start,
        page_end=first_chunk.page_end,
        score=None,
        evidence=build_evidence_card(document, first_chunk, "document_outline"),
        metadata={
            **document_source_metadata(document),
            "source_type": "document_outline",
            "chapter_count": len(chapters),
            "appendix_count": len(appendices),
        },
    )


def build_filtered_chapter_source(
    document: Document,
    first_chunk: DocumentChunk,
    chapters: list[OutlineItem],
    keyword: str,
) -> SourceOut:
    matched = filter_chapters_by_keyword(chapters, keyword)
    content_lines = [f"大纲标题匹配关键词：{keyword}"]
    content_lines.extend(item.title for item in matched)
    return SourceOut(
        document_id=document.id,
        document_title=document.title,
        chunk_id=first_chunk.id,
        content="\n".join(content_lines),
        chapter=None,
        page_start=first_chunk.page_start,
        page_end=first_chunk.page_end,
        score=None,
        evidence=build_evidence_card(document, first_chunk, "document_outline_filter"),
        metadata={
            **document_source_metadata(document),
            "source_type": "document_outline_filter",
            "keyword": keyword,
            "matched_chapter_count": len(matched),
        },
    )


def try_answer_chapter_existence_question(
    db: Session,
    question: str,
) -> Optional[tuple[str, list[SourceOut]]]:
    if not is_chapter_existence_question(question):
        return None

    document = find_document_for_question(db, question)
    chapter_key = extract_chapter_key(question)
    if not document or not chapter_key:
        return None

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not rows:
        return None

    chapters = _extract_outline_items(rows, kind="chapter")
    target = find_outline_item(chapters, chapter_key)
    answer = build_chapter_existence_answer(document, chapter_key, chapters, target)
    source = build_chapter_existence_source(document, rows[0], chapter_key, chapters, target)
    return answer, [source]


def is_chapter_existence_question(question: str) -> bool:
    if extract_chapter_key(question) is None:
        return False
    if not any(keyword in question for keyword in ["有没有", "是否有", "有无", "存在"]):
        return False
    content_intent_keywords = ["里", "中", "提到", "涉及", "包含", "讲", "要求", "规定"]
    return not any(keyword in question for keyword in content_intent_keywords)


def build_chapter_existence_answer(
    document: Document,
    chapter_key: str,
    chapters: list[OutlineItem],
    target: Optional[OutlineItem],
) -> str:
    if target:
        return (
            f"{document.title} 有 {chapter_key.upper()} 章：{target.title}。\n\n"
            "说明：该结果来自文档大纲识别，建议结合原文目录复核。"
        )

    chapter_titles = "、".join(item.title.split(" ", 1)[0] for item in chapters)
    return (
        f"{document.title} 未识别到 {chapter_key.upper()} 章。\n\n"
        f"当前大纲识别到的章节为：{chapter_titles}。\n\n"
        "说明：该结果来自文档大纲识别，建议结合原文目录复核。"
    )


def build_chapter_existence_source(
    document: Document,
    first_chunk: DocumentChunk,
    chapter_key: str,
    chapters: list[OutlineItem],
    target: Optional[OutlineItem],
) -> SourceOut:
    content_lines = [f"检查章节：{chapter_key.upper()} 章"]
    if target:
        content_lines.append(f"匹配结果：{target.title}")
    else:
        content_lines.append("匹配结果：未识别到该章节")
        content_lines.append("已识别章节：")
        content_lines.extend(item.title for item in chapters)
    return SourceOut(
        document_id=document.id,
        document_title=document.title,
        chunk_id=first_chunk.id,
        content="\n".join(content_lines),
        chapter=None,
        page_start=first_chunk.page_start,
        page_end=first_chunk.page_end,
        score=None,
        evidence=build_evidence_card(document, first_chunk, "document_outline_chapter_existence"),
        metadata={
            **document_source_metadata(document),
            "source_type": "document_outline_chapter_existence",
            "chapter_key": chapter_key.upper(),
            "exists": target is not None,
        },
    )


def try_answer_chapter_question(
    db: Session,
    question: str,
    settings: Settings,
    top_k: int,
) -> Optional[tuple[str, list[SourceOut]]]:
    if not is_chapter_summary_question(question):
        return None

    document = find_document_for_question(db, question)
    chapter_keys = extract_chapter_keys(question)
    if not document or not chapter_keys:
        return None

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not rows:
        return None

    chapters = _extract_outline_items(rows, kind="chapter")
    selected: list[SourceOut] = []
    seen_source_keys: set[tuple[str, str]] = set()
    content_keyword = extract_chapter_content_keyword(question)
    per_chapter_limit = max(1, min(3, top_k))
    keyword_limit = max(1, top_k)
    source_type = "chapter_keyword_lookup" if content_keyword else "chapter_summary"
    for chapter_key in chapter_keys:
        target = find_outline_item(chapters, chapter_key)
        if not target:
            continue
        chapter_rows = rows_for_outline_item(rows, chapters, target)
        if content_keyword:
            rows_to_add = rows_matching_keyword(
                chapter_rows,
                content_keyword,
                keyword_limit,
                heading_title=target.title,
            )
            sources_to_add = build_chapter_keyword_sources(
                document,
                rows,
                rows_to_add,
                content_keyword,
                keyword_limit,
            )
            for source in sources_to_add:
                source_key = (source.chunk_id, str(source.metadata.get("primary_article") or ""))
                if source_key in seen_source_keys:
                    continue
                selected.append(source)
                seen_source_keys.add(source_key)
            continue
        else:
            rows_to_add = chapter_rows[:per_chapter_limit]
        for row in rows_to_add:
            source_key = (row.id, "")
            if source_key in seen_source_keys:
                continue
            selected.append(chunk_to_source(document, row, source_type))
            seen_source_keys.add(source_key)

    if not selected:
        return None

    answer = get_llm_provider(settings).answer(question, selected)
    return answer, selected


def is_chapter_summary_question(question: str) -> bool:
    intent_keywords = [
        "归纳",
        "总结",
        "概括",
        "主要讲",
        "主要内容",
        "讲了什么",
        "是否",
        "有没有",
        "提到",
        "涉及",
        "包含",
        "要求",
        "规定",
        "区别",
        "对比",
        "比较",
        "不同",
    ]
    return any(keyword in question for keyword in intent_keywords) and bool(extract_chapter_keys(question))


def extract_chapter_content_keyword(question: str) -> Optional[str]:
    normalized = re.sub(r"\s+", "", question)
    patterns = [
        r"提到(.+?)(?:如果|是否|有哪|哪些|什么|吗|么|？|\?|，|,|。|；|;|$)",
        r"涉及(.+?)(?:如果|是否|有哪|哪些|什么|吗|么|？|\?|，|,|。|；|;|$)",
        r"包含(.+?)(?:如果|是否|有哪|哪些|什么|吗|么|？|\?|，|,|。|；|;|$)",
        r"关于(.+?)(?:的)?(?:要求|规定|内容|条款|章节|章|？|\?|，|,|。|；|;|$)",
        r"有没有(.+?)(?:如果|是否|有哪|哪些|什么|吗|么|？|\?|，|,|。|；|;|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        keyword = cleanup_chapter_content_keyword(match.group(1))
        if keyword and not re.fullmatch(r"[A-Z]章|第.+[章节]", keyword, flags=re.IGNORECASE):
            return keyword
    return None


def cleanup_chapter_content_keyword(value: str) -> str:
    cleaned = re.sub(r"^(?:CCAR121部?|121部?|部|[A-Z]章(?:里|中|内)?|第.+?[章节](?:里|中|内)?)", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:相关)?(?:要求|规定|内容|条款)$", "", cleaned)
    return cleaned.strip(" ：:，,。？?的里中内")


def rows_matching_keyword(
    rows: list[DocumentChunk],
    keyword: str,
    limit: int,
    heading_title: Optional[str] = None,
) -> list[DocumentChunk]:
    normalized_keyword = normalize_for_match(keyword)
    normalized_heading = normalize_heading(heading_title or "")
    matched: list[DocumentChunk] = []
    for row in rows:
        content = content_after_heading(row.content, normalized_heading)
        normalized_content = normalize_for_match(content)
        if normalized_keyword and normalized_keyword not in normalized_content:
            continue
        matched.append(row)
        if len(matched) >= limit:
            break
    return matched


def build_chapter_keyword_sources(
    document: Document,
    all_rows: list[DocumentChunk],
    matched_rows: list[DocumentChunk],
    keyword: str,
    limit: int,
) -> list[SourceOut]:
    sources: list[SourceOut] = []
    seen_articles: set[str] = set()
    row_index_by_id = {row.id: index for index, row in enumerate(all_rows)}
    for row in matched_rows:
        row_index = row_index_by_id.get(row.id)
        if row_index is None:
            continue
        matching_articles = article_numbers_matching_keyword(all_rows, row_index, keyword)
        for article_no in matching_articles:
            if article_no in seen_articles:
                continue
            article_index = find_article_chunk_index(all_rows, article_no)
            if article_index is None:
                continue
            source = build_article_lookup_source(document, all_rows, article_index, article_no, max_rows=3)
            source.evidence["retrieval_type"] = "chapter_keyword_article"
            source.metadata["source_type"] = "chapter_keyword_article"
            sources.append(source)
            seen_articles.add(article_no)
            if len(sources) >= limit:
                return sources

    return sources


def article_numbers_matching_keyword(
    rows: list[DocumentChunk],
    row_index: int,
    keyword: str,
) -> list[str]:
    row = rows[row_index]
    article_numbers = article_heading_numbers_for_row(row)
    normalized_keyword = normalize_for_match(keyword)
    matched: list[str] = []
    for article_no in article_numbers:
        article_index = find_article_chunk_index(rows, article_no)
        if article_index is None:
            continue
        clipped = clip_article_content_from_rows(rows[article_index : article_index + 3], article_no)
        if normalized_keyword and normalized_keyword not in normalize_for_match(clipped):
            continue
        matched.append(article_no)
    return matched


def article_heading_numbers_for_row(row: DocumentChunk) -> list[str]:
    articles: list[str] = []
    pattern = re.compile(r"(^|\n)\s*(?:第\s*)?(\d{2,3}\.\d{1,4})\s*条")
    for match in pattern.finditer(row.content):
        article_no = match.group(2)
        if article_no not in articles:
            articles.append(article_no)
    return articles


def article_numbers_for_row(row: DocumentChunk) -> list[str]:
    metadata_articles = row.chunk_metadata.get("articles", []) if row.chunk_metadata else []
    articles: list[str] = []
    for article_no in [*metadata_articles, *extract_article_numbers_from_content(row.content)]:
        if article_no not in articles:
            articles.append(article_no)
    return articles


def content_after_heading(content: str, normalized_heading: str) -> str:
    if not normalized_heading:
        return content
    for line in content.splitlines():
        if normalize_heading(line) == normalized_heading:
            return content[content.find(line) + len(line) :]
    return content


def extract_chapter_key(question: str) -> Optional[str]:
    keys = extract_chapter_keys(question)
    return keys[0] if keys else None


def extract_chapter_keys(question: str) -> list[str]:
    normalized = question.upper()
    keys: list[str] = []
    for match in re.finditer(r"(^|[^A-Z])([A-Z])\s*章", normalized):
        key = match.group(2)
        if key not in keys:
            keys.append(key)

    for match in re.finditer(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*[章节]", question):
        key = match.group(1)
        if key not in keys:
            keys.append(key)
    return keys


def find_outline_item(chapters: list[OutlineItem], chapter_key: str) -> Optional[OutlineItem]:
    normalized_key = chapter_key.upper()
    for item in chapters:
        title = normalize_heading(item.title).upper()
        if re.match(rf"^{re.escape(normalized_key)}\s*章", title):
            return item
        if title.startswith(f"第{chapter_key}章") or title.startswith(f"第{chapter_key}节"):
            return item
    return None


def rows_for_outline_item(
    rows: list[DocumentChunk],
    chapters: list[OutlineItem],
    target: OutlineItem,
) -> list[DocumentChunk]:
    start = find_body_heading_chunk_index(rows, target.title)
    if start is None:
        start = target.first_chunk_index

    next_starts = sorted(
        index
        for item in chapters
        if item.title != target.title
        for index in [find_body_heading_chunk_index(rows, item.title)]
        if index is not None and index > start
    )
    end = min(next_starts) if next_starts else None
    return [
        row
        for row in rows
        if row.chunk_index >= start and (end is None or row.chunk_index < end)
    ]


def find_body_heading_chunk_index(rows: list[DocumentChunk], title: str) -> Optional[int]:
    normalized_title = normalize_heading(title)
    matches: list[int] = []
    for row in rows:
        for line in row.content.splitlines():
            if normalize_heading(line) == normalized_title:
                matches.append(row.chunk_index)
                break

    if not matches:
        return None
    if matches[0] == 0 and len(matches) > 1:
        return matches[1]
    non_toc_matches = [
        index
        for index in matches
        if "目录" not in rows[index].content[:800]
    ]
    body_matches = [
        index
        for index in non_toc_matches
        if (rows[index].chunk_metadata or {}).get("article_count", 0) > 0
    ]
    if body_matches:
        return body_matches[0]
    return non_toc_matches[0] if non_toc_matches else matches[0]


def chunk_to_source(document: Document, chunk: DocumentChunk, source_type: str) -> SourceOut:
    return SourceOut(
        document_id=document.id,
        document_title=document.title,
        chunk_id=chunk.id,
        content=chunk.content,
        chapter=chunk.chapter,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        score=None,
        evidence=build_evidence_card(document, chunk, source_type),
        metadata={
            **(chunk.chunk_metadata or {}),
            **document_source_metadata(document),
            "source_type": source_type,
            "doc_type": document.doc_type,
            "version": document.version,
            "effective_date": (
                document.effective_date.isoformat() if document.effective_date else None
            ),
        },
    )


def try_answer_approach_facility_minima_question(
    db: Session,
    question: str,
) -> Optional[tuple[str, list[SourceOut]]]:
    if not is_approach_facility_minima_calculation_question(question):
        return None
    facility_count = extract_approach_facility_count(question)
    if facility_count is None:
        return None

    document, rows = find_document_rows_for_article(db, question, "121.643")
    if not document or not rows:
        return None

    article_index = find_article_chunk_index(rows, "121.643")
    if article_index is None:
        return None
    selected = rows[article_index : article_index + 2]
    sources = [chunk_to_source(document, row, "approach_facility_minima") for row in selected]
    for source in sources:
        source.evidence["article"] = "121.643"
        source.evidence["label"] = build_article_evidence_label(source.evidence, "121.643")
        source.metadata["primary_article"] = "121.643"
    return build_approach_facility_minima_answer(document, facility_count), sources


def try_answer_approach_facility_minima_overview_question(
    db: Session,
    question: str,
) -> Optional[tuple[str, list[SourceOut]]]:
    if not is_approach_facility_minima_overview_question(question):
        return None

    document, rows = find_document_rows_for_article(db, question, "121.643")
    if not document or not rows:
        return None

    article_index = find_article_chunk_index(rows, "121.643")
    if article_index is None:
        return None
    selected = rows[article_index : article_index + 2]
    sources = [chunk_to_source(document, row, "approach_facility_minima_overview") for row in selected]
    for source in sources:
        source.evidence["article"] = "121.643"
        source.evidence["label"] = build_article_evidence_label(source.evidence, "121.643")
        source.metadata["primary_article"] = "121.643"
    return build_approach_facility_minima_overview_answer(document), sources


def is_approach_facility_minima_overview_question(question: str) -> bool:
    if not has_approach_facility_minima_topic(question):
        return False
    overview_keywords = [
        "是这样吗",
        "是不是",
        "是否",
        "有几种",
        "几种情况",
        "两种情况",
        "分几档",
        "几档",
        "一套和两套",
        "一套、两套",
        "一套，两套",
    ]
    return any(keyword in question for keyword in overview_keywords)


def is_approach_facility_minima_calculation_question(question: str) -> bool:
    if extract_approach_facility_count(question) is None:
        return False
    if not has_approach_facility_topic(question):
        return False
    calculation_keywords = [
        "加多少",
        "增加多少",
        "怎么加",
        "该加",
        "要加",
        "应加",
        "按哪档",
        "哪一档",
        "标准多少",
        "增加值",
    ]
    return any(keyword in question for keyword in calculation_keywords)


def has_approach_facility_minima_topic(question: str) -> bool:
    if not has_approach_facility_topic(question):
        return False
    return any(keyword in question for keyword in ["最低天气标准", "备降", "备降标准"])


def has_approach_facility_topic(question: str) -> bool:
    return any(keyword in question for keyword in ["进近设施", "进近程序"])


def find_document_rows_for_article(
    db: Session,
    question: str,
    article_no: str,
) -> tuple[Optional[Document], list[DocumentChunk]]:
    document = find_document_for_question(db, question)
    if document:
        rows = rows_for_document(db, document.id)
        if find_article_chunk_index(rows, article_no) is not None:
            return document, rows

    documents = (
        db.query(Document)
        .filter(Document.status == DocumentStatus.ready)
        .order_by(Document.created_at.desc())
        .all()
    )
    for candidate in documents:
        rows = rows_for_document(db, candidate.id)
        if find_article_chunk_index(rows, article_no) is not None:
            return candidate, rows
    return None, []


def rows_for_document(db: Session, document_id: str) -> list[DocumentChunk]:
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )


def extract_approach_facility_count(question: str) -> Optional[int]:
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "1": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
    }
    match = re.search(r"([一二两三四五1-5])\s*套", question)
    if not match:
        return None
    return mapping.get(match.group(1))


def build_approach_facility_minima_answer(document: Document, facility_count: int) -> str:
    if facility_count >= 2:
        applied_rule = "至少有两套能够提供不同跑道直线进近的可用进近设施"
        increment = (
            "在两个服务于不同适用跑道的相应直线进近程序中，"
            "取 DH/MDH 较高值再增加 60 米（200 英尺），"
            "取 VIS 较高值再增加 800 米（1/2 英里）。"
        )
        note = (
            f"{facility_count} 套进近设施没有单独更高一档；只要满足“{applied_rule}”的条件，"
            "就按“两套或以上”这一档计算。"
        )
    else:
        applied_rule = "至少有一套可用进近设施"
        increment = "MDH/DH 增加 120 米（400 英尺），VIS 增加 1,600 米（1 英里）。"
        note = "只有一套可用进近设施时，不能套用“两套或以上”的较低增加值。"

    return (
        f"结论：对于 {facility_count} 套进近设施的机场，应按“{applied_rule}”规则判断。\n\n"
        f"应增加的数值：{increment}\n\n"
        f"依据：{document.title} 第121.643条“备降机场最低天气标准”。\n\n"
        f"判断说明：{note}\n\n"
        "风险提示：必须确认这些进近设施可用、能提供直线 NPA/APV/I 类 PA，"
        "且所选两套设施服务于不同适用跑道；否则不能直接按两套或以上规则计算。"
    )


def build_approach_facility_minima_overview_answer(document: Document) -> str:
    return (
        "是的。按常规备降机场最低天气标准，进近设施数量主要分两档判断：\n\n"
        "1. 至少有一套可用进近设施：MDH/DH 增加 120 米（400 英尺），"
        "VIS 增加 1,600 米（1 英里）。\n"
        "2. 至少有两套能够提供不同跑道直线进近的可用进近设施："
        "取两个相应程序的 DH/MDH 较高值再增加 60 米（200 英尺），"
        "取 VIS 较高值再增加 800 米（1/2 英里）。\n\n"
        f"依据：{document.title} 第121.643条“备降机场最低天气标准”。\n\n"
        "注意：这里的“两套”不是单纯数量够就行，还要能提供不同适用跑道的直线进近。"
        "另外，II/III 类精密进近、GNSS APV 等情形还可能有专门补充要求。"
    )


def build_article_evidence_label(evidence: dict, article_no: str) -> str:
    parts = [str(evidence.get("title") or "文档")]
    if evidence.get("section"):
        parts.append(str(evidence["section"]))
    parts.append(f"第{article_no}条")
    if evidence.get("page_label"):
        parts.append(str(evidence["page_label"]))
    return " / ".join(parts)


def try_answer_article_question(
    db: Session,
    question: str,
    settings: Settings,
) -> Optional[tuple[str, list[SourceOut]]]:
    article_numbers = extract_article_numbers(question)
    if not article_numbers:
        return None

    sources: list[SourceOut] = []
    missing_articles: list[str] = []
    seen_article_sources: set[tuple[str, str]] = set()
    per_article_limit = max(1, min(3, settings.top_k))
    for article_no in article_numbers:
        document, rows = find_document_rows_for_article(db, question, article_no)
        if not document or not rows:
            missing_articles.append(article_no)
            continue
        matched_index = find_article_chunk_index(rows, article_no)
        if matched_index is None:
            missing_articles.append(article_no)
            continue
        source_key = (document.id, article_no)
        if source_key in seen_article_sources:
            continue
        sources.append(
            build_article_lookup_source(
                document,
                rows,
                matched_index,
                article_no,
                per_article_limit,
            )
        )
        seen_article_sources.add(source_key)

    if not sources:
        return build_missing_article_answer(article_numbers), []

    mark_article_lookup_sources(sources, article_numbers)
    answer = get_llm_provider(settings).answer(question, sources)
    if missing_articles:
        answer = append_missing_article_note(answer, missing_articles)
    return answer, sources


def extract_article_number(question: str) -> Optional[str]:
    numbers = extract_article_numbers(question)
    return numbers[0] if numbers else None


def extract_article_numbers(question: str) -> list[str]:
    matches = re.findall(r"(?:第\s*)?(\d{2,3}\.\d{1,4})\s*(?:条)?", question)
    numbers: list[str] = []
    for match in matches:
        if match not in numbers:
            numbers.append(match)
    return numbers


def mark_article_lookup_sources(sources: list[SourceOut], article_numbers: list[str]) -> None:
    for source in sources:
        source_articles = source.metadata.get("articles", [])
        primary_article = source.metadata.get("primary_article")
        if primary_article is None:
            primary_article = next(
                (article_no for article_no in article_numbers if article_no in source_articles),
                None,
            )
        if primary_article is None:
            primary_article = next(
                (
                    article_no
                    for article_no in article_numbers
                    if contains_article_reference(source.content, article_no)
                ),
                article_numbers[0],
            )
        source.evidence["article"] = primary_article
        source.evidence["label"] = build_article_evidence_label(source.evidence, primary_article)
        source.metadata["primary_article"] = primary_article
        source.metadata["requested_articles"] = article_numbers


def build_article_lookup_source(
    document: Document,
    rows: list[DocumentChunk],
    matched_index: int,
    article_no: str,
    max_rows: int,
) -> SourceOut:
    row = rows[matched_index]
    source = chunk_to_source(document, row, "article_lookup")
    source.content = clip_article_content_from_rows(
        rows[matched_index : matched_index + max_rows],
        article_no,
    )
    source.metadata["primary_article"] = article_no
    source.metadata["requested_articles"] = [article_no]
    source.metadata["clipped_to_article"] = True
    source.evidence["article"] = article_no
    source.evidence["label"] = build_article_evidence_label(source.evidence, article_no)
    return source


def clip_article_content_from_rows(rows: list[DocumentChunk], article_no: str) -> str:
    combined = "\n".join(row.content for row in rows).strip()
    if not combined:
        return ""

    start = find_article_heading_position(combined, article_no)
    if start is None:
        start = 0
    end = find_next_article_heading_position(combined, article_no, start + 1)
    return combined[start:end].strip() if end is not None else combined[start:].strip()


def find_article_heading_position(content: str, article_no: str) -> Optional[int]:
    patterns = [
        re.compile(rf"(^|\n)\s*第\s*{re.escape(article_no)}\s*条"),
        re.compile(rf"(^|\n)\s*{re.escape(article_no)}\s*条"),
    ]
    positions = [
        match.start() + len(match.group(1))
        for pattern in patterns
        for match in [pattern.search(content)]
        if match
    ]
    return min(positions) if positions else None


def find_next_article_heading_position(
    content: str,
    current_article_no: str,
    start: int,
) -> Optional[int]:
    pattern = re.compile(r"(^|\n)\s*(?:第\s*)?(\d{2,3}\.\d{1,4})\s*条")
    positions = [
        match.start() + len(match.group(1))
        for match in pattern.finditer(content, start)
        if match.group(2) != current_article_no
    ]
    return min(positions) if positions else None


def contains_article_reference(content: str, article_no: str) -> bool:
    patterns = [
        rf"第\s*{re.escape(article_no)}\s*条",
        rf"(^|\n)\s*{re.escape(article_no)}\s*条?",
    ]
    return any(re.search(pattern, content) for pattern in patterns)


def build_missing_article_answer(article_numbers: list[str]) -> str:
    joined = "、".join(f"第{article_no}条" for article_no in article_numbers)
    return (
        f"结论：未在当前已处理的知识库文档中命中 {joined} 的正文。\n\n"
        "建议：请确认对应手册已经上传并处理完成，或在文档片段中检查该条款编号是否因 OCR、换行、版本差异被识别成其他形式。"
    )


def append_missing_article_note(answer: str, missing_articles: list[str]) -> str:
    joined = "、".join(f"第{article_no}条" for article_no in missing_articles)
    return (
        f"{answer}\n\n"
        f"补充说明：当前知识库未命中 {joined} 的正文；以上回答仅基于已命中的条款片段。"
    )


def normalize_article_number(value: str) -> str:
    match = re.search(r"(\d{2,3}\.\d{1,4})", value)
    return match.group(1) if match else value.strip()


def find_article_chunk_index(rows: list[DocumentChunk], article_no: str) -> Optional[int]:
    heading_patterns = [
        re.compile(rf"(^|\n)\s*第\s*{re.escape(article_no)}\s*条"),
        re.compile(rf"(^|\n)\s*{re.escape(article_no)}\s*条"),
    ]
    heading_matches: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        positions = [
            match.start()
            for pattern in heading_patterns
            for match in [pattern.search(row.content)]
            if match
        ]
        if positions:
            heading_matches.append((min(positions), index))
    if heading_matches:
        return min(heading_matches)[1]

    reference_patterns = [
        re.compile(rf"第\s*{re.escape(article_no)}\s*条"),
        re.compile(rf"\b{re.escape(article_no)}\s*条"),
    ]
    matches: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        positions = [
            match.start()
            for pattern in reference_patterns
            for match in [pattern.search(row.content)]
            if match
        ]
        if positions:
            matches.append((min(positions), index))
    if matches:
        return min(matches)[1]

    for index, row in enumerate(rows):
        metadata_articles = row.chunk_metadata.get("articles", []) if row.chunk_metadata else []
        if article_no in metadata_articles:
            return index
    return None
