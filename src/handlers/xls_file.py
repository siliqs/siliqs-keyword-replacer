# -*- coding: utf-8 -*-
"""舊版 .xls handler：LibreOffice 轉 xlsx → 沿用 xlsx handler 取代 → 轉回 .xls。

R2：進來是 .xls，出去也一定是 .xls。
"""
from __future__ import annotations

from typing import Iterable

import openpyxl

from src import legacy_office
from src.config import MatchOptions
from src.handlers import xlsx_file

EXTENSIONS = (".xls",)


def _fingerprint(xlsx_path: str):
    """內容量指紋：工作表名稱與每張表的非空儲存格數。"""
    workbook = openpyxl.load_workbook(xlsx_path, data_only=False)
    return tuple(
        (sheet.title, sum(1 for row in sheet.iter_rows() for cell in row if cell.value is not None))
        for sheet in workbook.worksheets
    )


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions):
    keywords = list(keywords)

    def replace(modern_in, modern_out):
        outcome = xlsx_file.process(modern_in, modern_out, keywords, options)
        return outcome if isinstance(outcome, tuple) else (outcome, "")

    count, message = legacy_office.round_trip(
        src_path, "xlsx", "xls", dst_path, replace, _fingerprint)
    notes = [n for n in (message, "經 LibreOffice 轉檔，複雜排版可能有差異") if n]
    return count, "；".join(notes)
