@echo off
setlocal
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "ROOT_DIR=%~dp0.."
set "PY_CMD="

where python.exe >nul 2>nul
if %errorlevel%==0 set "PY_CMD=python.exe"

if not defined PY_CMD (
    where py.exe >nul 2>nul
    if %errorlevel%==0 set "PY_CMD=py.exe"
)

if not defined PY_CMD (
    echo Python was not found.
    echo Install Python for Windows, then run this launcher again.
    echo Make sure pip is installed.
    pause
    exit /b 1
)

%PY_CMD% -c "import PIL, obsws_python, streamlink" >nul 2>nul
if not %errorlevel%==0 (
    echo Required Python packages are missing.
    echo Installing packages from "%ROOT_DIR%\requirements.txt"...
    %PY_CMD% -m pip install -r "%ROOT_DIR%\requirements.txt"
    if not %errorlevel%==0 (
        echo.
        echo Package install failed.
        echo From the project folder, try:
        echo   %PY_CMD% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%APP_DIR%restream_app.py"
    exit /b 0
)

%PY_CMD% "%APP_DIR%restream_app.py"
if not %errorlevel%==0 (
    echo.
    echo Restream Control exited with an error.
    pause
)
