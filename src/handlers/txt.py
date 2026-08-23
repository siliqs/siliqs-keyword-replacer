# -*- coding: utf-8 -*-
"""純文字 handler：保留原編碼、原 BOM、原換行符 (CRLF/LF)。

作法是「讀 bytes → 解碼 → 只換關鍵字 → 用同一組 codec 編回」，
換行符與其他所有位元組都不會被動到（R5）。
"""
from __future__ import annotations

import codecs
from typing import Iterable, Tuple

from src.config import MatchOptions
from src.replacer import replace_text

EXTENSIONS = (".txt",)

# (BOM bytes, codec)；有 BOM 者優先，順序不可調換（UTF-32 的 BOM 前綴含 UTF-16 LE BOM）
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# 無 BOM 時的猜測順序（台灣常見）
_FALLBACK_CODECS = ("utf-8", "cp950", "big5", "cp1252")


def detect_encoding(raw: bytes) -> Tuple[str, bytes]:
    """回傳 (codec, 需保留的 BOM bytes)。

    codec 為 'utf-8-sig' 時 BOM 由 codec 自己處理，故 bom 回傳 b''。
    """
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            if codec == "utf-8-sig":
                return codec, b""
            return codec, bom

    try:
        import chardet  # 選配相依；沒裝就退回猜測清單
    except ImportError:
        chardet = None

    if chardet is not None:
        guess = chardet.detect(raw) or {}
        codec = guess.get("encoding")
        confidence = guess.get("confidence") or 0
        if codec and confidence >= 0.7:
            try:
                raw.decode(codec)
                return codec, b""
            except (UnicodeDecodeError, LookupError):
                pass

    for codec in _FALLBACK_CODECS:
        try:
            raw.decode(codec)
            return codec, b""
        except UnicodeDecodeError:
            continue

    raise ValueError("無法判定文字編碼")


def read_text(src_path: str) -> Tuple[str, str, bytes]:
    with open(src_path, "rb") as fh:      # R1：來源一律唯讀
        raw = fh.read()
    codec, bom = detect_encoding(raw)
    body = raw[len(bom):] if bom else raw
    return body.decode(codec), codec, bom


def write_text(dst_path: str, text: str, codec: str, bom: bytes) -> None:
    with open(dst_path, "wb") as fh:
        if bom:
            fh.write(bom)
        fh.write(text.encode(codec))


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions) -> int:
    text, codec, bom = read_text(src_path)
    new_text, count = replace_text(text, keywords, options)
    write_text(dst_path, new_text, codec, bom)
    return count
