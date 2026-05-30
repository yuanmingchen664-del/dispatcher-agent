from backend.app.services.chunker import (
    extract_article_numbers_from_content,
    is_appendix_heading,
    is_article_line,
    is_chapter_heading,
    normalize_heading,
    TextPage,
    split_pages_into_chunks,
)
from backend.app.api.routes import (
    append_missing_article_note,
    article_heading_numbers_for_row,
    article_numbers_for_row,
    article_numbers_matching_keyword,
    build_approach_facility_minima_answer,
    build_approach_facility_minima_overview_answer,
    build_missing_article_answer,
    classify_question,
    clip_article_content_from_rows,
    contains_article_reference,
    extract_approach_facility_count,
    extract_article_numbers,
    find_article_heading_position,
    find_body_heading_chunk_index,
    find_next_article_heading_position,
    extract_chapter_filter_keyword,
    extract_chapter_content_keyword,
    extract_chapter_key,
    filter_chapters_by_keyword,
    is_approach_facility_minima_calculation_question,
    is_approach_facility_minima_overview_question,
    QuestionIntent,
    rows_matching_keyword,
)
from backend.app.schemas import OutlineItem


class FakeChunk:
    def __init__(self, content, metadata=None, id="fake", chunk_index=0):
        self.id = id
        self.chunk_index = chunk_index
        self.content = content
        self.chunk_metadata = metadata or {}


class FakeDocument:
    title = "CCAR121"


def test_split_pages_into_chunks_keeps_page_range():
    pages = [
        TextPage(page_number=1, text="第一章 总则\n\n这是第一段。" * 20),
        TextPage(page_number=2, text="这是第二页内容。" * 20),
    ]

    chunks = split_pages_into_chunks(pages, max_chars=200, overlap_chars=20)

    assert chunks
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end in {1, 2}
    assert all(chunk.content for chunk in chunks)


def test_split_pages_into_chunks_uses_actual_block_pages():
    pages = [
        TextPage(page_number=1, text="A 章 总则\n\n第121.1 条 目的\n第一页内容。" * 10),
        TextPage(page_number=2, text="第121.3 条 适用范围\n第二页内容。" * 10),
    ]

    chunks = split_pages_into_chunks(pages, max_chars=180, overlap_chars=0)

    assert chunks
    assert chunks[0].page_start == 1
    assert any(chunk.page_start == 2 and chunk.page_end == 2 for chunk in chunks)


def test_split_pages_into_chunks_prefers_chapter_boundaries():
    pages = [
        TextPage(
            page_number=1,
            text=(
                "签派助手测试手册\n\n"
                "第一章 目的地天气放行标准\n\n"
                "1.1 计划放行时，应检查目的地机场预计到达时段的 METAR、TAF。\n"
                "1.2 如目的地机场低于适用着陆最低标准，不得仅以该目的地放行。\n\n"
                "第二章 备降机场选择\n\n"
                "2.1 备降机场必须在预计使用时段满足适用天气标准。\n"
                "2.2 选择备降机场时，应检查 NOTAM、跑道关闭和导航台失效。"
            ),
        )
    ]

    chunks = split_pages_into_chunks(pages, max_chars=120, overlap_chars=0)

    assert len(chunks) >= 2
    assert any(chunk.chapter == "第一章 目的地天气放行标准" for chunk in chunks)
    assert any(chunk.chapter == "第二章 备降机场选择" for chunk in chunks)
    assert any("1.1" in chunk.metadata["articles"] for chunk in chunks)


def test_regulation_heading_patterns():
    assert is_chapter_heading("A 章  总  则")
    assert is_chapter_heading("R章 基于胜任力的培训和评估方案")
    assert is_chapter_heading("U 章  签派和飞行放行")
    assert not is_chapter_heading("W 章；")
    assert is_appendix_heading("附件A  定  义")
    assert is_article_line("第121.1 条 目的和依据")
    assert normalize_heading("A 章  总  则") == "A 章 总 则"
    assert normalize_heading("R章 基于胜任力的培训和评估方案") == "R 章 基于胜任力的培训和评估方案"


