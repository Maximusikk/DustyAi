@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onedir --windowed --name DustyAi ^
  --icon "assets\dustyai.ico" ^
  --version-file "packaging\version.txt" ^
  --add-data "templates;templates" app.py
echo Done: dist\DustyAi\DustyAi.exe
pause
