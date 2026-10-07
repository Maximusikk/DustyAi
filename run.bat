@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Установка зависимостей...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Не удалось установить Flask. Проверьте, что Python 3.10+ установлен и добавлен в PATH.
    pause
    exit /b 1
)
python app.py
pause
