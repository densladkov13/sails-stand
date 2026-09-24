@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

rem Pinned Python version to auto-install if none is found. Bump PYVER and
rem PYUSERDIR together (the installer folder is named after MAJOR.MINOR only).
set "PYVER=3.11.9"
set "PYUSERDIR=%LocalAppData%\Programs\Python\Python311"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYINSTALLER=%TEMP%\python-%PYVER%-installer.exe"

echo ============================================================
echo   SAILS - yacht client
echo ============================================================

rem ---------- 1. Find or install Python ----------
set "PYTHON_EXE="
where python.exe >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    if exist "%PYUSERDIR%\python.exe" set "PYTHON_EXE=%PYUSERDIR%\python.exe"
)

if not defined PYTHON_EXE (
    echo [1/3] Python not found - downloading Python %PYVER% ^(needs internet^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINSTALLER%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        echo.
        echo ERROR: could not download Python. Check the internet connection on
        echo this computer, or install Python 3.10+ manually from python.org
        echo ^(check "Add python.exe to PATH"^) and run this file again.
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
            echo run this file again.
            pause
            exit /b 1
        )
    )
    echo Python installed.
) else (
    echo [1/3] Python found: !PYTHON_EXE!
)

rem ---------- 2. Virtual environment + dependencies ----------
if not exist ".venv\Scripts\python.exe" (
    echo [2/3] Creating virtual environment...
    "!PYTHON_EXE!" -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo [3/3] Checking dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: failed to install dependencies. Check the internet connection
    echo and re-run this file.
    pause
    exit /b 1
)

rem ---------- Stand address + yacht id: ask once, remember for next time ----------
rem (so this can auto-start unattended after a reboot without anyone typing
rem anything - delete yacht_client\yacht.cfg to be asked again)
set "CFG_FILE=yacht_client\yacht.cfg"
if exist "%CFG_FILE%" goto load_cfg
goto ask_cfg

:load_cfg
for /f "usebackq tokens=1,2 delims=|" %%a in ("%CFG_FILE%") do (
    set "STAND_HOST=%%a"
    set "YACHT_ID=%%b"
)
echo Using saved settings: %STAND_HOST% / %YACHT_ID%  ^(delete %CFG_FILE% to change^)
goto cfg_done

:ask_cfg
echo.
set /p STAND_HOST=Stand computer address (hostname.local or IP, e.g. SAILS-STAND.local):
if "%STAND_HOST%"=="" set "STAND_HOST=127.0.0.1"
set /p YACHT_ID=Yacht id from config.json [yacht1]:
if "%YACHT_ID%"=="" set "YACHT_ID=yacht1"
echo %STAND_HOST%^|%YACHT_ID%>"%CFG_FILE%"
echo Saved - next time this starts automatically, without asking.

:cfg_done
echo.
echo Connecting to %STAND_HOST%:8000 as "%YACHT_ID%" ^(auto-reconnects; close this window to stop^)...
echo.
:runloop
".venv\Scripts\python.exe" "yacht_client\yacht_client.py" --host %STAND_HOST% --port 8000 --yacht %YACHT_ID%
echo.
echo ------------------------------------------------------------
echo Client stopped or crashed just now ^(see the error above, if any^).
echo Restarting in 5 seconds... close this window to stop for good.
echo ------------------------------------------------------------
timeout /t 5 /nobreak >nul
goto runloop
