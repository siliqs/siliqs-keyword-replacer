# -*- coding: utf-8 -*-
"""CSV handler。

刻意採「位元組保真的純文字取代」而非 csv 模組 round-trip：
csv 模組重寫會改動原本的引號風格與跳脫方式，等於動到關鍵字以外的內容（違反 R5）。

代價是關鍵字若含分隔符／引號／換行，純文字取代可能跨欄位而破壞結構，
因此這裡先做結構安全檢查，命中就丟 UnsafeKeywordError 讓上層記為 SKIP。
"""
from __future__ import annotations

import csv
from typing import Iterable

from src.config import MatchOptions
from src.errors import SkipReason
from src.handlers.txt import read_text, write_text
from src.replacer import normalize_keywords, replace_text

EXTENSIONS = (".csv",)

_SAMPLE_BYTES = 8192


class UnsafeKeywordError(SkipReason):
    """關鍵字含結構字元，純文字取代會破壞 CSV 結構。"""


def sniff_dialect(text: str):
    """猜分隔符；猜不出來就回傳標準 excel dialect（逗號）。"""
    try:
        return csv.Sniffer().sniff(text[:_SAMPLE_BYTES], delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def check_keywords_safe(keywords: Iterable[str], dialect) -> None:
    unsafe = set([dialect.delimiter, dialect.quotechar, "\r", "\n"])
    for kw in normalize_keywords(keywords):
        hit = [ch for ch in unsafe if ch in kw]
        if hit:
            raise UnsafeKeywordError(
                "關鍵字 %r 含 CSV 結構字元 %r，純文字取代會破壞欄位結構" % (kw, hit)
            )


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions) -> int:
    text, codec, bom = read_text(src_path)
    check_keywords_safe(keywords, sniff_dialect(text))
    new_text, count = replace_text(text, keywords, options)
    write_text(dst_path, new_text, codec, bom)
    return count
