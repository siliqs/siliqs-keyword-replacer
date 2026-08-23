# -*- coding: utf-8 -*-
import csv
import io
import os
import shutil

from conftest import SAMPLES
from src.config import OUTPUT_DIR_NAME, REPORT_NAME, STATUS_OK, STATUS_SKIP, MatchOptions
from src.runner import run, unique_path


# 只取「不依賴 OCR」的樣本，整批流程的斷言才不會因為有沒有裝 Tesseract 而漂移
DETERMINISTIC = (
    "big5_lf.txt", "utf8_bom.txt", "utf8_crlf.txt", "note.md",
    "semicolon.csv", "sub/nested.csv", "book.xlsx", "split_runs.docx", "text_layer.pdf",
)


def _prepare(tmp_path):
    src = tmp_path / "src"
    for rel in DETERMINISTIC:
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(SAMPLES, rel), str(target))
    return str(src), str(tmp_path / "dest")


def test_run_end_to_end(tmp_path):
    src, out = _prepare(tmp_path)
    summary = run(src, out, ["機密"], MatchOptions())

    root = os.path.join(out, OUTPUT_DIR_NAME)
    assert summary.output_root == root
    # R3：子目錄結構鏡射；R4：檔名不變
    assert os.path.isfile(os.path.join(root, "utf8_crlf.txt"))
    assert os.path.isfile(os.path.join(root, "sub", "nested.csv"))
    # R2：副檔名進出一致（輸出只會有來源既有的副檔名 + 報表）
    produced = sorted(os.path.splitext(f)[1] for f in os.listdir(root)
                      if f != REPORT_NAME and os.path.isfile(os.path.join(root, f)))
    assert produced == [".csv", ".docx", ".pdf", ".txt", ".txt", ".txt", ".xlsx"]
    # 不支援的 .md 記為 SKIP 且不輸出
    assert not os.path.exists(os.path.join(root, "note.md"))
    assert summary.skipped == 1      # note.md 不支援
    assert summary.failed == 0
    assert summary.ok == 8
    # txt 1+2+2、csv 1+1、xlsx 4、docx 4、pdf 3
    assert summary.replaced == 18


def test_report_contents(tmp_path):
    src, out = _prepare(tmp_path)
    summary = run(src, out, ["機密"], MatchOptions())
    with io.open(summary.report_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["來源路徑", "輸出路徑", "狀態", "取代次數", "訊息"]
    assert len(rows) == 1 + len(summary.results)
    statuses = set(r[2] for r in rows[1:])
    assert statuses == set([STATUS_OK, STATUS_SKIP])


def test_no_partial_output_on_failure(tmp_path, monkeypatch):
    src, out = _prepare(tmp_path)
    from src.handlers import txt

    def boom(src_path, dst_path, keywords, options):
        io.open(dst_path, "w", encoding="utf-8").write("半成品")
        raise RuntimeError("模擬失敗")

    monkeypatch.setattr(txt, "process", boom)
    summary = run(src, out, ["機密"], MatchOptions())

    root = summary.output_root
    leftovers = [f for f in os.listdir(root) if f.endswith(".txt") or "part" in f]
    assert leftovers == []                       # R6：不留半成品
    assert summary.failed == 3                   # 三個 .txt 全 FAIL
    assert summary.ok == 5                       # csv/xlsx/docx/pdf 不受影響，整批未中斷
    assert os.path.isfile(os.path.join(root, "_error.log"))


def test_output_inside_source_is_not_rescanned(tmp_path):
    src, _ = _prepare(tmp_path)
    first = run(src, src, ["機密"], MatchOptions())      # 輸出就放在來源底下
    second = run(src, src, ["機密"], MatchOptions())
    assert first.ok == second.ok                        # 第二次沒把上一輪產物當來源


def test_unique_path_only_on_conflict(tmp_path):
    target = str(tmp_path / "a.txt")
    assert unique_path(target) == target                 # R4：不撞名就不改名
    io.open(target, "w").write("x")
    assert unique_path(target).endswith("a (1).txt")


def test_skip_reason_is_not_treated_as_error(tmp_path):
    """檔案沒壞、只是我們處理不了 → SKIP，且不該被寫進 _error.log。"""
    src, out = _prepare(tmp_path)
    summary = run(src, out, ["機密"], MatchOptions())

    unsupported = [r for r in summary.results if r.src.endswith("note.md")][0]
    assert unsupported.status == STATUS_SKIP
    assert unsupported.dst == ""                               # 沒有輸出半成品
    assert not os.path.exists(os.path.join(summary.output_root, "_error.log"))
    assert summary.failed == 0


def test_scanned_pdf_without_ocr_is_skipped_with_reason(tmp_path, monkeypatch):
    """沒有文字層又沒有 OCR：整份無從處理，必須 SKIP 並寫明原因。"""
    from src import ocr

    monkeypatch.setattr(ocr, "is_available", lambda: False)
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(os.path.join(SAMPLES, "scanned_text.pdf"), str(src / "scanned_text.pdf"))

    summary = run(str(src), str(tmp_path / "dest"), ["機密"], MatchOptions())
    result = summary.results[0]
    assert result.status == STATUS_SKIP
    assert "Tesseract" in result.message
    assert summary.failed == 0
    assert not os.path.exists(os.path.join(summary.output_root, "scanned_text.pdf"))
