# -*- coding: utf-8 -*-
"""DOCX handler。

重點：Word 常把一個詞拆成多個 `<w:r>`（例如打字過程、拼字檢查、註解都會切 run），
所以**必須先把整個段落的 `<w:t>` 接起來比對**，再把取代結果寫回原本的 run，
命中的第一個 run 保留其字型樣式，其餘被吃掉的片段清空（R5）。

處理範圍涵蓋本文、表格、文字方塊、頁首頁尾、註腳與註解——凡是 `<w:p>` 都會走到。
"""
from __future__ import annotations

import io
from typing import Iterable, List, Tuple

from docx import Document
from PIL import Image

from src import ocr

from src.config import REPLACEMENT, MatchOptions
from src.replacer import build_pattern

EXTENSIONS = (".docx",)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P = _W + "p"
_T = _W + "t"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# 只在這些 part 內取代；styles.xml、numbering.xml 之類不得碰
_TARGET_CONTENT_TYPES = (
    "wordprocessingml.document.main+xml",
    "wordprocessingml.header+xml",
    "wordprocessingml.footer+xml",
    "wordprocessingml.footnotes+xml",
    "wordprocessingml.endnotes+xml",
    "wordprocessingml.comments+xml",
)


def _target_parts(document):
    for part in document.part.package.iter_parts():
        content_type = getattr(part, "content_type", "") or ""
        if any(ct in content_type for ct in _TARGET_CONTENT_TYPES):
            element = getattr(part, "element", None)
            if element is not None:
                yield element


def _set_text(t_element, text: str) -> None:
    t_element.text = text
    # 前後有空白時必須加 xml:space="preserve"，否則 Word 會把空白吃掉
    if text != text.strip():
        t_element.set(_XML_SPACE, "preserve")


def _replace_in_paragraph(p_element, pattern) -> int:
    t_elements = list(p_element.iter(_T))
    if not t_elements:
        return 0

    texts = [t.text or "" for t in t_elements]
    joined = "".join(texts)
    matches = list(pattern.finditer(joined))
    if not matches:
        return 0

    # 每個 <w:t> 在合併字串中的起訖位置
    spans = []  # type: List[Tuple[int, int]]
    cursor = 0
    for text in texts:
        spans.append((cursor, cursor + len(text)))
        cursor += len(text)

    # 由後往前改，前面的位移才不會被影響
    for match in reversed(matches):
        start, end = match.span()
        touched = [i for i, (s, e) in enumerate(spans) if s < end and e > start]
        if not touched:
            continue
        first, last = touched[0], touched[-1]
        prefix = texts[first][:start - spans[first][0]]
        suffix = texts[last][end - spans[last][0]:]

        texts[first] = prefix + REPLACEMENT       # 取代字沿用第一個 run 的樣式
        for i in touched[1:]:
            texts[i] = ""
        if last != first:
            texts[last] = suffix
        else:
            texts[first] = prefix + REPLACEMENT + suffix

    for t_element, text in zip(t_elements, texts):
        _set_text(t_element, text)
    return len(matches)


def _replace_in_images(document, pattern, warnings, min_confidence=None) -> int:
    """內嵌圖片走 OCR；輸出沿用原圖格式，不把 JPEG 換成 PNG（R2 的精神）。"""
    count = 0
    for part in document.part.package.iter_parts():
        content_type = getattr(part, "content_type", "") or ""
        if not content_type.startswith("image/"):
            continue
        with Image.open(io.BytesIO(part.blob)) as image:
            image_format = image.format or "PNG"
            new_image, hits, warning = ocr.replace_in_image_safe(
                image, pattern, "內嵌圖片 %s：" % part.partname,
                min_confidence or ocr.OCR_MIN_CONFIDENCE)
            if warning:
                warnings.append(warning)
            if not hits:
                continue
            buffer = io.BytesIO()
            new_image.save(buffer, format=image_format)
        part._blob = buffer.getvalue()
        count += hits
    return count


def _has_images(document) -> bool:
    return any((getattr(p, "content_type", "") or "").startswith("image/")
               for p in document.part.package.iter_parts())


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions):
    """回傳 (取代次數, 警告訊息)。"""
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return 0, ""

    document = Document(src_path)          # R1：python-docx 只讀不寫來源
    count = 0
    for root in _target_parts(document):
        for p_element in root.iter(_P):
            count += _replace_in_paragraph(p_element, pattern)

    warnings = []
    if getattr(options, "ocr_images", True):
        if ocr.is_available():
            count += _replace_in_images(
                document, build_pattern(keywords, options, flexible_space=True), warnings,
                getattr(options, "min_confidence", None))
        elif _has_images(document):
            warnings.append("影像未經 OCR 檢查（Tesseract 不可用）")

    document.save(dst_path)
    return count, "；".join(warnings)
