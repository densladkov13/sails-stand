@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   SAILS - enable autostart on this computer
echo ============================================================
echo.
echo This adds a shortcut to the Windows Startup folder so the stand
echo (start.bat) launches automatically whenever this computer turns
echo on or you log in - useful if power blips during the event.
echo It waits 30 seconds first, so you can close the window if needed.
echo.
set /p CONFIRM=Continue? (y/n):
if /i not "%CONFIRM%"=="y" (
    echo Cancelled, nothing changed.
    pause
    exit /b 0
)

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP_DIR%\SAILS-Stand.lnk"
set "TARGET=%~dp0start.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.Arguments = 'autostart'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 1; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo Done. SAILS will start automatically from now on.
    echo To undo this later, delete this file:
    echo   %SHORTCUT%
) else (
    echo.
    echo ERROR: could not create the startup shortcut.
)
pause
