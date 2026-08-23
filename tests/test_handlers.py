# -*- coding: utf-8 -*-
import io
import os

import pytest

from conftest import SAMPLES
from src.config import MatchOptions
from src.handlers import csv_file, txt


def test_txt_preserves_crlf_and_utf8(tmp_path):
    dst = str(tmp_path / "out.txt")
    count = txt.process(os.path.join(SAMPLES, "utf8_crlf.txt"), dst, ["機密"], MatchOptions())
    raw = io.open(dst, "rb").read()
    assert count == 2
    assert b"\r\n" in raw and b"\n\n" not in raw          # CRLF 原樣保留
    assert raw.decode("utf-8").startswith("客戶資料：snoopy")


def test_txt_preserves_big5_encoding(tmp_path):
    dst = str(tmp_path / "out.txt")
    txt.process(os.path.join(SAMPLES, "big5_lf.txt"), dst, ["機密"], MatchOptions())
    raw = io.open(dst, "rb").read()
    assert b"\r\n" not in raw                              # LF 原樣保留
    assert raw.decode("cp950") == "snoopy文件\n第二行沒有關鍵字\n"


def test_txt_preserves_bom(tmp_path):
    dst = str(tmp_path / "out.txt")
    txt.process(os.path.join(SAMPLES, "utf8_bom.txt"), dst, ["機密"], MatchOptions())
    raw = io.open(dst, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")                 # BOM 原樣保留


def test_source_file_untouched(tmp_path):
    src = os.path.join(SAMPLES, "utf8_crlf.txt")
    before = io.open(src, "rb").read()
    txt.process(src, str(tmp_path / "out.txt"), ["機密"], MatchOptions())
    assert io.open(src, "rb").read() == before             # R1


def test_csv_preserves_quoting_and_delimiter(tmp_path):
    dst = str(tmp_path / "out.csv")
    count = csv_file.process(os.path.join(SAMPLES, "semicolon.csv"), dst, ["機密"], MatchOptions())
    text = io.open(dst, encoding="utf-8", newline="").read()
    assert count == 1
    assert text == '姓名;備註\r\n王小明;"snoopy, 請勿外流"\r\n李小華;一般\r\n'


def test_csv_rejects_structural_keyword(tmp_path):
    with pytest.raises(csv_file.UnsafeKeywordError):
        csv_file.process(os.path.join(SAMPLES, "sub", "nested.csv"),
                         str(tmp_path / "out.csv"), ["a,b"], MatchOptions())
