@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0restream_app.py"
    exit /b
)

python restream_app.py
pause
