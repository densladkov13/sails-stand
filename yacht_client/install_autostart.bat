@echo off
setlocal
cd /d "%~dp0\.."

echo ============================================================
echo   SAILS - enable autostart for the yacht client
echo ============================================================
echo.
echo This adds a shortcut to the Windows Startup folder so the yacht
echo client (start_yacht_client.bat) launches automatically whenever
echo this computer turns on or you log in - useful if it reboots on
echo its own during the event. Run start_yacht_client.bat by hand at
echo least once first, so it already knows the stand's address.
echo.
set /p CONFIRM=Continue? (y/n):
if /i not "%CONFIRM%"=="y" (
    echo Cancelled, nothing changed.
    pause
    exit /b 0
)

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP_DIR%\SAILS-Yacht-Client.lnk"
set "TARGET=%~dp0start_yacht_client.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%~dp0..'; $s.WindowStyle = 1; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo Done. The yacht client will start automatically from now on.
    echo To undo this later, delete this file:
    echo   %SHORTCUT%
) else (
    echo.
    echo ERROR: could not create the startup shortcut.
)
pause
