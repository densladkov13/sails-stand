@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Pinned Python version to auto-install if none is found. Bump PYVER and
rem PYUSERDIR together (the installer folder is named after MAJOR.MINOR only).
set "PYVER=3.11.9"
set "PYUSERDIR=%LocalAppData%\Programs\Python\Python311"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYINSTALLER=%TEMP%\python-%PYVER%-installer.exe"

echo ============================================================
echo   SAILS - starting the stand
echo ============================================================

rem ---------- 1. Find or install Python ----------
set "PYTHON_EXE="
where python.exe >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    if exist "%PYUSERDIR%\python.exe" set "PYTHON_EXE=%PYUSERDIR%\python.exe"
)

if not defined PYTHON_EXE (
    echo [1/4] Python not found - downloading Python %PYVER% ^(needs internet^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINSTALLER%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        echo.
        echo ERROR: could not download Python. Check the internet connection on
        echo this computer, or install Python 3.10+ manually from python.org
        echo ^(check "Add python.exe to PATH"^) and run start.bat again.
        pause
        exit /b 1
    )

    echo Installing Python %PYVER% silently, please wait ^(no admin needed^)...
    "%PYINSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1

    if exist "%PYUSERDIR%\python.exe" (
        set "PYTHON_EXE=%PYUSERDIR%\python.exe"
    ) else (
        where python.exe >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=python"
        ) else (
            echo.
            echo ERROR: Python installation finished, but python.exe was not found.
            echo Close this window, open a NEW window ^(so PATH refreshes^) and
            echo run start.bat again.
            pause
            exit /b 1
        )
    )
    echo Python installed.
) else (
    echo [1/4] Python found: !PYTHON_EXE!
)

rem ---------- 2. Virtual environment ----------
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment...
    "!PYTHON_EXE!" -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: failed to create the virtual environment.
        pause
        exit /b 1
    )
)

rem ---------- 3. Dependencies ----------
echo [3/4] Checking dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: failed to install dependencies. Check the internet connection
    echo and re-run start.bat.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo ERROR: .env file not found ^(needs OPENROUTER_API_KEY^).
    echo Copy .env.example to .env and put your key in it, then run start.bat again.
    pause
    exit /b 1
)

rem ---------- 4. Run, auto-restart on crash ----------
echo [4/4] Starting server ^(auto-restarts if it crashes; close this window to stop^)...
echo.
:runloop
".venv\Scripts\python.exe" run.py
echo.
echo ------------------------------------------------------------
echo Server stopped or crashed just now ^(see the error above, if any^).
echo Restarting in 5 seconds... close this window to stop for good.
echo ------------------------------------------------------------
timeout /t 5 /nobreak >nul
goto runloop
