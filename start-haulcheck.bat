@echo off
REM ===================================================================
REM  HaulCheck - double-click launcher (Windows)
REM  Opens two windows: the API and the web app. MongoDB runs as a
REM  Windows service, so it is already up - nothing to start for it.
REM  Close either window to stop that part. See CLIENT_SETUP for help.
REM ===================================================================

echo Starting HaulCheck...
echo   - API  window: http://localhost:8000
echo   - Web  window: http://localhost:3000  (opens in your browser)
echo.
echo Leave both windows open while you use the app.
echo.

start "HaulCheck API" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python -m uvicorn server:app --port 8000"

REM Give the API a few seconds to boot before the browser opens.
timeout /t 5 /nobreak >nul

start "HaulCheck Web" cmd /k "cd /d "%~dp0frontend" && yarn start"
