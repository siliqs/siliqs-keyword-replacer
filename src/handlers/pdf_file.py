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
_CAP_HEIGHT_RATIO = 0.72         # Helvetica 的 cap height 約為字級的 0.72
_RENDER_DPI = 200                # 整頁彩現 OCR 的解析度：夠 OCR 認字，又不會讓檔案暴增
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


def _text_looks_unreadable(page) -> bool:
    """頁面畫了一堆字形，卻抽不出對應數量的字元 → 有字讀不到。

    典型成因：嵌入字型缺 ToUnicode 對照表，或字碼落在造字區。
    這種頁面「抽得到一點文字」，所以 `_has_text()` 會回 True，
    但關鍵字永遠比對不到——必須靠整頁彩現 OCR 才救得回來。
    """
    text = page.get_text("text")
    glyphs = sum(len(span["chars"]) for block in page.get_text("rawdict")["blocks"]
                 if block.get("type") == 0
                 for line in block["lines"] for span in line["spans"])
    if glyphs <= 20:
        return False
    readable = sum(1 for ch in text if not ch.isspace() and ch != "\ufffd"
                   and not (0xE000 <= ord(ch) <= 0xF8FF))
    return readable < glyphs * 0.5


def _replace_by_page_render(page, pattern, warnings, dpi=_RENDER_DPI) -> int:
    """最後手段：整頁彩現後 OCR，命中處換算回 PDF 座標塗底色補字。

    這一級不管頁面內部是文字、圖片還是向量外框——畫得出來就抓得到。
    """
    scale = 72.0 / dpi
    pixmap = page.get_pixmap(dpi=dpi)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    try:
        boxes = ocr.find_hits(image, pattern)
    except ocr.LowConfidenceError as exc:
        warnings.append("第%d頁整頁 OCR：%s" % (page.number + 1, exc))
        return 0
    if not boxes:
        return 0

    plans = []
    for box in boxes:
        rect = fitz.Rect(box[0] * scale, box[1] * scale, box[2] * scale, box[3] * scale)
        background = tuple(c / 255.0 for c in ocr.background_color(image, box))
        plans.append((rect, background))

    for rect, background in plans:
        page.add_redact_annot(rect, fill=background)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    for rect, background in plans:
        # redaction 不會清掉圖片像素，所以自己補一塊底色確保原字看不見
        page.draw_rect(rect, color=background, fill=background, width=0)
        # OCR 框高量到的是字身高度（cap height），約為字級的 0.72 倍；
        # 直接拿框高當字級會明顯比周圍的字小，所以先還原成字級再交給寬度限制。
        size = _fit_fontsize(rect.height / _CAP_HEIGHT_RATIO, rect.width)
        page.insert_text((rect.x0, rect.y1 - rect.height * 0.1), REPLACEMENT,
                         fontname=_FALLBACK_FONT, fontsize=size, color=(0, 0, 0))
    return len(plans)


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
    """回傳 (取代次數, 警告訊息)。處理不了時丟 SkipReason。"""
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return 0, ""

    document = fitz.open(src_path)          # R1：來源只讀，改動只存在記憶體
    try:
        want_ocr = getattr(options, "ocr_images", True)
        ocr_ready = want_ocr and ocr.is_available()
        unreadable = [p.number + 1 for p in document if _text_looks_unreadable(p)]

        if not _has_text(document) or unreadable:
            # 內容讀不出來，又不能 OCR → 什麼都做不到，記 SKIP 而不是輸出一份沒改的檔
            if not want_ocr:
                raise NeedsOcrError(
                    "PDF 的文字讀不出來（無文字層或字型缺對照表），但 OCR 選項已關閉")
            ocr.ensure_available()
            ocr_ready = True

        count = 0
        warnings = []
        done_xrefs = set()
        if want_ocr and not ocr_ready:
            warnings.append("影像未經 OCR 檢查（Tesseract 不可用）")
        if unreadable:
            warnings.append("第 %s 頁的文字抽不出來（字型缺對照表或為向量外框），改用整頁 OCR"
                            % "、".join(str(n) for n in unreadable))

        # 第 1 級：文字層
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

            # 第 2 級：內嵌圖片
            if ocr_ready and page.get_images():
                count += _replace_in_images(document, page, pattern, done_xrefs,
                                            warnings, page.number + 1)

        # 第 3 級：整頁彩現 OCR。前兩級毫無收穫才跑，因為它最貴也最粗暴
        if count == 0 and ocr_ready:
            rendered = 0
            for page in document:
                rendered += _replace_by_page_render(page, pattern, warnings)
            if rendered:
                warnings.append("文字層比對不到，改以整頁 OCR 取代（版面為彩現結果）")
            count += rendered

        if count == 0:
            tried = ["文字層"]
            if ocr_ready:
                tried += ["內嵌圖片 OCR", "整頁 OCR"]
            warnings.append("未取代任何內容：已試過 %s，都沒有命中關鍵字" % "、".join(tried))

        document.save(dst_path, garbage=3, deflate=True)
        return count, "；".join(warnings)
    finally:
        document.close()
