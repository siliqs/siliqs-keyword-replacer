# -*- coding: utf-8 -*-
import io
import os

try:
    import pymupdf as fitz          # PyMuPDF 1.24+ 的新名稱
except ImportError:
    import fitz
import pytest

from conftest import SAMPLES, call
from src.config import MatchOptions
from src.handlers import pdf_file

SRC = os.path.join(SAMPLES, "text_layer.pdf")
SCANNED = os.path.join(SAMPLES, "scanned.pdf")


def _process(tmp_path, keywords=("機密",)):
    dst = str(tmp_path / "out.pdf")
    count, _ = call(pdf_file, SRC, dst, keywords, MatchOptions())
    return fitz.open(dst), count


def _chars(page, skip_fonts=()):
    """回傳 [(字元, 左上角座標)]，用來比對版面有沒有被推擠。"""
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if any(f in span["font"] for f in skip_fonts):
                    continue
                for char in span["chars"]:
                    out.append((char["c"], round(char["bbox"][0], 2), round(char["bbox"][1], 2)))
    return out


def test_replaces_text_layer(tmp_path):
    doc, count = _process(tmp_path)
    text = doc[0].get_text("text", sort=True)
    assert count == 3
    assert "機密" not in text
    assert text.count("snoopy") == 3


def test_page_count_and_untouched_page(tmp_path):
    doc, _ = _process(tmp_path)
    assert doc.page_count == 2
    assert doc[1].get_text().strip() == "第二頁沒有關鍵字"


def test_images_preserved(tmp_path):
    doc, _ = _process(tmp_path)
    assert len(doc[0].get_images()) == len(fitz.open(SRC)[0].get_images()) == 1


def test_surrounding_text_not_pushed(tmp_path):
    """R5：只有關鍵字消失，其餘每個字元的座標都必須一模一樣。"""
    before = [c for c in _chars(fitz.open(SRC)[0]) if c[0] not in "機密"]
    doc, _ = _process(tmp_path)
    # 補進去的 snoopy 用 Helvetica，原文全是 CJK 字型，據此排除
    after = _chars(doc[0], skip_fonts=("Helvetica",))
    assert before == after


def test_color_preserved(tmp_path):
    doc, _ = _process(tmp_path)
    reds = [s for b in doc[0].get_text("dict")["blocks"] if b.get("type") == 0
            for line in b["lines"] for s in line["spans"]
            if "snoopy" in s["text"] and s["color"] != 0]
    assert len(reds) == 1                    # 紅字那筆取代後仍是紅字


def test_fontsize_only_shrinks(tmp_path):
    doc, _ = _process(tmp_path)
    sizes = [s["size"] for b in doc[0].get_text("dict")["blocks"] if b.get("type") == 0
             for line in b["lines"] for s in line["spans"] if "snoopy" in s["text"]]
    assert len(sizes) == 3
    assert max(sizes) <= 18.0                # 絕不放大超過原字級
    assert min(sizes) >= 4.0                 # 也不會縮到看不見


def test_scanned_pdf_refused_when_ocr_disabled(tmp_path):
    """沒有文字層又關掉 OCR：什麼都做不到，必須 SKIP 而不是輸出一份沒改的檔。"""
    with pytest.raises(pdf_file.NeedsOcrError):
        pdf_file.process(SCANNED, str(tmp_path / "out.pdf"), ["機密"],
                         MatchOptions(ocr_images=False))


def test_scanned_pdf_needs_ocr_engine(tmp_path, monkeypatch):
    from src import ocr
    monkeypatch.setattr(ocr, "is_available", lambda: False)
    with pytest.raises(ocr.OcrUnavailableError):
        pdf_file.process(SCANNED, str(tmp_path / "out.pdf"), ["機密"], MatchOptions())


def test_no_keyword_no_change(tmp_path):
    doc, count = _process(tmp_path, keywords=("不存在的詞",))
    assert count == 0
    assert "機密" in doc[0].get_text()


def test_source_untouched(tmp_path):
    before = io.open(SRC, "rb").read()
    _process(tmp_path)
    assert io.open(SRC, "rb").read() == before


def test_unreadable_text_layer_falls_back_to_page_ocr(tmp_path, monkeypatch):
    """畫面看得到字、文字層讀不出來（銀行月結單常見）時，要自動升級到整頁 OCR。

    這裡把前兩級打掉來模擬那種檔案：文字層比對不到、也沒有可改的內嵌圖片。
    """
    import pytesseract

    from src import ocr
    if not ocr.is_available():
        pytest.skip("未安裝 Tesseract")

    monkeypatch.setattr(pdf_file, "_collect_matches", lambda page, pattern: [])
    monkeypatch.setattr(pdf_file, "_replace_in_images",
                        lambda document, page, pattern, done, warnings, number: 0)

    dst = str(tmp_path / "out.pdf")
    count, message = pdf_file.process(SRC, dst, ["Secret"], MatchOptions())

    assert count == 1
    assert "整頁 OCR" in message
    doc = fitz.open(dst)
    pixmap = doc[0].get_pixmap(dpi=150)
    from PIL import Image
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    text = pytesseract.image_to_string(image, lang="eng")
    assert "Secret" not in text
    assert "snoopy" in text.lower()


def test_zero_replacement_says_what_was_tried(tmp_path):
    _, message = pdf_file.process(SRC, str(tmp_path / "out.pdf"),
                                  ["絕對不存在的詞"], MatchOptions(ocr_images=False))
    assert "未取代任何內容" in message
    assert "文字層" in message


def test_readable_pdf_not_flagged_as_unreadable():
    document = fitz.open(SRC)
    assert not any(pdf_file._text_looks_unreadable(page) for page in document)
