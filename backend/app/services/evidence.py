from datetime import date
from typing import Any, Optional

from backend.app.models.document import Document, DocumentChunk


def build_document_metadata(
    source_type: Optional[str] = None,
    author: Optional[str] = None,
    department: Optional[str] = None,
    scenario: Optional[str] = None,
    reliability: Optional[str] = None,
) -> dict[str, Any]:
    metadata = {
        "source_type": normalize_source_type(source_type),
        "author": clean_optional(author),
        "department": clean_optional(department),
        "scenario": clean_optional(scenario),
        "reliability": normalize_reliability(reliability, source_type),
    }
    return {key: value for key, value in metadata.items() if value not in {None, ""}}


def document_source_metadata(document: Document) -> dict[str, Any]:
    metadata = dict(document.document_metadata or {})
    metadata.setdefault("source_type", normalize_source_type(document.doc_type))
    metadata.setdefault("reliability", normalize_reliability(None, document.doc_type))
    return metadata


def build_evidence_card(
    document: Document,
    chunk: DocumentChunk,
    retrieval_type: Optional[str] = None,
) -> dict[str, Any]:
    chunk_metadata = chunk.chunk_metadata or {}
    document_metadata = document_source_metadata(document)
    evidence_type = document_metadata.get("source_type") or "manual"
    primary_article = primary_article_from_metadata(chunk_metadata)
    page_label = build_page_label(chunk.page_start, chunk.page_end)
    section = chunk.chapter or chunk_metadata.get("section")

    card = {
        "source_type": evidence_type,
        "retrieval_type": retrieval_type,
        "title": document.title,
        "section": section,
        "article": primary_article,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "page_label": page_label,
        "record_date": date_to_string(document.effective_date),
        "version": document.version,
        "author": document_metadata.get("author"),
        "department": document_metadata.get("department"),
        "scenario": document_metadata.get("scenario"),
        "reliability": document_metadata.get("reliability"),
    }
    card["label"] = build_evidence_label(card)
    return {key: value for key, value in card.items() if value is not None}


def primary_article_from_metadata(metadata: dict[str, Any]) -> Optional[str]:
    articles = metadata.get("articles") or []
    if isinstance(articles, list) and articles:
        return str(articles[0])
    return None


def build_page_label(page_start: Optional[int], page_end: Optional[int]) -> Optional[str]:
    if page_start is None:
        return None
    if page_end is None or page_end == page_start:
        return f"第{page_start}页"
    return f"第{page_start}-{page_end}页"


def build_evidence_label(card: dict[str, Any]) -> str:
    parts = [str(card["title"])]
    if card.get("section"):
        parts.append(str(card["section"]))
    if card.get("article"):
        parts.append(f"第{card['article']}条")
    if card.get("page_label"):
        parts.append(str(card["page_label"]))

    if card.get("source_type") in {"experience", "case", "template"}:
        parts = [str(card["title"])]
        if card.get("scenario"):
            parts.append(str(card["scenario"]))
        if card.get("record_date"):
            parts.append(str(card["record_date"]))
        if card.get("author"):
            parts.append(str(card["author"]))
    return " / ".join(parts)


def normalize_source_type(value: Optional[str]) -> str:
    if not value:
        return "manual"
    normalized = value.strip().lower()
    mapping = {
        "规章": "regulation",
        "手册": "manual",
        "经验": "experience",
        "案例": "case",
        "模板": "template",
        "运行规范": "ops_spec",
    }
    return mapping.get(normalized, normalized)


def normalize_reliability(value: Optional[str], source_type: Optional[str]) -> str:
    if value:
        return value.strip().lower()
    normalized_type = normalize_source_type(source_type)
    if normalized_type == "regulation":
        return "official"
    if normalized_type in {"manual", "ops_spec"}:
        return "company"
    return "experiential"


def clean_optional(value: Optional[str]) -> Optional[str]:
    return value.strip() if value and value.strip() else None


def date_to_string(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None
