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


@dataclass
class TextBlock:
    text: str
    page_number: int


CHAPTER_PATTERN = re.compile(
    r"^("
    r"第[一二三四五六七八九十百零〇0-9]+[章节篇部]\s*.+"
    r"|[A-Z]\s*章\s*[\u4e00-\u9fffA-Za-z0-9（(].+"
    r"|Chapter\s+\d+.+"
    r"|Section\s+\d+.+"
    r")$",
    re.IGNORECASE,
)
APPENDIX_PATTERN = re.compile(r"^(附件\s*[A-Z一二三四五六七八九十0-9]+|附录\s*[A-Z一二三四五六七八九十0-9]+)\s*.+")
ARTICLE_PATTERN = re.compile(
    r"^(第\s*\d+(?:\.\d+)*\s*条|\d+(?:\.\d+)+|[A-Z]\.|[a-z]\)|\([一二三四五六七八九十0-9]+\))\s*"
)


def split_pages_into_chunks(
    pages: list[TextPage],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current_chapter: Optional[str] = None
    current_blocks: list[TextBlock] = []

    for page in pages:
        blocks = split_text_blocks(page.text)
        if not blocks:
            continue

        for block in blocks:
            if is_chapter_heading(block):
                chunks.extend(
                    _flush_blocks(
                        current_blocks,
                        current_chapter,
                        max_chars,
                        overlap_chars,
                    )
                )
                current_chapter = block
                current_blocks = [TextBlock(text=block, page_number=page.page_number)]
                continue

            current_blocks.append(TextBlock(text=block, page_number=page.page_number))

    chunks.extend(
        _flush_blocks(
            current_blocks,
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


def is_appendix_heading(text: str) -> bool:
    line = text.strip()
    return len(line) <= 100 and bool(APPENDIX_PATTERN.match(line))


def normalize_heading(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(r"^([A-Z])\s*章\s*", r"\1 章 ", normalized)
    normalized = re.sub(r"^(附件|附录)\s*([A-Z一二三四五六七八九十0-9]+)\s*", r"\1\2 ", normalized)
    return normalized.strip()


def is_article_line(text: str) -> bool:
    return bool(ARTICLE_PATTERN.match(text.strip()))


def _looks_like_continuation(line: str) -> bool:
    return bool(line) and not is_chapter_heading(line) and not is_article_line(line)


def _flush_blocks(
    blocks: list[TextBlock],
    chapter: Optional[str],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    if not blocks:
        return []

    chunks: list[TextChunk] = []
    buffer: list[TextBlock] = []

    for block in blocks:
        proposed = "\n".join([item.text for item in [*buffer, block]]).strip()
        if len(proposed) <= max_chars:
            buffer.append(block)
            continue

        if buffer:
            chunks.append(_build_chunk(buffer, chapter))
            buffer = _overlap_blocks(buffer, overlap_chars, chapter)

        if len(block.text) > max_chars:
            chunks.extend(_split_long_block(block, chapter, max_chars, overlap_chars))
            buffer = []
        else:
            buffer.append(block)

    if buffer:
        chunks.append(_build_chunk(buffer, chapter))

    return chunks


def _split_long_block(
    block: TextBlock,
    chapter: Optional[str],
    max_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    start = 0
    while start < len(block.text):
        end = min(start + max_chars, len(block.text))
        chunks.append(
            _build_chunk(
                [TextBlock(text=block.text[start:end], page_number=block.page_number)],
                chapter,
            )
        )
        if end == len(block.text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _overlap_blocks(
    blocks: list[TextBlock],
    overlap_chars: int,
    chapter: Optional[str],
) -> list[TextBlock]:
    if overlap_chars <= 0:
        chapter_block = next((block for block in blocks if block.text == chapter), None)
        return [chapter_block] if chapter_block else []

    selected: list[TextBlock] = []
    char_count = 0
    for block in reversed(blocks):
        if block.text == chapter:
            continue
        selected.insert(0, block)
        char_count += len(block.text)
        if char_count >= overlap_chars:
            break

    chapter_block = next((block for block in blocks if block.text == chapter), None)
    if chapter_block and (not selected or selected[0].text != chapter):
        selected.insert(0, chapter_block)
    return selected


def _build_chunk(
    blocks: list[TextBlock],
    chapter: Optional[str],
) -> TextChunk:
    content = "\n".join(block.text for block in blocks)
    pages = [block.page_number for block in blocks]
    resolved_chapter = chapter or _guess_chapter(content)
    articles = extract_article_numbers_from_content(content)
    return TextChunk(
        content=content.strip(),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
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


def extract_article_numbers_from_content(content: str) -> list[str]:
    articles: list[str] = []
    patterns = [
        re.compile(r"第\s*(\d+(?:\.\d+)*)\s*条"),
        re.compile(r"^(\d+(?:\.\d+)+)\s*条?", re.MULTILINE),
    ]
    for pattern in patterns:
        for match in pattern.finditer(content):
            article = match.group(1)
            if article not in articles:
                articles.append(article)
    return articles
