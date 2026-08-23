# -*- coding: utf-8 -*-
"""舊版 Office 格式（.doc / .xls）的共用轉檔層。

策略（CLAUDE.md §10.3 決議 A）：LibreOffice headless 為主。
    原檔 → 現代格式（暫存）→ 既有 handler 取代 → 轉回原格式 → 驗證

三條硬規則：
1. 中間檔一律寫在暫存目錄，**絕不落到 snoopy_folder**（R2）。
2. 轉回原格式後要再轉一次回現代格式做驗證，內容量對不上就丟例外不輸出（R6）。
3. 找不到 soffice 就給明確訊息，**禁止靜默改存成新格式**。
"""
from __future__ import annotations

import atexit
import os
import pathlib
import shutil
import subprocess
import tempfile

from src.errors import SkipReason

_SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
)

# 正常一次轉檔 5–20 秒；設 90 秒是為了讓「卡住」這件事快點現形，而不是等三分鐘
CONVERT_TIMEOUT = int(os.environ.get("SNOOPY_SOFFICE_TIMEOUT", "90"))

_PROFILE_DIR = None       # 每個行程共用一份 user profile：每次都新建會慢上數倍


class SofficeUnavailableError(SkipReason):
    """找不到 LibreOffice。"""


class ConversionError(Exception):
    """轉檔失敗——這是真的錯誤，記 FAIL。"""


class FidelityError(Exception):
    """轉回舊格式後內容量對不上，不得輸出（R6）。"""


def _profile_dir() -> str:
    """LibreOffice 的 user profile。

    同一份 profile 不能被兩個 soffice 同時使用，但本程式的轉檔都是循序的，
    因此每個行程建一份重複用就好——每次轉檔都新建 profile 會慢上數倍。
    """
    global _PROFILE_DIR
    if _PROFILE_DIR is None:
        _PROFILE_DIR = tempfile.mkdtemp(prefix="soffice-profile-")
        atexit.register(shutil.rmtree, _PROFILE_DIR, True)
    return _PROFILE_DIR


def find_soffice():
    """找 soffice。

    Windows 上優先用 `soffice.com`：`soffice.exe` 是 GUI launcher，
    丟出子行程後可能不等它結束，導致呼叫端行為不可預期。
    """
    for path in _SOFFICE_CANDIDATES:
        if os.path.exists(path):
            return path
    for name in ("soffice.com", "soffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def is_available() -> bool:
    return find_soffice() is not None


def ensure_available() -> None:
    if not is_available():
        raise SofficeUnavailableError(
            "找不到 LibreOffice（soffice），無法處理 .doc / .xls；請安裝後重試")


def convert(src_path: str, target_ext: str, out_dir: str) -> str:
    """把 src_path 轉成 target_ext（不含點）放進 out_dir，回傳產出路徑。"""
    soffice = find_soffice()
    if soffice is None:
        raise SofficeUnavailableError("找不到 LibreOffice（soffice）")

    command = [
        soffice,
        # 必須是合法的 file URI。Windows 路徑直接接在 file:// 後面
        # （會變成 file://C:\...）LibreOffice 解析不了，實測會整個卡住到逾時。
        "-env:UserInstallation=%s" % pathlib.Path(_profile_dir()).as_uri(),
        "--headless", "--norestore", "--invisible",
        "--convert-to", target_ext,
        "--outdir", out_dir,
        src_path,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=CONVERT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ConversionError("LibreOffice 轉檔逾時（%d 秒）：%s" % (CONVERT_TIMEOUT, src_path))

    produced = os.path.join(
        out_dir, os.path.splitext(os.path.basename(src_path))[0] + "." + target_ext)
    if not os.path.exists(produced):
        raise ConversionError(
            "LibreOffice 轉檔失敗（%s → %s）：%s"
            % (os.path.splitext(src_path)[1], target_ext,
               (completed.stderr or completed.stdout).decode("utf-8", "replace").strip()[:200]))
    return produced


def round_trip(src_path: str, modern_ext: str, legacy_ext: str, dst_path: str,
               replace_fn, verify_fn):
    """舊格式 → 現代格式 → 取代 → 轉回舊格式 → 驗證。

    replace_fn(modern_path, modern_out) -> (取代次數, 警告)
    verify_fn(modern_path) -> 可比較的內容量指紋（例如工作表名稱清單）
    """
    ensure_available()
    with tempfile.TemporaryDirectory(prefix="legacy-office-") as workdir:
        modern = convert(src_path, modern_ext, workdir)

        replaced_modern = os.path.join(workdir, "replaced." + modern_ext)
        count, message = replace_fn(modern, replaced_modern)

        legacy = convert(replaced_modern, legacy_ext, workdir)

        # 驗證：把產出的舊格式再轉回現代格式，內容量必須一致
        verify_dir = os.path.join(workdir, "verify")
        os.makedirs(verify_dir, exist_ok=True)
        expected = verify_fn(replaced_modern)
        actual = verify_fn(convert(legacy, modern_ext, verify_dir))
        if expected != actual:
            raise FidelityError(
                "轉回 %s 後內容量對不上（預期 %r，實得 %r），未輸出" % (legacy_ext, expected, actual))

        shutil.copyfile(legacy, dst_path)
    return count, message
