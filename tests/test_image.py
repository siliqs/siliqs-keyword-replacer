# -*- coding: utf-8 -*-
"""單張影像檔（.png / .jpg …）測試。"""
import io
import os

import pytest
from PIL import Image

from conftest import SAMPLES, call
from src import ocr
from src.config import MatchOptions
from src.handlers import image_file

PNG = os.path.join(SAMPLES, "ocr_page.png")
JPG = os.path.join(SAMPLES, "ocr_page.jpg")

needs_ocr = pytest.mark.skipif(not ocr.is_available(), reason="未安裝 Tesseract")


@needs_ocr
def test_png_stays_png_and_replaces(tmp_path):
    dst = str(tmp_path / "out.png")
    count, message = call(image_file, PNG, dst, ["Secret"], MatchOptions())
    assert count == 1
    assert "重新編碼" in message
    with Image.open(dst) as out, Image.open(PNG) as src:
        assert out.format == "PNG"                     # R2
        assert out.size == src.size                    # 尺寸不得改變


@needs_ocr
def test_jpeg_keeps_format_and_exif(tmp_path):
    dst = str(tmp_path / "out.jpg")
    count, _ = call(image_file, JPG, dst, ["Secret"], MatchOptions())
    assert count == 1
    with Image.open(dst) as out:
        assert out.format == "JPEG"
        assert out.getexif().get(270) == "snoopy test sample"   # EXIF 要留著
        assert out.getexif().get(305) == "make_samples.py"


@needs_ocr
def test_untouched_bytes_when_no_match(tmp_path):
    """沒命中就一個位元組都不動——不重新編碼，才是最徹底的 R5。"""
    dst = str(tmp_path / "out.png")
    count, _ = call(image_file, PNG, dst, ["不存在的詞"], MatchOptions())
    assert count == 0
    assert io.open(dst, "rb").read() == io.open(PNG, "rb").read()


@needs_ocr
def test_replaced_image_no_longer_reads_as_keyword(tmp_path):
    import pytesseract

    dst = str(tmp_path / "out.png")
    call(image_file, PNG, dst, ["Secret"], MatchOptions())
    with Image.open(dst) as out:
        text = pytesseract.image_to_string(out, lang=ocr.resolve_langs())
    assert "Secret" not in text
    assert "Project" in text                            # 旁邊的字沒被波及


@needs_ocr
def test_source_untouched(tmp_path):
    before = io.open(PNG, "rb").read()
    call(image_file, PNG, str(tmp_path / "out.png"), ["Secret"], MatchOptions())
    assert io.open(PNG, "rb").read() == before          # R1


def test_skips_when_ocr_disabled(tmp_path):
    """影像的內容全靠 OCR，關掉就無事可做——不得輸出一份沒改的檔。"""
    with pytest.raises(image_file.OcrDisabledError):
        image_file.process(PNG, str(tmp_path / "out.png"), ["Secret"],
                           MatchOptions(ocr_images=False))
    assert not os.path.exists(str(tmp_path / "out.png"))


def test_skips_when_ocr_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "is_available", lambda: False)
    with pytest.raises(ocr.OcrUnavailableError):
        image_file.process(PNG, str(tmp_path / "out.png"), ["Secret"], MatchOptions())


@needs_ocr
def test_low_confidence_skips_whole_file(tmp_path, monkeypatch):
    """單張圖只要信心度不足就整檔 SKIP：這時候「跳過該圖」等於什麼都沒做。"""
    original = ocr.replace_in_image
    monkeypatch.setattr(ocr, "replace_in_image",
                        lambda image, pattern, langs=None, min_confidence=100:
                        original(image, pattern, langs, 100))
    with pytest.raises(ocr.LowConfidenceError):
        image_file.process(PNG, str(tmp_path / "out.png"), ["Secret"], MatchOptions())
