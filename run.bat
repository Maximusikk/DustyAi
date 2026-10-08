@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing dependencies...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies. Make sure Python 3.10+ is installed and added to PATH.
    pause
    exit /b 1
)
python app.py
if errorlevel 1 pause
