from pathlib import Path
from typing import Optional

import fitz

from backend.app.services.chunker import TextPage


def parse_document(path: str, mime_type: Optional[str]) -> list[TextPage]:
    suffix = Path(path).suffix.lower()
    if mime_type == "application/pdf" or suffix == ".pdf":
        return parse_pdf(path)
    if suffix in {".txt", ".md"}:
        return [TextPage(page_number=1, text=Path(path).read_text(encoding="utf-8"))]
    raise ValueError(f"Unsupported document type: {mime_type or suffix}")


def parse_pdf(path: str) -> list[TextPage]:
    pages: list[TextPage] = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            pages.append(TextPage(page_number=index, text=page.get_text("text")))
    return pages
