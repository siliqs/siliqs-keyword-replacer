# -*- coding: utf-8 -*-
"""PDF handler（文字層）。

流程：`rawdict` 取出逐字 bbox → 以自家 regex 比對（才能守住區分大小寫／全字比對規則）
→ `add_redact_annot` 遮除原字 → `apply_redactions` 真正刪除 → 原位置補上 snoopy。

版面位移是本格式獨有的問題：「機密」兩個中文字換成 snoopy 六個字母，寬度不同。
作法是**只縮不放、且絕不推擠後面的內容**（R5）：
可用寬度算到「同一行下一個字元的起點」為止，行尾則算到頁面右邊界（留 36pt 邊界）；
snoopy 在原字級下超過可用寬度才等比縮小，永遠不為了填滿而放大。

影像內容（掃描頁、內嵌圖片）走 `src/ocr.py`：**直接改圖片本身**再以 `replace_image` 換回去，
而不是把整頁重新點陣化——頁面其餘的文字與向量內容因此完全不受影響。
關掉 OCR 又遇到抽不到文字的 PDF 時丟 NeedsOcrError 記 SKIP，**不得默默複製一份沒改到的檔案出去**。
"""
from __future__ import annotations

import io
from typing import Iterable, List

import fitz
from PIL import Image

from src import ocr

from src.config import REPLACEMENT, MatchOptions
from src.errors import SkipReason
from src.replacer import build_pattern

EXTENSIONS = (".pdf",)

_FALLBACK_FONT = "helv"          # snoopy 是純 ASCII，base14 字型即可，不需嵌入 CJK
_MIN_FONTSIZE = 4.0
_PAGE_MARGIN = 36.0              # 行尾補字時保留的頁面邊界
_ROTATIONS = {(1.0, 0.0): 0, (0.0, -1.0): 90, (-1.0, 0.0): 180, (0.0, 1.0): 270}


class NeedsOcrError(SkipReason):
    """PDF 抽不到文字，而 OCR 未啟用或不可用。"""


class UnsupportedTextAngleError(SkipReason):
    """文字為非直角旋轉，補字位置無法可靠還原。"""


def _color_tuple(color_int: int):
    return ((color_int >> 16) & 255) / 255.0, ((color_int >> 8) & 255) / 255.0, (color_int & 255) / 255.0


def _collect_matches(page, pattern) -> List[dict]:
    """回傳每個命中的 rect、基準點、字級、顏色與旋轉角。"""
    hits = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:          # 非文字區塊（圖片）不處理
            continue
        for line in block["lines"]:
            chars = []
            for span in line["spans"]:
                for char in span["chars"]:
                    chars.append((char, span))
            if not chars:
                continue

            text = "".join(c["c"] for c, _ in chars)
            for match in pattern.finditer(text):
                start, end = match.span()
                if start == end:
                    continue
                rect = fitz.Rect(chars[start][0]["bbox"])
                for char, _ in chars[start + 1:end]:
                    rect |= fitz.Rect(char["bbox"])

                direction = tuple(round(v, 6) for v in line["dir"])
                if direction not in _ROTATIONS:
                    raise UnsupportedTextAngleError("文字旋轉角 %s 不支援" % (direction,))

                span = chars[start][1]
                rotation = _ROTATIONS[direction]
                hits.append({
                    "rect": rect,
                    "origin": chars[start][0]["origin"],
                    "size": span["size"],
                    "color": _color_tuple(span["color"]),
                    "rotate": rotation,
                    "available": _available_width(page, chars, start, end, rect, rotation),
                })
    return hits


def _available_width(page, chars, start: int, end: int, rect, rotation: int) -> float:
    """可用寬度＝到同一行下一個字元起點為止；行尾則到頁面邊界。"""
    if rotation in (90, 270):
        return rect.height          # 直排／旋轉文字保守處理，只用原佔位
    if rotation == 180:
        return rect.width
    if end < len(chars):
        next_x0 = fitz.Rect(chars[end][0]["bbox"]).x0
        return max(rect.width, next_x0 - rect.x0)
    return max(rect.width, page.rect.x1 - _PAGE_MARGIN - rect.x0)


def _fit_fontsize(size: float, available: float) -> float:
    """只縮不放：算出讓 snoopy 塞得進原佔位的字級。"""
    width = fitz.get_text_length(REPLACEMENT, fontname=_FALLBACK_FONT, fontsize=size)
    if width <= available or width <= 0:
        return size
    return max(_MIN_FONTSIZE, size * available / width)


def _has_text(document) -> bool:
    for page in document:
        if page.get_text("text").strip():
            return True
    return False


def _replace_in_images(document, page, pattern, done, warnings, page_number):
    """OCR 取代頁面上的內嵌圖片；同一個 xref 只處理一次。"""
    count = 0
    for image_info in page.get_images(full=True):
        xref = image_info[0]
        if xref in done:
            continue
        done.add(xref)

        base = document.extract_image(xref)
        if not base or not base.get("image"):
            continue
        with Image.open(io.BytesIO(base["image"])) as image:
            label = "第%d頁圖片：" % page_number
            new_image, hits, warning = ocr.replace_in_image_safe(image, pattern, label)
            if warning:
                warnings.append(warning)
            if not hits:
                continue
            buffer = io.BytesIO()
            new_image.save(buffer, format="PNG")
        page.replace_image(xref, stream=buffer.getvalue())
        count += hits
    return count


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions):
    """回傳 (取代次數, 警告訊息)。"""
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return 0, ""

    document = fitz.open(src_path)          # R1：來源只讀，改動只存在記憶體
    try:
        use_ocr = getattr(options, "ocr_images", True) and ocr.is_available()
        if not _has_text(document):
            # 整份抽不到文字又不能 OCR：什麼都做不到，記 SKIP 而不是輸出一份沒改的檔
            if not getattr(options, "ocr_images", True):
                raise NeedsOcrError("PDF 無文字層（疑似掃描影像），但 OCR 選項已關閉")
            ocr.ensure_available()

        count = 0
        warnings = []
        done_xrefs = set()
        if getattr(options, "ocr_images", True) and not ocr.is_available():
            warnings.append("影像未經 OCR 檢查（Tesseract 不可用）")
        for page in document:
            hits = _collect_matches(page, pattern)
            if hits:
                for hit in hits:
                    page.add_redact_annot(hit["rect"])   # 只刪字，不畫黑框
                # 圖片與線條不得被 redaction 波及（R5）
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                      graphics=fitz.PDF_REDACT_LINE_ART_NONE)

                for hit in hits:
                    page.insert_text(hit["origin"], REPLACEMENT,
                                     fontname=_FALLBACK_FONT,
                                     fontsize=_fit_fontsize(hit["size"], hit["available"]),
                                     color=hit["color"],
                                     rotate=hit["rotate"])
                    count += 1

            if use_ocr and page.get_images():
                count += _replace_in_images(document, page, pattern, done_xrefs,
                                            warnings, page.number + 1)

        document.save(dst_path, garbage=3, deflate=True)
        return count, "；".join(warnings)
    finally:
        document.close()
