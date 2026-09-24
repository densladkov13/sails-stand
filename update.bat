@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   SAILS - update to latest version
echo ============================================================

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: this folder is not set up for updates ^(no git^).
    echo Ask for a fresh copy of the whole project instead.
    pause
    exit /b 1
)

git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: no "origin" remote configured yet. Run once ^(ask for the URL^):
    echo   git remote add origin ^<repository URL^>
    pause
    exit /b 1
)

echo [1/3] Fetching the latest version...
git fetch origin
if errorlevel 1 (
    echo.
    echo ERROR: could not reach the repository. Check the internet connection.
    pause
    exit /b 1
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"

git diff --quiet
if errorlevel 1 (
    echo.
    echo Note: you have local edits in this folder ^(e.g. config.json^) that are
    echo not part of the update. They will be kept unless the update changes
    echo the exact same lines - if that happens, git will say "CONFLICT" below.
    echo.
)

echo [2/3] Applying update ^(branch: %BRANCH%^)...
git pull origin %BRANCH%
if errorlevel 1 (
    echo.
    echo ERROR: update failed - see the message above.
    echo Nothing else was touched; fix the issue ^(or ask for help^) and run
    echo update.bat again.
    pause
    exit /b 1
)

echo [3/3] Re-checking dependencies...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
) else (
    echo ^(No .venv yet - run start.bat once first.^)
)

echo.
echo ============================================================
echo Done - this is now the latest version.
echo Close and re-run start.bat ^(or start_yacht_client.bat^) to apply it.
echo ============================================================
pause
