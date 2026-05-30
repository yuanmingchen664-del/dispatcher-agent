from datetime import date

from backend.app.services.evidence import (
    build_document_metadata,
    build_evidence_label,
    build_page_label,
    normalize_source_type,
)


def test_build_page_label_single_and_range():
    assert build_page_label(12, 12) == "第12页"
    assert build_page_label(12, 14) == "第12-14页"
    assert build_page_label(None, None) is None


def test_normalize_source_type_supports_chinese_alias():
    assert normalize_source_type("规章") == "regulation"
    assert normalize_source_type("经验") == "experience"
    assert normalize_source_type(None) == "manual"


def test_build_document_metadata_for_experience_record():
    metadata = build_document_metadata(
        source_type="经验",
        author="签派员A",
        department="AOC",
        scenario="低能见度放行",
    )

    assert metadata["source_type"] == "experience"
    assert metadata["reliability"] == "experiential"
    assert metadata["author"] == "签派员A"
    assert "reviewed" not in metadata


def test_build_evidence_label_for_regulation_and_experience():
    regulation = {
        "source_type": "regulation",
        "title": "CCAR121",
        "section": "U 章 签派和飞行放行",
        "article": "121.637",
        "page_label": "第243页",
    }
    experience = {
        "source_type": "experience",
        "title": "低能见度放行复盘",
        "scenario": "低能见度放行",
        "record_date": date(2026, 5, 28).isoformat(),
        "author": "签派员A",
    }

    assert build_evidence_label(regulation) == "CCAR121 / U 章 签派和飞行放行 / 第121.637条 / 第243页"
    assert build_evidence_label(experience) == "低能见度放行复盘 / 低能见度放行 / 2026-05-28 / 签派员A"
