# -*- coding: utf-8 -*-
"""全域常數與比對選項。

R5 規則：取代字串與輸出資料夾名稱只能定義在這裡，禁止散落到其他模組硬編碼。
"""
from __future__ import annotations

from dataclasses import dataclass

# --- 不可散落的核心常數 ---------------------------------------------------
REPLACEMENT = "snoopy"          # 一律取代成這個字串
OUTPUT_DIR_NAME = "snoopy_folder"  # R3：輸出資料夾固定名稱
REPORT_NAME = "_report.csv"
ERROR_LOG_NAME = "_error.log"

# OCR 信心度門檻；低於此值不得盲改（見 CLAUDE.md §3.4）
OCR_MIN_CONFIDENCE = 70

# 處理狀態
STATUS_OK = "OK"
STATUS_SKIP = "SKIP"
STATUS_FAIL = "FAIL"


@dataclass
class MatchOptions:  # noqa: E302
    """關鍵字比對選項（CLAUDE.md §4）。"""

    case_sensitive: bool = True   # 預設區分大小寫
    whole_word: bool = False      # 預設允許子字串命中
    ocr_images: bool = True       # 是否對影像內容做 OCR 取代（需 Tesseract）
    min_confidence: float = OCR_MIN_CONFIDENCE   # OCR 信心度門檻，低於此值不取代
