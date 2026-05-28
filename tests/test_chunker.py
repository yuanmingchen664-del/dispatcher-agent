from backend.app.services.chunker import TextPage, split_pages_into_chunks


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
