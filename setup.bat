@echo off
setlocal EnableExtensions
title PMA - Setup
cd /d "%~dp0"

echo ============================================================
echo   Project Management Accelerator - one-time setup
echo ============================================================
echo.

rem ---------------------------------------------------------------- prerequisites
set "PY="
where py >nul 2>&1 && ( py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3" )
if not defined PY (
  where python >nul 2>&1 && ( python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python" )
)
if not defined PY (
  echo [ERROR] Python 3.11 or newer is required: https://www.python.org/downloads/
  goto :fail
)
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do echo [OK] Python %%v

where java >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Java 11 or newer is required to read MS Project files.
  echo         Install e.g. Microsoft OpenJDK 17: https://learn.microsoft.com/java/openjdk/download
  goto :fail
)
echo [OK] Java found

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js 20 or newer is required to build the UI: https://nodejs.org/
  goto :fail
)
for /f "delims=" %%v in ('node --version') do echo [OK] Node %%v
echo.

rem ---------------------------------------------------------------- backend
echo [1/4] Creating Python environment...
if not exist "backend\.venv\Scripts\python.exe" (
  %PY% -m venv backend\.venv || goto :fail
)
echo [2/4] Installing backend packages (first run can take a few minutes)...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
"backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt --quiet || goto :fail

rem ---------------------------------------------------------------- frontend
echo [3/4] Installing and building the web UI...
pushd frontend
call npm ci --no-audit --no-fund --loglevel=error || ( popd & goto :fail )
call npm run build || ( popd & goto :fail )
popd

rem ---------------------------------------------------------------- configuration
echo [4/4] Configuring...
pushd backend
"%~dp0backend\.venv\Scripts\python.exe" scripts\init_env.py || ( popd & goto :fail )
popd

echo ============================================================
echo   Setup complete. Run start.bat to launch PMA.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Setup did not complete - see the message above.
pause
exit /b 1
