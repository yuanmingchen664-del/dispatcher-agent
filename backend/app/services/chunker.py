import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class TextPage:
    page_number: int
    text: str


@dataclass
class TextChunk:
    content: str
    page_start: Optional[int]
    page_end: Optional[int]
    chapter: Optional[str]
    metadata: dict


CHAPTER_PATTERN = re.compile(
    r"^(第[一二三四五六七八九十百零〇0-9]+[章节篇部].+|Chapter\s+\d+.+|Section\s+\d+.+)$",
    re.IGNORECASE,
)
ARTICLE_PATTERN = re.compile(r"^(\d+(?:\.\d+)+|[A-Z]\.|[a-z]\)|\([一二三四五六七八九十0-9]+\))\s+")


def split_pages_into_chunks(
    pages: list[TextPage],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current_chapter: Optional[str] = None
    current_blocks: list[str] = []
    current_page_start: Optional[int] = None
    current_page_end: Optional[int] = None

    for page in pages:
        blocks = split_text_blocks(page.text)
        if not blocks:
            continue

        for block in blocks:
            if is_chapter_heading(block):
                chunks.extend(
                    _flush_blocks(
                        current_blocks,
                        current_page_start,
                        current_page_end,
                        current_chapter,
                        max_chars,
                        overlap_chars,
                    )
                )
                current_chapter = block
                current_blocks = [block]
                current_page_start = page.page_number
                current_page_end = page.page_number
                continue

            if current_page_start is None:
                current_page_start = page.page_number
            current_page_end = page.page_number
            current_blocks.append(block)

    chunks.extend(
        _flush_blocks(
            current_blocks,
            current_page_start,
            current_page_end,
            current_chapter,
            max_chars,
            overlap_chars,
        )
    )

    return chunks


def split_text_blocks(text: str) -> list[str]:
    normalized = normalize_text(text)
    blocks: list[str] = []
    for raw_block in normalized.split("\n\n"):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        for line in lines:
            if is_chapter_heading(line) or is_article_line(line):
                blocks.append(line)
                continue
            if not blocks:
                blocks.append(line)
            elif _looks_like_continuation(line):
                blocks[-1] = f"{blocks[-1]}\n{line}"
            else:
                blocks.append(line)
    return blocks


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    output: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if output and not blank_seen:
                output.append("")
            blank_seen = True
            continue
        output.append(line)
        blank_seen = False
    return "\n".join(output).strip()


def is_chapter_heading(text: str) -> bool:
    line = text.strip()
    return len(line) <= 80 and bool(CHAPTER_PATTERN.match(line))


def is_article_line(text: str) -> bool:
    return bool(ARTICLE_PATTERN.match(text.strip()))


def _looks_like_continuation(line: str) -> bool:
    return bool(line) and not is_chapter_heading(line) and not is_article_line(line)


def _flush_blocks(
    blocks: list[str],
    page_start: Optional[int],
    page_end: Optional[int],
    chapter: Optional[str],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    if not blocks:
        return []

    chunks: list[TextChunk] = []
    buffer: list[str] = []

    for block in blocks:
        proposed = "\n".join([*buffer, block]).strip()
        if len(proposed) <= max_chars:
            buffer.append(block)
            continue

        if buffer:
            chunks.append(_build_chunk("\n".join(buffer), page_start, page_end, chapter))
            buffer = _overlap_blocks(buffer, overlap_chars, chapter)

        if len(block) > max_chars:
            chunks.extend(_split_long_block(block, page_start, page_end, chapter, max_chars, overlap_chars))
            buffer = []
        else:
            buffer.append(block)

    if buffer:
        chunks.append(_build_chunk("\n".join(buffer), page_start, page_end, chapter))

    return chunks


def _split_long_block(
    block: str,
    page_start: Optional[int],
    page_end: Optional[int],
    chapter: Optional[str],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    start = 0
    while start < len(block):
        end = min(start + max_chars, len(block))
        chunks.append(_build_chunk(block[start:end], page_start, page_end, chapter))
        if end == len(block):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _overlap_blocks(blocks: list[str], overlap_chars: int, chapter: Optional[str]) -> list[str]:
    if overlap_chars <= 0:
        return [chapter] if chapter else []

    selected: list[str] = []
    char_count = 0
    for block in reversed(blocks):
        if block == chapter:
            continue
        selected.insert(0, block)
        char_count += len(block)
        if char_count >= overlap_chars:
            break

    if chapter and (not selected or selected[0] != chapter):
        selected.insert(0, chapter)
    return selected


def _build_chunk(
    content: str,
    page_start: Optional[int],
    page_end: Optional[int],
    chapter: Optional[str],
) -> TextChunk:
    resolved_chapter = chapter or _guess_chapter(content)
    articles = [line.split(maxsplit=1)[0] for line in content.splitlines() if is_article_line(line)]
    return TextChunk(
        content=content.strip(),
        page_start=page_start,
        page_end=page_end,
        chapter=resolved_chapter,
        metadata={
            "char_count": len(content),
            "article_count": len(articles),
            "articles": articles,
        },
    )


def _guess_chapter(content: str) -> Optional[str]:
    first_line = content.splitlines()[0].strip() if content.splitlines() else ""
    if is_chapter_heading(first_line):
        return first_line
    return None
