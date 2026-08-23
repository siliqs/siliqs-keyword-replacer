# 第三方元件

本專案發佈的 `KeywordReplacer.exe` 內含下列第三方軟體。

## Tesseract OCR

- 授權：Apache License 2.0
- 來源：<https://github.com/tesseract-ocr/tesseract>
- 隨附內容：`tesseract.exe`、相依 DLL，以及 `eng` / `osd` / `chi_tra` 三份語言資料
- 語言資料來源：<https://github.com/tesseract-ocr/tessdata_fast>（Apache License 2.0）
- 授權全文隨附於執行檔內的 `tesseract/LICENSE-Tesseract`

## Python 套件

執行檔以 PyInstaller 打包，內含下列套件及其相依項目：

| 套件 | 授權 |
|---|---|
| PyMuPDF | AGPL-3.0 |
| python-docx | MIT |
| openpyxl | MIT |
| Pillow | MIT-CMU |
| pytesseract | Apache-2.0 |
| chardet | LGPL-2.1 |

> PyMuPDF 為 AGPL-3.0，本專案採 GPL-3.0 並公開原始碼，符合其要求。

## 未隨附

**LibreOffice**（處理舊版 `.doc` / `.xls` 用）體積超過 700 MB，不隨執行檔散布，需使用者自行安裝。
未安裝時其餘格式照常處理，報表會標明哪些檔案未處理。
