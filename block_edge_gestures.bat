@echo off
setlocal
net session >nul 2>nul
if errorlevel 1 (
    echo This needs administrator rights.
    echo Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo ============================================================
echo   SAILS - block Windows touch swipes from the screen edges
echo ============================================================
echo.
echo Disables: swipe-in panels (notifications, widgets, task view) and the
echo news/widgets flyout. Takes effect after a restart or sign-out.
echo To undo, run unblock_edge_gestures.bat as administrator.
echo.

reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\EdgeUI" /v AllowEdgeSwipe /t REG_DWORD /d 0 /f
reg add "HKLM\SOFTWARE\Microsoft\PolicyManager\default\LockDown\AllowEdgeSwipe" /v value /t REG_DWORD /d 0 /f
reg add "HKLM\SOFTWARE\Policies\Microsoft\Dsh" /v AllowNewsAndInterests /t REG_DWORD /d 0 /f

echo.
echo Done. Restart the computer for it to take effect.
pause
