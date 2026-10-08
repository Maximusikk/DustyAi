@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name DustyAi ^
  --icon "assets\dustyai.ico" ^
  --add-data "templates;templates" app.py
echo Done: dist\DustyAi.exe
pause