def test_extract_letter_chapter_from_chinese_question():
    assert extract_chapter_key("归纳一下ccar121部 A 章主要讲了什么") == "A"


def test_extract_chapter_filter_keyword_from_which_chapters_question():
    assert extract_chapter_filter_keyword("ccar121 哪几章是关于签派放行的") == "签派放行"


def test_filter_chapters_by_dispatch_release_keyword():
    chapters = [
        OutlineItem(title="Q 章 飞行签派员的合格要求和值勤时间限制", kind="chapter", first_chunk_index=1, page_start=1, page_end=1),
        OutlineItem(title="U 章 签派和飞行放行", kind="chapter", first_chunk_index=2, page_start=2, page_end=2),
        OutlineItem(title="T 章 飞行运行", kind="chapter", first_chunk_index=3, page_start=3, page_end=3),
    ]

    matched = filter_chapters_by_keyword(chapters, "签派放行")

    assert [item.title for item in matched] == ["U 章 签派和飞行放行"]


def test_extract_chapter_content_keyword_from_question():
    question = "CCAR121 部 U 章里有没有提到备降机场？如果有，涉及哪些要求？"

    assert extract_chapter_content_keyword(question) == "备降机场"


def test_rows_matching_keyword_searches_full_chapter():
    rows = [
        FakeChunk("U 章 签派和飞行放行\n第121.621条 签派权"),
        FakeChunk("第121.629条 通信和导航设施"),
        FakeChunk("第121.637条 起飞备降机场\n起飞机场气象条件低于标准时，应选择起飞备降机场。"),
    ]

    matched = rows_matching_keyword(rows, "备降机场", limit=5)

    assert matched == [rows[2]]


def test_find_body_heading_chunk_index_prefers_article_body_over_toc():
    rows = [
        FakeChunk("U 章 签派和飞行放行", metadata={"article_count": 0}, chunk_index=0),
        FakeChunk("U 章 签派和飞行放行\n第121.621条 签派权", metadata={"article_count": 1}, chunk_index=1),
    ]

    assert find_body_heading_chunk_index(rows, "U 章 签派和飞行放行") == 1


def test_article_numbers_for_row_merges_metadata_and_content():
    row = FakeChunk(
        "第121.637条 起飞备降机场\n121.639 条 目的地备降机场",
        metadata={"articles": ["121.635", "121.637"]},
    )

    assert article_numbers_for_row(row) == ["121.635", "121.637", "121.639"]


def test_article_heading_numbers_for_row_ignores_references():
    row = FakeChunk(
        "第121.642 条 目的地备降机场\n本条引用本规则第121.643 条规定的标准。"
    )

    assert article_heading_numbers_for_row(row) == ["121.642"]


def test_article_numbers_matching_keyword_returns_relevant_articles():
    rows = [
        FakeChunk("第121.637条 起飞备降机场\n应选择起飞备降机场。", id="1"),
        FakeChunk("第121.639条 目的地机场\n目的地机场要求。", id="2"),
        FakeChunk("第121.641条 目的地备降机场\n应列出目的地备降机场。", id="3"),
    ]

    assert article_numbers_matching_keyword(rows, 0, "备降机场") == ["121.637"]
    assert article_numbers_matching_keyword(rows, 1, "备降机场") == []


def test_extract_article_numbers_from_content_normalizes_article_heading():
    content = "第121.637 条 起飞备降机场\n(a) 应选择起飞备降机场。\n121.639 条 目的地备降机场"

    assert extract_article_numbers_from_content(content) == ["121.637", "121.639"]


def test_extract_article_numbers_from_question():
    question = "CCAR121部第121.3条和第121.5条分别讲什么？"

    assert extract_article_numbers(question) == ["121.3", "121.5"]


