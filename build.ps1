# 備援手動建置腳本（Windows 實機 / VM 使用，步驟需與 CI 一致）
$ErrorActionPreference = "Stop"
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest -v
# --paths . ：main.py 用 sys.path 引導 src 套件，PyInstaller 分析階段看不到
pyinstaller --onefile --windowed --paths . --name KeywordReplacer src/main.py
Write-Host "OK -> dist/KeywordReplacer.exe"
