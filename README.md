# siliqs-keyword-replacer

把資料夾裡文件中的**關鍵字**全部換成 `snoopy`，並以**原本的檔案格式**另存到 `snoopy_folder`。
原始檔案永遠不會被修改。

*A Windows desktop tool that replaces a keyword with `snoopy` across a folder of documents,
writing each result back in its original file format. Sources are never modified.*

## 下載

到 [Releases](../../releases) 取得 `KeywordReplacer.exe`——單一執行檔，免安裝，需要 Windows 10 / 11（64 位元）。

## 支援格式

| 類型 | 副檔名 | 說明 |
|---|---|---|
| 純文字 | `.txt`、`.csv` | 保留原編碼（UTF-8 / BIG5…）、BOM 與換行符 |
| Word | `.docx`、`.doc` | 關鍵字被切成多個 run 也抓得到；`.doc` 走 LibreOffice 轉檔 |
| Excel | `.xlsx`、`.xls` | 只改字串儲存格；公式只換雙引號內的字串常數 |
| PDF | `.pdf` | 三級自動升級：文字層 → 內嵌圖片 OCR → 整頁 OCR |
| 影像 | `.png`、`.jpg`、`.bmp`、`.tif` | OCR 定位後塗底色疊字 |

## 設計原則

1. **原始檔永不修改** — 來源一律唯讀開啟。
2. **副檔名進出一致** — `.doc` 出來還是 `.doc`，不做「順手升級」。
3. **輸出到 `snoopy_folder`** — 完整保留來源的子目錄結構，檔名不變。
4. **只動關鍵字** — 字型、字級、顏色、欄寬、公式、圖片、頁首頁尾都不變。
5. **失敗不留半成品** — 單一檔案失敗不中斷整批，也不會留下半個檔。
6. **做不到就不輸出** — 處理不了的檔案記 SKIP 並寫明原因，不會給你一份沒改到的檔。
7. **全程離線** — 文件內容不會離開你的電腦。

### PDF 換不掉時

有些 PDF（銀行月結單特別常見）畫面上看得到字，程式卻抽不出正確字碼——嵌入字型缺 `ToUnicode`，
或整段文字根本是向量外框。工具會自動偵測並升級到**整頁 OCR**，不需要你做任何事。

真的還是換不掉時，報表會寫明試過哪幾級。想知道細節可以跑：

```bash
python tools/diagnose_pdf.py <檔案.pdf> <關鍵字>
```

它會報告加密狀態、字型有無 `ToUnicode`、造字區字元數、頁面畫了幾個字形對比抽得出幾個字元，
以及關鍵字在四種寫法（原樣 / NFKC / NFC / 去空白）下有沒有命中。
**這支工具不會印出文件內容**，只印統計與判定。

## 執行結果

每次執行會在 `snoopy_folder` 產生 `_report.csv`：

```
來源路徑, 輸出路徑, 狀態(OK/SKIP/FAIL), 取代次數, 訊息
```

處理成功但有事情沒做到（例如某張圖信心度不足被跳過）也會寫在訊息欄，不會讓你以為全做完了。

## 外部相依

| 功能 | 需要 |
|---|---|
| OCR（掃描 PDF、內嵌圖片、單張影像） | [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)，繁中需 `chi_tra` 語言包 |
| 舊版 `.doc` / `.xls` | [LibreOffice](https://www.libreoffice.org/) |

兩者缺席時其餘格式照常處理，報表會標明哪些檔案未經檢查。

## 開發

```bash
pip install -r requirements.txt
pytest -q                                    # 69 項測試
python src/main.py                           # GUI
python src/main.py --src A --out B --keyword 機密   # CLI
```

`.exe` 一律由 GitHub Actions 產出（`.github/workflows/build-windows.yml`），
發版則由 tag `v*` 觸發 `release.yml`。

## 授權

[GPL-3.0](LICENSE)
