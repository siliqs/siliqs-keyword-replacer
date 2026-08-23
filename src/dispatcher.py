# -*- coding: utf-8 -*-
"""依副檔名把檔案分派給對應的 handler。

每新增一種格式，就在 handlers/ 新增一個模組並註冊到 _HANDLERS（CLAUDE.md §6）。
handler 介面固定為：
    EXTENSIONS: Tuple[str, ...]
    process(src_path, dst_path, keywords, options) -> int  # 回傳取代次數
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from src.handlers import (
    csv_file, doc_file, docx_file, image_file, pdf_file, txt, xls_file, xlsx_file,
)

_MODULES = (txt, csv_file, docx_file, xlsx_file, pdf_file, doc_file, xls_file, image_file)

_HANDLERS = {}  # type: Dict[str, object]
for _module in _MODULES:
    for _ext in _module.EXTENSIONS:
        _HANDLERS[_ext.lower()] = _module


def supported_extensions():
    return tuple(sorted(_HANDLERS))


def get_handler(path: str) -> Optional[object]:
    """回傳 handler 模組；不支援的格式回傳 None（上層記為 SKIP）。"""
    ext = os.path.splitext(path)[1].lower()
    return _HANDLERS.get(ext)
