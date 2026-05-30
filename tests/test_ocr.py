from backend.app.services.ocr import extract_ocr_text


class FakePaddleResult:
    json = {"rec_texts": ["第一章 总则", "1.1 测试条款"]}


def test_extract_ocr_text_from_rec_texts_dict():
    result = [{"res": {"rec_texts": ["第一章 总则", "1.1 测试条款"]}}]

    assert extract_ocr_text(result) == "第一章 总则\n1.1 测试条款"


def test_extract_ocr_text_from_result_object():
    assert extract_ocr_text([FakePaddleResult()]) == "第一章 总则\n1.1 测试条款"


def test_extract_ocr_text_from_legacy_ocr_shape():
    result = [[[[0, 0], [1, 0], [1, 1], [0, 1]], ["目的地天气标准", 0.98]]]

    assert extract_ocr_text(result) == "目的地天气标准"
