# -*- coding: utf-8 -*-
"""單張影像 handler（.png / .jpg / .bmp / .tif …）。

整張圖就是全部內容，所以規則跟掃描 PDF 一樣：**做不到就不要輸出一份沒改的檔**。
- 沒有 OCR 引擎 → SKIP
- 信心度不足 → SKIP（標記 LOW_CONFIDENCE）
- 沒命中關鍵字 → **原封不動複製位元組**，完全不重新編碼（這是最徹底的 R5）
- 有命中 → 重新編碼，盡量保住 EXIF / ICC / JPEG 品質，並在訊息說明已重新編碼
"""
from __future__ import annotations

import shutil
from typing import Iterable

from PIL import Image

from src import ocr
from src.config import MatchOptions
from src.errors import SkipReason
from src.replacer import build_pattern

EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


class OcrDisabledError(SkipReason):
    """影像檔的全部內容都要靠 OCR，關掉 OCR 就無事可做。"""


def _save_kwargs(image: Image.Image) -> dict:
    """盡量把原檔的附屬資訊帶到新檔：EXIF、ICC、JPEG 品質。"""
    kwargs = {}
    exif = image.info.get("exif")
    if exif:
        kwargs["exif"] = exif
    icc = image.info.get("icc_profile")
    if icc:
        kwargs["icc_profile"] = icc
    if (image.format or "").upper() in ("JPEG", "JPG"):
        # quality="keep" 只能用在「還是原本那個 JPEG 物件」上，我們手上是新畫過的 RGB copy。
        # 改成沿用原檔的量化表與取樣方式，效果一樣是不重新量化。
        quantization = getattr(image, "quantization", None)
        if quantization:
            kwargs["qtables"] = quantization
        else:
            kwargs["quality"] = 95
        try:
            from PIL import JpegImagePlugin

            kwargs["subsampling"] = JpegImagePlugin.get_sampling(image)
        except Exception:
            pass
        if image.info.get("progressive"):
            kwargs["progressive"] = True
    if (image.format or "").upper() in ("TIFF",):
        compression = image.info.get("compression")
        if compression:
            kwargs["compression"] = compression
    return kwargs


def process(src_path: str, dst_path: str, keywords: Iterable[str], options: MatchOptions):
    """回傳 (取代次數, 警告訊息)。"""
    # OCR 逐「詞」回報，比對要容許詞間空白（`Monthly Statement` vs `MonthlyStatement`）
    pattern = build_pattern(keywords, options, flexible_space=True)
    if pattern is None:
        shutil.copyfile(src_path, dst_path)
        return 0, ""

    if not getattr(options, "ocr_images", True):
        raise OcrDisabledError("影像檔的內容全靠 OCR，但 OCR 選項已關閉")
    ocr.ensure_available()

    with Image.open(src_path) as image:      # R1：只讀
        image_format = image.format or "PNG"
        new_image, count = ocr.replace_in_image(
            image, pattern, min_confidence=getattr(options, "min_confidence", None)
            or ocr.OCR_MIN_CONFIDENCE)
        if count == 0:
            shutil.copyfile(src_path, dst_path)   # 沒命中就一個位元組都不動
            return 0, ""
        save_kwargs = _save_kwargs(image)
        new_image.save(dst_path, format=image_format, **save_kwargs)

    return count, "影像已重新編碼（原格式 %s）" % image_format
