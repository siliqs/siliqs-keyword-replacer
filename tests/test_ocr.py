# -*- coding: utf-8 -*-
"""OCR 測試。

沒裝 Tesseract 就整批跳過——**跳過不等於通過**，這些項目要在 CI（L3）才算真正驗過。
"""
import io
import os

import fitz
import pytest
from PIL import Image

from conftest import SAMPLES, call
from src import ocr
from src.config import MatchOptions
from src.handlers import docx_file, pdf_file
from src.replacer import build_pattern

pytestmark = pytest.mark.skipif(not ocr.is_available(), reason="未安裝 Tesseract")

IMAGE = os.path.join(SAMPLES, "ocr_page.png")
SCANNED_TEXT = os.path.join(SAMPLES, "scanned_text.pdf")
DOCX_WITH_IMAGE = os.path.join(SAMPLES, "with_image.docx")


def _chinese_available():
    return "chi_tra" in ocr.resolve_langs()


def test_replaces_english_word_in_image():
    pattern = build_pattern(["Secret"], MatchOptions())
    with Image.open(IMAGE) as image:
        new_image, count = ocr.replace_in_image(image, pattern)
    assert count == 1
    assert new_image.size == Image.open(IMAGE).size      # 尺寸不得改變


def test_replaced_area_no_longer_reads_as_keyword():
    pattern = build_pattern(["Secret"], MatchOptions())
    with Image.open(IMAGE) as image:
        new_image, _ = ocr.replace_in_image(image, pattern)
    import pytesseract
    text = pytesseract.image_to_string(new_image, lang=ocr.resolve_langs())
    assert "Secret" not in text
    assert "Project" in text                              # 旁邊的字不能被波及


@pytest.mark.skipif(not _chinese_available(), reason="未安裝 chi_tra 語言包")
def test_replaces_chinese_in_image():
    pattern = build_pattern(["機密"], MatchOptions())
    with Image.open(IMAGE) as image:
        _, count = ocr.replace_in_image(image, pattern)
    assert count == 1


def test_low_confidence_is_skipped_not_guessed(monkeypatch):
    """信心度不足時寧可不改，也不能改錯（§3.4）。"""
    pattern = build_pattern(["Secret"], MatchOptions())
    monkeypatch.setattr(ocr, "OCR_MIN_CONFIDENCE", 100)
    with Image.open(IMAGE) as image:
        with pytest.raises(ocr.LowConfidenceError):
            ocr.replace_in_image(image, pattern, min_confidence=100)


def test_low_confidence_only_skips_that_image(tmp_path, monkeypatch):
    """整個檔案不該被一張看不清的圖拖垮：該圖跳過，其餘照常，警告寫進報表。"""
    original = ocr.replace_in_image

    def picky(image, pattern, langs=None, min_confidence=100):
        return original(image, pattern, langs, 100)

    monkeypatch.setattr(ocr, "replace_in_image", picky)
    count, message = call(docx_file, DOCX_WITH_IMAGE, str(tmp_path / "out.docx"),
                          ["Secret"], MatchOptions())
    assert count == 0
    assert "LOW_CONFIDENCE" in message


def test_scanned_pdf_is_processed_via_ocr(tmp_path):
    import pytesseract

    dst = str(tmp_path / "out.pdf")
    count, _ = call(pdf_file, SCANNED_TEXT, dst, ["Secret"], MatchOptions())
    assert count == 1

    doc = fitz.open(dst)
    assert doc.page_count == 1

    rendered = doc[0].get_pixmap(dpi=150)
    image = Image.frombytes("RGB", (rendered.width, rendered.height), rendered.samples)
    text = pytesseract.image_to_string(image, lang=ocr.resolve_langs())
    assert "Secret" not in text
    assert "snoopy" in text.lower()

    # 沒有整頁重新點陣化：圖片尺寸與原檔一致
    original_sizes = sorted((i[2], i[3]) for i in fitz.open(SCANNED_TEXT)[0].get_images())
    assert sorted((i[2], i[3]) for i in doc[0].get_images()) [:1] == original_sizes


def test_no_original_image_left_behind(tmp_path):
    """關鍵：舊圖的位元組不得殘留在檔案裡，否則原始內容還原得回來。"""
    import pytesseract

    dst = str(tmp_path / "out.pdf")
    call(pdf_file, SCANNED_TEXT, dst, ["Secret"], MatchOptions())
    doc = fitz.open(dst)
    for info in doc[0].get_images(full=True):
        base = doc.extract_image(info[0])
        with Image.open(io.BytesIO(base["image"])) as embedded:
            found = pytesseract.image_to_string(embedded, lang=ocr.resolve_langs())
        assert "Secret" not in found


def test_docx_embedded_image_is_processed(tmp_path):
    dst = str(tmp_path / "out.docx")
    count, _ = call(docx_file, DOCX_WITH_IMAGE, dst, ["Secret"], MatchOptions())
    assert count == 1


def test_source_untouched(tmp_path):
    before = io.open(SCANNED_TEXT, "rb").read()
    call(pdf_file, SCANNED_TEXT, str(tmp_path / "out.pdf"), ["Secret"], MatchOptions())
    assert io.open(SCANNED_TEXT, "rb").read() == before
