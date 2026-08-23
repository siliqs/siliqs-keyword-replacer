# -*- coding: utf-8 -*-
"""影像 OCR 取代核心（掃描 PDF 與文件內嵌圖片共用）。

信心度是這裡的靈魂：OCR 認錯字就塗錯地方，而且塗掉的內容救不回來。
因此任何命中只要信心度低於門檻，一律**整張圖不處理**並回報 LOW_CONFIDENCE，
交給使用者人工複查——寧可不改，也不能改錯（CLAUDE.md §3.4）。
"""
from __future__ import annotations

import os
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

from src.config import OCR_MIN_CONFIDENCE, REPLACEMENT
from src.errors import SkipReason

PREFERRED_LANGS = ("chi_tra", "chi_sim", "eng")
DEFAULT_LANGS = None      # None = 依實際安裝的語言包自動決定

# 補字用字型：Windows / macOS / Linux 常見路徑，找不到就退回 PIL 內建點陣字型
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


class OcrUnavailableError(SkipReason):
    """找不到 Tesseract 執行檔或語言包。"""


class LowConfidenceError(SkipReason):
    """OCR 信心度低於門檻，不得盲目取代。"""


def _pytesseract():
    import pytesseract  # 延後匯入：沒裝 OCR 也要能跑純文字格式
    return pytesseract


def is_available() -> bool:
    try:
        _pytesseract().get_tesseract_version()
        return True
    except Exception:
        return False


def ensure_available() -> None:
    if not is_available():
        raise OcrUnavailableError("找不到 Tesseract，無法處理影像內容；請安裝後重試，或關閉 OCR 選項")


def resolve_langs(langs=None) -> str:
    """指定就用指定的；否則取實際裝到的語言包，chi_tra 缺席時退回 eng。"""
    if langs:
        return langs
    try:
        installed = set(_pytesseract().get_languages(config=""))
    except Exception:
        return "eng"
    picked = [lang for lang in PREFERRED_LANGS if lang in installed]
    return "+".join(picked) if picked else "eng"


def find_font(size: int):
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _words(image: Image.Image, langs: str) -> List[dict]:
    """回傳 [{text, conf, left, top, width, height, line_key}]，只保留有內容的詞。"""
    pytesseract = _pytesseract()
    data = pytesseract.image_to_data(image, lang=langs,
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        text = data["text"][i]
        if not text or not text.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        words.append({
            "text": text,
            "conf": conf,
            "left": data["left"][i], "top": data["top"][i],
            "width": data["width"][i], "height": data["height"][i],
            "line_key": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        })
    return words


def _char_boxes(words: List[dict]):
    """把每個詞按字數等分成字元框，才能定位到詞中間的關鍵字。"""
    boxes = []
    for word in words:
        text = word["text"]
        step = word["width"] / float(len(text)) if text else 0
        for index, char in enumerate(text):
            left = word["left"] + step * index
            boxes.append((char,
                          (int(left), word["top"], int(left + step), word["top"] + word["height"]),
                          word["conf"]))
    return boxes


def _background_color(image: Image.Image, box):
    """取框線外緣一圈的中位數顏色當底色，避免塗白在深色背景上很突兀。"""
    left, top, right, bottom = box
    samples = []
    step = max(1, (right - left) // 12)
    for x in range(left, max(left + 1, right), step):
        for y in (max(0, top - 2), min(image.height - 1, bottom + 1)):
            samples.append(image.getpixel((min(max(x, 0), image.width - 1), y)))
    if not samples:
        return (255, 255, 255)
    channels = list(zip(*samples))
    return tuple(int(sorted(c)[len(c) // 2]) for c in channels[:3])


def _text_color(image: Image.Image, box):
    """取框內最暗的像素當字色。"""
    left, top, right, bottom = box
    region = image.crop((max(0, left), max(0, top),
                         min(image.width, right), min(image.height, bottom)))
    raw = region.convert("RGB").tobytes()      # 不用 getdata()：Pillow 14 會移除
    if not raw:
        return (0, 0, 0)
    darkest = min(range(0, len(raw), 3), key=lambda i: raw[i] + raw[i + 1] + raw[i + 2])
    return (raw[darkest], raw[darkest + 1], raw[darkest + 2])


def replace_in_image_safe(image: Image.Image, pattern, label: str):
    """回傳 (影像, 取代次數, 警告)。信心度不足時只跳過這張圖，不牽連整個檔案（§3.4）。"""
    try:
        new_image, count = replace_in_image(image, pattern)
        return new_image, count, None
    except LowConfidenceError as exc:
        return image, 0, "%s %s" % (label, exc)


def find_hits(image: Image.Image, pattern, langs=DEFAULT_LANGS,
              min_confidence: float = OCR_MIN_CONFIDENCE):
    """OCR 後回傳所有命中的方框 [(left, top, right, bottom)]（影像像素座標）。

    抽出來獨立成函式，是因為 PDF 的「整頁重繪」路徑要的是座標，不是改好的圖。
    """
    ensure_available()
    words = _words(image, resolve_langs(langs))
    if not words:
        return []

    # 依行分組後接成字串比對，關鍵字跨詞也抓得到
    lines = {}
    for word in words:
        lines.setdefault(word["line_key"], []).append(word)

    hits = []
    for line_words in lines.values():
        line_words.sort(key=lambda w: w["left"])
        boxes = _char_boxes(line_words)
        text = "".join(b[0] for b in boxes)
        for match in pattern.finditer(text):
            start, end = match.span()
            covered = boxes[start:end]
            if not covered:
                continue
            confidence = min(b[2] for b in covered)
            if confidence < min_confidence:
                raise LowConfidenceError(
                    "LOW_CONFIDENCE：命中 %r 的 OCR 信心度僅 %.0f（門檻 %.0f），未處理此圖"
                    % (match.group(0), confidence, min_confidence))
            hits.append((min(b[1][0] for b in covered), min(b[1][1] for b in covered),
                         max(b[1][2] for b in covered), max(b[1][3] for b in covered)))
    return hits


def background_color(image: Image.Image, box):
    """對外公開：取框線外緣的底色（PDF 整頁重繪路徑要用）。"""
    return _background_color(image, box)


def replace_in_image(image: Image.Image, pattern, langs=DEFAULT_LANGS,
                     min_confidence: float = OCR_MIN_CONFIDENCE) -> Tuple[Image.Image, int]:
    """在影像上取代關鍵字。回傳 (新影像, 取代次數)；沒命中就回傳原影像。"""
    ensure_available()
    rgb = image.convert("RGB")
    hits = find_hits(rgb, pattern, langs, min_confidence)
    if not hits:
        return image, 0

    result = rgb.copy()
    draw = ImageDraw.Draw(result)
    for box in hits:
        left, top, right, bottom = box
        background = _background_color(rgb, box)
        color = _text_color(rgb, box)
        draw.rectangle([left, top, right, bottom], fill=background)

        # 字級以框高為基準，寬度超過原佔位就縮小（只縮不放，同 PDF 規則）
        size = max(8, int((bottom - top) * 0.9))
        font = find_font(size)
        while size > 6:
            width = draw.textlength(REPLACEMENT, font=font)
            if width <= (right - left) or width <= 0:
                break
            size = int(size * 0.9)
            font = find_font(size)
        draw.text((left, top), REPLACEMENT, fill=color, font=font)

    return result, len(hits)
