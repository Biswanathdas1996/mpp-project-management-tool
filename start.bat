@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PMA_PORT set "PMA_PORT=8000"
set "URL=http://localhost:%PMA_PORT%"
rem Health checks use 127.0.0.1: "localhost" may resolve to IPv6 (::1) first and time out
set "CHECK_URL=http://127.0.0.1:%PMA_PORT%"

if not exist "backend\.venv\Scripts\python.exe" goto :needsetup
if not exist "frontend\dist\index.html" goto :needsetup
if not exist "backend\.env" goto :needsetup

rem Already running?
netstat -ano | findstr /R /C:":%PMA_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo PMA is already running on %URL%
  start "" "%URL%"
  exit /b 0
)

if not exist "backend\data" mkdir "backend\data"
echo Starting PMA on %URL% ...
rem Runs minimised in its own window ("PMA Server"); output goes to backend\data\server.log
start "PMA Server" /min /d "%~dp0backend" cmd /c ""%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PMA_PORT% >> data\server.log 2>&1"

rem Wait up to 90 s for the health check (one PowerShell loop; works even when input is redirected)
powershell -NoProfile -Command "$u='%CHECK_URL%/api/health'; for ($i = 0; $i -lt 90; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u).StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"
if not errorlevel 1 goto :ready
echo [ERROR] PMA did not start within 90 seconds. Last lines of backend\data\server.log:
powershell -NoProfile -Command "Get-Content 'backend\data\server.log' -Tail 25"
pause
exit /b 1

:ready
echo PMA is running: %URL%   (API docs: %URL%/api/docs)
echo Logs: backend\data\server.log  -  stop with stop.bat
start "" "%URL%"
exit /b 0

:needsetup
echo PMA is not set up yet. Please run setup.bat first.
pause
exit /b 1