def test_contains_article_reference_supports_heading_forms():
    assert contains_article_reference("第121.637 条 起飞备降机场", "121.637")
    assert contains_article_reference("121.639 条 目的地备降机场", "121.639")
    assert not contains_article_reference("第121.637 条 起飞备降机场", "121.639")


def test_find_article_heading_position():
    content = "A 章 总则\n第121.3 条 适用范围\n正文\n第121.5 条 定义"

    assert find_article_heading_position(content, "121.3") == content.index("第121.3")
    assert find_article_heading_position(content, "121.5") == content.index("第121.5")
    assert find_article_heading_position(content, "121.7") is None


def test_find_next_article_heading_position():
    content = "第121.3 条 适用范围\n正文\n第121.5 条 定义"

    assert find_next_article_heading_position(content, "121.3", 1) == content.index("第121.5")
    assert find_next_article_heading_position(content, "121.5", content.index("定义")) is None


def test_clip_article_content_from_rows_stops_before_next_article():
    rows = [
        FakeChunk("A 章 总则\n第121.3 条 适用范围\n121.3正文\n第121.5 条 定义\n121.5正文"),
        FakeChunk("第121.7 条 运行合格审定\n121.7正文"),
    ]

    clipped = clip_article_content_from_rows(rows, "121.5")

    assert clipped.startswith("第121.5 条 定义")
    assert "121.5正文" in clipped
    assert "第121.7 条" not in clipped


def test_missing_article_answer_names_requested_articles():
    answer = build_missing_article_answer(["121.3", "121.5"])

    assert "第121.3条" in answer
    assert "第121.5条" in answer
    assert "未在当前已处理的知识库文档中命中" in answer


def test_append_missing_article_note():
    answer = append_missing_article_note("已命中第121.637条。", ["121.643"])

    assert "第121.643条" in answer
    assert "仅基于已命中的条款片段" in answer


def test_extract_approach_facility_count():
    assert extract_approach_facility_count("对于三套进近设施的机场又该加多少呢？") == 3
    assert extract_approach_facility_count("两套进近设施怎么加？") == 2


def test_build_approach_facility_minima_answer_for_three_facilities():
    answer = build_approach_facility_minima_answer(FakeDocument(), 3)

    assert "两套或以上" in answer
    assert "增加 60 米" in answer
    assert "增加 800 米" in answer


def test_approach_facility_minima_overview_question():
    question = "我记得备降机场最低天气标准有一套和两套进近设施两种情况，是这样吗？"

    assert is_approach_facility_minima_overview_question(question)
    assert not is_approach_facility_minima_calculation_question(question)


def test_approach_facility_minima_calculation_question():
    question = "对于三套进近设施的机场又该加多少呢？"

    assert is_approach_facility_minima_calculation_question(question)
    assert not is_approach_facility_minima_overview_question(question)


def test_build_approach_facility_minima_overview_answer():
    answer = build_approach_facility_minima_overview_answer(FakeDocument())

    assert "主要分两档" in answer
    assert "至少有一套可用进近设施" in answer
    assert "至少有两套" in answer
    assert "第121.643条" in answer


def test_classify_question_intents():
    assert classify_question("CCAR121 部有没有 D 章？") == QuestionIntent.CHAPTER_EXISTENCE
    assert classify_question("CCAR121 部 U 章里有没有提到备降机场？") == QuestionIntent.CHAPTER_CONTENT
    assert classify_question("ccar121 哪几章是关于签派放行的") == QuestionIntent.OUTLINE
    assert classify_question("CCAR121部第121.3条和第121.5条分别讲什么") == QuestionIntent.ARTICLE_LOOKUP
    assert (
        classify_question("我记得备降机场最低天气标准有一套和两套进近设施两种情况，是这样吗？")
        == QuestionIntent.APPROACH_MINIMA_OVERVIEW
    )
    assert classify_question("对于三套进近设施的机场又该加多少呢？") == QuestionIntent.APPROACH_MINIMA_CALCULATION
