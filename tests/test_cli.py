# -*- coding: utf-8 -*-
"""CLI 層測試（GUI 是薄殼，商業邏輯的最外層就在這裡）。"""
import os
import shutil
import subprocess
import sys

from conftest import SAMPLES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "src", "main.py")


def _run(tmp_path, env_extra=None, keywords=("Secret",)):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("utf8_crlf.txt", "semicolon.csv"):
        shutil.copy(os.path.join(SAMPLES, name), str(src / name))

    env = dict(os.environ)
    env.update(env_extra or {})
    command = [sys.executable, MAIN, "--src", str(src), "--out", str(tmp_path), "--no-ocr"]
    for keyword in keywords:
        command += ["--keyword", keyword]
    return subprocess.run(command, capture_output=True, env=env)


def test_cli_runs_and_reports(tmp_path):
    result = _run(tmp_path, keywords=("機密",))
    assert result.returncode == 0
    assert os.path.isfile(str(tmp_path / "snoopy_folder" / "_report.csv"))


def test_cli_survives_non_utf8_console(tmp_path):
    """Windows console 是 cp950/cp1252，印中文摘要不得讓整支程式以 exit 1 收場。"""
    result = _run(tmp_path, env_extra={"PYTHONIOENCODING": "cp1252"}, keywords=("機密",))
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert os.path.isfile(str(tmp_path / "snoopy_folder" / "_report.csv"))


def test_cli_requires_all_arguments(tmp_path):
    result = subprocess.run([sys.executable, MAIN, "--src", str(tmp_path)], capture_output=True)
    assert result.returncode != 0
    assert b"--keyword" in result.stderr
