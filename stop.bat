@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PMA_PORT set "PMA_PORT=8000"

set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%PMA_PORT% .*LISTENING"') do (
  if not "%%p"=="0" (
    taskkill /PID %%p /T /F >nul 2>&1
    set "FOUND=1"
  )
)
rem Also close the minimised server window started by start.bat, if still open
taskkill /FI "WINDOWTITLE eq PMA Server*" /T /F >nul 2>&1

if defined FOUND (
  echo PMA stopped.
) else (
  echo PMA was not running on port %PMA_PORT%.
)
exit /b 0
