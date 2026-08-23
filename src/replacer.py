# -*- coding: utf-8 -*-
"""共用的關鍵字取代核心：所有 handler 都必須經由這裡取代，行為才會一致。"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple

from src.config import REPLACEMENT, MatchOptions

_ASCII_WORD = re.compile(r"^\w+$", re.ASCII)


def normalize_keywords(keywords: Iterable[str]) -> List[str]:
    """去除空白行與重複，並依長度由長到短排序（避免短詞先吃掉長詞）。"""
    seen = set()
    result = []
    for kw in keywords:
        kw = (kw or "").strip()
        if not kw or kw in seen:
            continue
        seen.add(kw)
        result.append(kw)
    result.sort(key=len, reverse=True)
    return result


def build_pattern(keywords: Iterable[str], options: MatchOptions, flexible_space: bool = False):
    """組出單一 regex；無有效關鍵字時回傳 None。

    全字比對僅對「純 ASCII 詞」加上 \\b 邊界；中文不做斷詞，加了 \\b 反而失效。

    `flexible_space=True` 給 OCR 用：OCR 是逐「詞」回報的，同一行接起來時
    英文詞之間有空格、中文詞之間沒有，且斷詞位置不保證。因此把關鍵字的每個字元
    之間都允許零個以上的空白，`Monthly Statement` 才比對得到 `MonthlyStatement`，
    `機密文件` 也比對得到被拆成兩個詞的 `機密 文件`。
    """
    kws = normalize_keywords(keywords)
    if not kws:
        return None

    parts = []
    for kw in kws:
        if flexible_space:
            escaped = r"\s*".join(re.escape(ch) for ch in kw if not ch.isspace())
        else:
            escaped = re.escape(kw)
        if options.whole_word and _ASCII_WORD.match(kw):
            escaped = r"\b" + escaped + r"\b"
        parts.append(escaped)

    flags = 0 if options.case_sensitive else re.IGNORECASE
    return re.compile("|".join(parts), flags)


def replace_text(text: str, keywords: Iterable[str], options: MatchOptions) -> Tuple[str, int]:
    """回傳 (取代後文字, 取代次數)。沒命中時原字串原樣回傳。"""
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return text, 0
    new_text, count = pattern.subn(REPLACEMENT, text)
    return new_text, count


def count_matches(text: str, keywords: Iterable[str], options: MatchOptions) -> int:
    pattern = build_pattern(keywords, options)
    if pattern is None:
        return 0
    return len(pattern.findall(text))
