# -*- coding: utf-8 -*-
"""進入點：預設開 GUI，帶參數時走 CLI（CI 無桌面環境時使用）。

    python src/main.py                                   # GUI
    python src/main.py --src A --out B --keyword 機密     # CLI
"""
from __future__ import annotations

import argparse
import os
import sys
import threading

# 讓 `python src/main.py` 與 PyInstaller 打包後都找得到 src 套件
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.config import (  # noqa: E402
    OCR_MIN_CONFIDENCE, OUTPUT_DIR_NAME, REPLACEMENT, MatchOptions,
)
from src.dispatcher import supported_extensions  # noqa: E402
from src.runner import run  # noqa: E402


def _force_utf8_stdio() -> None:
    """Windows console 預設是 cp950/cp1252，印中文會炸 UnicodeEncodeError。

    處理本身早就完成、報表也寫好了，卻因為印一行摘要而讓整支程式以 exit 1 收場——
    在 CI 或批次腳本裡這會被誤判成整批失敗。
    """
    # --windowed 打包的 exe 沒有 console，sys.stdout 會是 None，print() 直接爆炸。
    # 使用者若用 CLI 參數執行發佈版，不能因為印不出字就整支掛掉。
    import io as _io

    if sys.stdout is None:
        sys.stdout = _io.StringIO()
    if sys.stderr is None:
        sys.stderr = _io.StringIO()

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def run_cli(args) -> int:
    _force_utf8_stdio()
    options = MatchOptions(case_sensitive=not args.ignore_case, whole_word=args.whole_word,
                           ocr_images=not args.no_ocr,
                           min_confidence=args.min_confidence)

    def progress(index, total, path):
        print("[%d/%d] %s" % (index, total, path))

    summary = run(args.src, args.out, args.keyword, options, progress)
    print("完成：OK %d / SKIP %d / FAIL %d，共取代 %d 處"
          % (summary.ok, summary.skipped, summary.failed, summary.replaced))
    print("輸出：%s" % summary.output_root)
    print("報表：%s" % summary.report_path)
    return 1 if summary.failed else 0


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("關鍵字取代為 %s" % REPLACEMENT)
    root.geometry("640x520")

    src_var = tk.StringVar()
    out_var = tk.StringVar()
    ignore_case_var = tk.BooleanVar(value=False)
    whole_word_var = tk.BooleanVar(value=False)
    ocr_var = tk.BooleanVar(value=True)
    confidence_var = tk.StringVar(value=str(OCR_MIN_CONFIDENCE))
    status_var = tk.StringVar(value="待命中")

    def pick(var, title):
        path = filedialog.askdirectory(title=title)
        if path:
            var.set(path)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="來源資料夾").grid(row=0, column=0, sticky="w")
    ttk.Entry(frame, textvariable=src_var, width=52).grid(row=0, column=1, padx=6)
    ttk.Button(frame, text="選擇", command=lambda: pick(src_var, "選擇來源資料夾")).grid(row=0, column=2)

    ttk.Label(frame, text="輸出位置").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(frame, textvariable=out_var, width=52).grid(row=1, column=1, padx=6, pady=(6, 0))
    ttk.Button(frame, text="選擇", command=lambda: pick(out_var, "選擇輸出位置")).grid(row=1, column=2, pady=(6, 0))

    ttk.Label(frame, text="關鍵字（一行一個，全部取代為 %s）" % REPLACEMENT).grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(12, 4))
    keyword_box = tk.Text(frame, height=6, width=72)
    keyword_box.grid(row=3, column=0, columnspan=3, sticky="we")

    ttk.Checkbutton(frame, text="忽略大小寫", variable=ignore_case_var).grid(row=4, column=0, sticky="w", pady=6)
    ttk.Checkbutton(frame, text="全字比對（僅對英數字生效）", variable=whole_word_var).grid(
        row=4, column=1, sticky="w", pady=6)
    ttk.Checkbutton(frame, text="影像 OCR", variable=ocr_var).grid(row=4, column=2, sticky="w", pady=6)

    confidence_row = ttk.Frame(frame)
    confidence_row.grid(row=5, column=0, columnspan=3, sticky="w")
    ttk.Label(confidence_row, text="OCR 信心度門檻（0–100，圖片模糊時可調低）").pack(side="left")
    ttk.Spinbox(confidence_row, from_=0, to=100, width=5,
                textvariable=confidence_var).pack(side="left", padx=6)

    progress_bar = ttk.Progressbar(frame, mode="determinate")
    progress_bar.grid(row=6, column=0, columnspan=3, sticky="we", pady=(6, 4))
    ttk.Label(frame, textvariable=status_var).grid(row=7, column=0, columnspan=3, sticky="w")

    log_box = tk.Text(frame, height=12, width=72, state="disabled")
    log_box.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    frame.rowconfigure(8, weight=1)
    frame.columnconfigure(1, weight=1)

    start_button = ttk.Button(frame, text="開始")
    start_button.grid(row=9, column=2, sticky="e", pady=8)

    def append_log(text):
        log_box.configure(state="normal")
        log_box.insert("end", text + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def on_start():
        src = src_var.get().strip()
        out = out_var.get().strip()
        keywords = [k for k in keyword_box.get("1.0", "end").splitlines() if k.strip()]
        if not src or not os.path.isdir(src):
            messagebox.showerror("錯誤", "請選擇有效的來源資料夾")
            return
        if not out:
            messagebox.showerror("錯誤", "請選擇輸出位置")
            return
        if not keywords:
            messagebox.showerror("錯誤", "請至少輸入一個關鍵字")
            return

        start_button.configure(state="disabled")
        try:
            confidence = float(confidence_var.get())
        except ValueError:
            messagebox.showerror("錯誤", "信心度門檻必須是 0–100 的數字")
            return

        options = MatchOptions(case_sensitive=not ignore_case_var.get(),
                               whole_word=whole_word_var.get(),
                               ocr_images=ocr_var.get(),
                               min_confidence=confidence)

        def progress(index, total, path):
            def update():
                progress_bar.configure(maximum=max(total, 1), value=index)
                status_var.set("(%d/%d) %s" % (index, total, os.path.basename(path)))
            root.after(0, update)

        def worker():
            try:
                summary = run(src, out, keywords, options, progress)
            except Exception as exc:  # 任何未預期錯誤都要看得到，不吞例外
                root.after(0, lambda: messagebox.showerror("執行失敗", str(exc)))
                root.after(0, lambda: start_button.configure(state="normal"))
                return

            def done():
                for r in summary.results:
                    append_log("%s  %s  取代 %d  %s"
                               % (r.status, os.path.basename(r.src), r.replaced, r.message))
                status_var.set("完成：OK %d / SKIP %d / FAIL %d，共取代 %d 處"
                               % (summary.ok, summary.skipped, summary.failed, summary.replaced))
                append_log("輸出：%s" % summary.output_root)
                append_log("報表：%s" % summary.report_path)
                start_button.configure(state="normal")
            root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    start_button.configure(command=on_start)
    from src import ocr
    append_log("目前支援：%s" % "、".join(supported_extensions()))
    append_log("影像 OCR：%s" % ("可用" if ocr.is_available() else "不可用（未安裝 Tesseract）"))
    append_log("輸出會建立在所選位置下的 %s，並保留來源子目錄結構。" % OUTPUT_DIR_NAME)
    root.mainloop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把關鍵字取代為 %s 並另存到 %s" % (REPLACEMENT, OUTPUT_DIR_NAME))
    parser.add_argument("--src", help="來源資料夾")
    parser.add_argument("--out", help="輸出位置（其下會建立 %s）" % OUTPUT_DIR_NAME)
    parser.add_argument("--keyword", action="append", default=[], help="關鍵字，可重複指定")
    parser.add_argument("--ignore-case", action="store_true", help="忽略大小寫")
    parser.add_argument("--whole-word", action="store_true", help="全字比對（僅對英數字生效）")
    parser.add_argument("--no-ocr", action="store_true",
                        help="關閉影像 OCR（不檢查圖片與掃描頁的內容）")
    parser.add_argument("--min-confidence", type=float, default=OCR_MIN_CONFIDENCE,
                        help="OCR 信心度門檻（預設 %(default)s）；低於此值不取代，"
                             "圖片模糊或解析度低時可以調低")
    args = parser.parse_args(argv)

    if args.src or args.out or args.keyword:
        if not (args.src and args.out and args.keyword):
            parser.error("CLI 模式需同時提供 --src、--out 與至少一個 --keyword")
        return run_cli(args)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
