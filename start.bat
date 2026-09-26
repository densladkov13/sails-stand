@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "GIT_TERMINAL_PROMPT=0"

rem Pinned Python version to auto-install if none is found. Bump PYVER and
rem PYUSERDIR together (the installer folder is named after MAJOR.MINOR only).
set "PYVER=3.11.9"
set "PYUSERDIR=%LocalAppData%\Programs\Python\Python311"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYINSTALLER=%TEMP%\python-%PYVER%-installer.exe"

rem Pinned portable Git, and the project's GitHub URL - used to auto-install
rem Git if missing, and to auto-repair a folder that was copied by hand
rem instead of cloned (so it can't self-update). Same pattern as Python above.
set "GITVER=2.46.0"
set "GITUSERDIR=%LocalAppData%\Programs\MinGit"
set "GITURL=https://github.com/git-for-windows/git/releases/download/v%GITVER%.windows.1/MinGit-%GITVER%-64-bit.zip"
set "GITZIP=%TEMP%\mingit-%GITVER%.zip"
set "REPO_URL=https://github.com/densladkov13/sails-stand.git"

echo ============================================================
echo   SAILS - starting the stand
echo ============================================================

rem Started by Windows autostart (shortcut passes "autostart"): wait 30 s so
rem there is time to close this window if you need to work on the machine.
rem Press any key to skip the wait.
if /i "%~1"=="autostart" (
    echo Autostart: the stand starts in 30 seconds.
    echo Close this window to cancel, or press any key to start right now.
    timeout /t 30
)

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
    echo [1/5] Python found: !PYTHON_EXE!
)

rem ---------- 2. Find or install Git (needed only for updates) ----------
set "GIT_EXE="
where git.exe >nul 2>nul
if not errorlevel 1 set "GIT_EXE=git"
if not defined GIT_EXE (
    if exist "%GITUSERDIR%\cmd\git.exe" set "GIT_EXE=%GITUSERDIR%\cmd\git.exe"
)
if not defined GIT_EXE (
    echo [2/5] Git not found - downloading a portable copy ^(needs internet^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%GITURL%' -OutFile '%GITZIP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
    if not errorlevel 1 (
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "Expand-Archive -Path '%GITZIP%' -DestinationPath '%GITUSERDIR%' -Force"
    )
    if exist "%GITUSERDIR%\cmd\git.exe" (
        set "GIT_EXE=%GITUSERDIR%\cmd\git.exe"
        echo Git installed.
    ) else (
        echo WARNING: could not set up Git - the app will still run fine, but
        echo automatic updates ^(update.bat / the admin panel^) will not work
        echo until Git is installed manually from git-scm.com.
    )
) else (
    echo [2/5] Git found: !GIT_EXE!
)

rem ---------- 3. Repair a folder that was copied by hand instead of cloned ----------
rem (so it has no .git and can't self-update). This overwrites tracked files
rem (config.json, .bat/.py files) with the latest from GitHub - that's the
rem point (it fixes a stale copy in one run); it never touches .env, .venv
rem or yacht_client\yacht.cfg since those are gitignored, not tracked.
if defined GIT_EXE (
    if not exist ".git" (
        echo Connecting this folder to Git so it can update itself...
        "!GIT_EXE!" init -q
        "!GIT_EXE!" remote add origin "%REPO_URL%" >nul 2>nul
        "!GIT_EXE!" fetch origin -q
        if not errorlevel 1 (
            "!GIT_EXE!" reset --hard origin/master >nul
            echo Connected and synced to the latest version - update.bat and the admin panel will work from now on.
        ) else (
            echo WARNING: could not reach GitHub to connect this folder. The app
            echo will still run; automatic updates can be set up later.
        )
    )
)

rem ---------- 4. Virtual environment ----------
if not exist ".venv\Scripts\python.exe" (
    echo [3/5] Creating virtual environment...
    "!PYTHON_EXE!" -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: failed to create the virtual environment.
        pause
        exit /b 1
    )
)

rem ---------- 5. Dependencies ----------
echo [4/5] Checking dependencies...
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

rem ---------- 6. Run, auto-restart on crash ----------
echo [5/5] Starting server ^(auto-restarts if it crashes; close this window to stop^)...
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
