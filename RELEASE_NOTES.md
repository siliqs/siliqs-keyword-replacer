把資料夾裡文件中的**關鍵字**全部換成 `snoopy`，並以**原本的檔案格式**另存到 `snoopy_folder`。原始檔案永遠不會被修改。

*Replace a keyword with `snoopy` across a folder of documents, writing each result back in its original file format.*

## 下載

**KeywordReplacer.exe** — 單一執行檔，免安裝。需要 Windows 10 或 11（64 位元）。

> **⚠️ 第一次執行會被 SmartScreen 擋下來**
> 因為這個執行檔沒有購買程式碼簽章憑證。點「其他資訊」→「仍要執行」即可。
> 不放心的話，可以用 `SHA256SUMS.txt` 核對檔案雜湊。

## 支援格式

| 類型 | 副檔名 |
|---|---|
| 純文字 | `.txt`、`.csv`（保留原編碼、BOM 與換行符） |
| Office | `.docx`、`.xlsx`、`.doc`、`.xls` |
| PDF | 文字層、掃描影像、以及「看得到字卻抽不出字」的檔案 |
| 影像 | `.png`、`.jpg`、`.bmp`、`.tif` |

## v0.1.1 的變更

**PDF 改為三級自動升級**：文字層 → 內嵌圖片 OCR → **整頁 OCR**。

有些 PDF（銀行月結單特別常見）畫面上看得到字，程式卻抽不出正確字碼——嵌入字型缺 `ToUnicode`，
或整段文字根本是向量外框。舊版會以為「有文字層」而走錯路徑，結果一個字都沒換。
現在會自動偵測並升級到整頁 OCR，不需要你做任何事。

**沒換到一定會告訴你**：報表訊息會寫明試過哪幾級，不再默默給你一份沒改的檔。

## 設計原則

- **原始檔永不修改**，一律唯讀開啟。
- **副檔名進出一致**：`.doc` 出來還是 `.doc`，不會被順手升級成 `.docx`。
- **只動關鍵字**：字型、字級、顏色、欄寬、公式、圖片、頁首頁尾都不變。
- **做不到就不輸出**：處理不了的檔案記為 SKIP 並寫明原因，不會給你一份沒改到的檔。
- **全程離線**：文件內容不會離開你的電腦。

## 外部相依

- **OCR**（掃描 PDF、文件內嵌圖片、單張影像）需要 [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)，繁體中文需 `chi_tra` 語言包。
- **舊版 `.doc` / `.xls`** 需要 [LibreOffice](https://www.libreoffice.org/)。

兩者缺席時，其餘格式照常處理，報表會標明哪些檔案未經檢查。

## 執行結果

每次執行會在 `snoopy_folder` 產生 `_report.csv`，逐檔列出來源、輸出、狀態（OK / SKIP / FAIL）、取代次數與訊息。
