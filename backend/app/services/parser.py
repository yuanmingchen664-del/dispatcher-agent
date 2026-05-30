from pathlib import Path
from typing import Optional

import fitz

from backend.app.core.config import Settings
from backend.app.services.chunker import TextPage
from backend.app.services.ocr import get_ocr_provider


def parse_document(path: str, mime_type: Optional[str], settings: Settings) -> list[TextPage]:
    suffix = Path(path).suffix.lower()
    if mime_type == "application/pdf" or suffix == ".pdf":
        return parse_pdf(path, settings)
    if suffix in {".txt", ".md"}:
        return [TextPage(page_number=1, text=Path(path).read_text(encoding="utf-8"))]
    raise ValueError(f"Unsupported document type: {mime_type or suffix}")


def parse_pdf(path: str, settings: Settings) -> list[TextPage]:
    pages: list[TextPage] = []
    ocr_provider = get_ocr_provider(settings)
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if ocr_provider and len(text) < settings.ocr_min_text_chars:
                pixmap = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
                text = ocr_provider.recognize_png(pixmap.tobytes("png")).strip()
            pages.append(TextPage(page_number=index, text=text))
    return pages
