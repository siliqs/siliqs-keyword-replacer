# -*- coding: utf-8 -*-
"""XLSX handler。

規則（CLAUDE.md §3.2）：只改儲存格的「字串值」；公式儲存格不動，
除非關鍵字出現在公式的字串常數（雙引號內）中。樣式、欄寬、合併儲存格由 openpyxl 原樣保留。

openpyxl 重寫活頁簿會遺失圖表、樞紐分析表與 VBA，那等於動到關鍵字以外的內容（違反 R5），
因此偵測到就丟 UnsupportedFeatureError 讓上層記為 SKIP，寧可不處理也不默默降級。
"""
from __future__ import annotations

import io
import re
from typing import Iterable

import openpyxl
from PIL import Image

from src.config import MatchOptions
from src import ocr
from src.errors import SkipReason
from src.replacer import build_pattern

EXTENSIONS = (".xlsx",)

_STRING_LITERAL = re.compile(r'"[^"]*"')


class UnsupportedFeatureError(SkipReason):
    """活頁簿含 openpyxl 無法保真回寫的物件。"""


def _check_lossless(workbook) -> None:
    if getattr(workbook, "vba_archive", None) is not None:
        raise UnsupportedFeatureError("活頁簿含 VBA 巨集，openpyxl 回寫會遺失")
    for sheet in workbook.worksheets:
        if getattr(sheet, "_charts", None):
            raise UnsupportedFeatureError("工作表 %r 含圖表，openpyxl 回寫會遺失" % sheet.title)
        if getattr(sheet, "_pivots", None):
            raise UnsupportedFeatureError("工作表 %r 含樞紐分析表，openpyxl 回寫會遺失" % sheet.title)


def _replace_in_formula(formula: str, pattern):
    """只動雙引號內的字串常數，函式名與儲存格參照一律不碰。回傳 (新公式, 取代次數)。"""
    from src.config import REPLACEMENT
    total = 0

    def _sub(match):
        nonlocal total
        literal = match.group(0)
        inner = literal[1:-1]
        new_inner, hits = pattern.subn(REPLACEMENT, inner)
        total += hits
        return '"%s"' % new_inner

    return _STRING_LITERAL.sub(_sub, formula), total


def _replace_in_images(workbook, pattern, warnings) -> int:
    count = 0
    for sheet in workbook.worksheets:
        for embedded in getattr(sheet, "_images", []) or []:
            data = embedded._data()
            with Image.open(io.BytesIO(data)) as image:
                image_format = image.format or "PNG"
                new_image, hits, warning = ocr.replace_in_image_safe(
                    image, pattern, "工作表 %r 的圖片：" % sheet.title)
                if warning:
                    warnings.append(warning)
                if not hits:
                    continue
                buffer = io.BytesIO()
                new_image.save(buffer, format=image_format)
            payload = buffer.getvalue()
            embedded._data = lambda payload=payload: payload
            count += hits
    return count


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions):
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return 0, ""

    from src.config import REPLACEMENT

    workbook = openpyxl.load_workbook(src_path, data_only=False)  # data_only=False：保住公式
    _check_lossless(workbook)

    count = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if not isinstance(value, str):
                    continue
                if value.startswith("="):
                    new_value, hits = _replace_in_formula(value, pattern)
                else:
                    new_value, hits = pattern.subn(REPLACEMENT, value)
                if hits:
                    cell.value = new_value
                    count += hits

    warnings = []
    has_images = any(getattr(s, "_images", None) for s in workbook.worksheets)
    if getattr(options, "ocr_images", True) and has_images:
        if ocr.is_available():
            count += _replace_in_images(workbook, pattern, warnings)
        else:
            warnings.append("影像未經 OCR 檢查（Tesseract 不可用）")

    workbook.save(dst_path)
    return count, "；".join(warnings)
