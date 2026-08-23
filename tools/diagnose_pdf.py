# -*- coding: utf-8 -*-
"""診斷「PDF 裡看得到關鍵字，工具卻換不掉」的原因。

刻意不印出文件內容，只印統計與判定結果——這支工具是拿來看銀行月結單之類的東西的。

    python3 tools/diagnose_pdf.py <檔案.pdf> <關鍵字> [關鍵字...]
"""
from __future__ import annotations

import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

PUA = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def _classify(text):
    counts = {"cjk": 0, "latin": 0, "digit": 0, "pua": 0, "replacement": 0, "other": 0}
    for ch in text:
        code = ord(ch)
        if ch == "�":
            counts["replacement"] += 1
        elif any(lo <= code <= hi for lo, hi in PUA):
            counts["pua"] += 1
        elif "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            counts["cjk"] += 1
        elif ch.isdigit():
            counts["digit"] += 1
        elif ch.isalpha():
            counts["latin"] += 1
        elif not ch.isspace():
            counts["other"] += 1
    return counts


def _variants(keyword):
    """同一個詞的幾種可能長相：全形半形、相容字、去空白。"""
    seen = {}
    seen["原樣"] = keyword
    seen["NFKC"] = unicodedata.normalize("NFKC", keyword)
    seen["NFC"] = unicodedata.normalize("NFC", keyword)
    seen["去空白"] = "".join(keyword.split())
    return seen


def main(path, keywords):
    print("檔案：%s（%.1f KB）" % (os.path.basename(path), os.path.getsize(path) / 1024.0))
    document = fitz.open(path)

    print("加密：%s  需要密碼：%s  頁數：%d"
          % (document.is_encrypted, document.needs_pass, document.page_count))
    if document.needs_pass:
        print("→ 需要開啟密碼，本工具無法處理。")
        return
    if document.is_encrypted:
        print("→ 檔案有加密（權限限制）。PyMuPDF 通常仍可讀，但部分檔案會擋住文字抽取。")

    total_text = []
    font_rows = []
    suspicious = False
    for page in document:
        text = page.get_text("text")
        total_text.append(text)
        drawings = len(page.get_drawings())
        print("\n[第 %d 頁] 可抽取字元 %d 個｜圖片 %d 張｜向量繪圖 %d 筆"
              % (page.number + 1, len(text.strip()), len(page.get_images()), drawings))
        counts = _classify(text)
        print("  字元組成：中日韓 %(cjk)d｜拉丁 %(latin)d｜數字 %(digit)d｜"
              "造字區 %(pua)d｜亂碼 %(replacement)d｜其他 %(other)d" % counts)
        if counts["pua"] or counts["replacement"]:
            suspicious = True
            print("  ⚠ 出現造字區/亂碼字元 → 抽出來的不是真正的文字")

        # 畫面上畫了很多字，卻抽不出對應數量 → 典型的「有字讀不到」
        glyphs = sum(len(span["chars"]) for block in page.get_text("rawdict")["blocks"]
                     if block.get("type") == 0
                     for line in block["lines"] for span in line["spans"])
        if glyphs > 20 and len(text.strip()) < glyphs * 0.5:
            suspicious = True
            print("  ⚠ 頁面畫了 %d 個字形，卻只抽得出 %d 個字元 → 有字讀不到"
                  % (glyphs, len(text.strip())))

        for font in page.get_fonts(full=True):
            xref, ext, ftype, basefont, name = font[0], font[1], font[2], font[3], font[4]
            try:
                definition = document.xref_object(xref, compressed=False)
            except Exception:
                definition = ""
            font_rows.append((page.number + 1, basefont, ftype, ext or "未嵌入",
                              "有" if "/ToUnicode" in definition else "無"))

    if font_rows:
        print("\n字型清單（頁, 字型, 類型, 嵌入, ToUnicode）")
        seen = set()
        for row in font_rows:
            key = row[1:]
            if key in seen:
                continue
            seen.add(key)
            print("  第%d頁  %-28s %-10s 嵌入=%-6s ToUnicode=%s" % row)
        missing = [r for r in font_rows if r[4] == "無"]
        if missing and suspicious:
            print("  ⚠ 這些字型缺 ToUnicode，且頁面出現造字區/亂碼字元"
                  " → 畫面看得到、程式讀不出正確字碼")
        elif missing:
            print("  （部分字型沒有 ToUnicode，但文字仍抽得出來，屬正常）")

    joined = "\n".join(total_text)
    stripped = "".join(joined.split())
    print("\n關鍵字比對")
    for keyword in keywords:
        print("  「%s」" % keyword)
        hit_any = False
        for label, variant in _variants(keyword).items():
            haystack = stripped if label == "去空白" else joined
            found = variant in haystack
            case_found = variant.lower() in haystack.lower()
            if found or case_found:
                hit_any = True
            print("    %-6s：%s%s" % (label, "命中" if found else "沒有",
                                      "（忽略大小寫才命中）" if (not found and case_found) else ""))
        if not hit_any:
            print("    → 文字層裡找不到這個詞。")

    if not stripped:
        print("\n判定：這是**沒有文字層的掃描 PDF**，只能走 OCR。")
    elif any("�" in t or any(any(lo <= ord(c) <= hi for lo, hi in PUA) for c in t)
             for t in total_text):
        print("\n判定：有文字層，但**字碼對不回真正的文字**（缺 ToUnicode）。"
              "\n      這種檔案只能改走 OCR，或用字型內的 CMap 自行建對照表。")
    else:
        print("\n判定：文字層可正常抽取。若關鍵字沒命中，多半是用字差異"
              "（繁簡、異體字、全形半形、中間夾空白或換行）。")

    document.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2:])
