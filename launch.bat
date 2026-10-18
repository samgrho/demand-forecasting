@echo off
rem Start the Hotel Demand Forecaster in its own minimized window and open the dashboard.
rem Usage: launch.bat [--no-browser]
setlocal
set PORT=8000
cd /d "%~dp0"

rem Already running?
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo Server is already running on port %PORT%.
    goto open
)

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment and installing dependencies...
    python -m venv .venv || goto fail
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto fail
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example - add your SCRAPER_CONTACT and TICKETMASTER_API_KEY there.
)

echo Starting server on http://localhost:%PORT% ...
start "Hotel Demand Forecaster" /min ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

rem Wait up to 30 seconds for the server to accept connections.
for /l %%i in (1,1,30) do (
    netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul && goto ready
    rem ping as a 1-second sleep: unlike timeout, it works without an interactive console
    ping -n 2 127.0.0.1 >nul
)
echo Server did not start. Check the "Hotel Demand Forecaster" window for errors.
goto fail

:ready
echo Server is running. Use terminate.bat to stop it.

:open
if /i not "%~1"=="--no-browser" start "" "http://localhost:%PORT%"
endlocal
exit /b 0

:fail
endlocal
exit /b 1
