# -*- coding: utf-8 -*-
"""批次流程：掃描來源 → 逐檔取代 → 輸出到 snoopy_folder → 產出 _report.csv。

守住的規則：
  R1 來源唯讀、R2 副檔名進出一致、R3 輸出結構鏡射、R4 檔名不變（衝突才加 (n)）、
  R6 失敗不留半成品且不中斷整批。
"""
from __future__ import annotations

import csv
import os
import shutil
import traceback
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from src.config import (
    ERROR_LOG_NAME,
    OUTPUT_DIR_NAME,
    REPORT_NAME,
    STATUS_FAIL,
    STATUS_OK,
    STATUS_SKIP,
    MatchOptions,
)
from src.dispatcher import get_handler
from src.errors import SkipReason

_TMP_SUFFIX = ".snoopy-part"


@dataclass
class FileResult:
    src: str
    dst: str
    status: str
    replaced: int
    message: str


@dataclass
class RunSummary:
    output_root: str
    report_path: str
    results: List[FileResult] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_OK)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_SKIP)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_FAIL)

    @property
    def replaced(self) -> int:
        return sum(r.replaced for r in self.results)


def collect_files(src_root: str, output_root: str) -> List[str]:
    """列出來源檔；輸出資料夾若位於來源之下必須排除，否則會自我遞迴。"""
    src_root = os.path.abspath(src_root)
    output_root = os.path.abspath(output_root)
    found = []
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [
            d for d in sorted(dirnames)
            if os.path.abspath(os.path.join(dirpath, d)) != output_root
        ]
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(_TMP_SUFFIX):
                continue
            found.append(os.path.join(dirpath, name))
    return found


def unique_path(path: str) -> str:
    """R4：檔名維持原樣；只有撞名時才在尾端加 (1)、(2)。"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 1
    while True:
        candidate = "%s (%d)%s" % (stem, index, ext)
        if not os.path.exists(candidate):
            return candidate
        index += 1


def _log_error(output_root: str, src_path: str, exc: BaseException) -> None:
    log_path = os.path.join(output_root, ERROR_LOG_NAME)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write("=== %s ===\n" % src_path)
        fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        fh.write("\n")


def process_one(src_path: str, src_root: str, output_root: str,
                keywords: Iterable[str], options: MatchOptions) -> FileResult:
    handler = get_handler(src_path)
    rel = os.path.relpath(src_path, src_root)
    if handler is None:
        return FileResult(src_path, "", STATUS_SKIP, 0, "不支援的格式，未處理")

    dst_dir = os.path.join(output_root, os.path.dirname(rel))
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
    dst_path = unique_path(os.path.join(output_root, rel))  # R2：副檔名沿用來源
    tmp_path = dst_path + _TMP_SUFFIX

    try:
        outcome = handler.process(src_path, tmp_path, keywords, options)
        # handler 可回傳 int，或 (次數, 警告訊息)
        replaced, message = outcome if isinstance(outcome, tuple) else (outcome, "")
    except Exception as exc:  # R6：失敗清掉暫存，不留半成品，也不中斷整批
        # SkipReason 不寫 _error.log（不是錯誤），其餘一律留完整 traceback
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if not isinstance(exc, SkipReason):
            _log_error(output_root, src_path, exc)
        # 檔案沒壞、只是我們處理不了 → SKIP；其餘才是 FAIL
        status = STATUS_SKIP if isinstance(exc, SkipReason) else STATUS_FAIL
        return FileResult(src_path, "", status, 0, "%s: %s" % (exc.__class__.__name__, exc))

    os.replace(tmp_path, dst_path)
    shutil.copystat(src_path, dst_path)  # 保留原時間戳，來源本身不受影響（R1）
    if replaced == 0 and not message:
        # 「處理完了但一個字都沒換」也要講出來，不能讓使用者以為換好了
        message = "未取代任何內容：檔案中沒有找到關鍵字"
    return FileResult(src_path, dst_path, STATUS_OK, replaced, message)


def write_report(output_root: str, results: List[FileResult]) -> str:
    report_path = os.path.join(output_root, REPORT_NAME)
    # utf-8-sig：Excel 直接開才不會亂碼
    with open(report_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["來源路徑", "輸出路徑", "狀態", "取代次數", "訊息"])
        for r in results:
            writer.writerow([r.src, r.dst, r.status, r.replaced, r.message])
    return report_path


def run(src_root: str, output_parent: str, keywords: Iterable[str],
        options: Optional[MatchOptions] = None,
        progress: Optional[Callable[[int, int, str], None]] = None) -> RunSummary:
    """執行整批取代。output_parent 之下會建立 snoopy_folder（R3）。"""
    options = options or MatchOptions()
    keywords = list(keywords)
    src_root = os.path.abspath(src_root)
    output_root = os.path.join(os.path.abspath(output_parent), OUTPUT_DIR_NAME)
    os.makedirs(output_root, exist_ok=True)

    files = collect_files(src_root, output_root)
    summary = RunSummary(output_root=output_root, report_path="")
    total = len(files)
    for index, src_path in enumerate(files, start=1):
        if progress is not None:
            progress(index, total, src_path)
        summary.results.append(process_one(src_path, src_root, output_root, keywords, options))

    summary.report_path = write_report(output_root, summary.results)
    return summary
