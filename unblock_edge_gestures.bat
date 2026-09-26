@echo off
setlocal
net session >nul 2>nul
if errorlevel 1 (
    echo This needs administrator rights.
    echo Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

reg delete "HKLM\SOFTWARE\Policies\Microsoft\Windows\EdgeUI" /v AllowEdgeSwipe /f
reg delete "HKLM\SOFTWARE\Microsoft\PolicyManager\default\LockDown\AllowEdgeSwipe" /v value /f
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Dsh" /v AllowNewsAndInterests /f

echo.
echo Edge swipes are allowed again after a restart.
pause
