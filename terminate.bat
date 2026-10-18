@echo off
rem Stop the Hotel Demand Forecaster server (everything listening on its port).
setlocal enabledelayedexpansion
set PORT=8000
set FOUND=

rem Repeat a few times: on Windows more than one process can listen on the
rem same port, and one may still be starting up.
for /l %%n in (1,1,5) do (
    set LEFT=
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
        if not "%%p"=="0" (
            taskkill /PID %%p /T /F >nul 2>&1
            set FOUND=1
            set LEFT=1
        )
    )
    if not defined LEFT goto done
    ping -n 2 127.0.0.1 >nul
)

:done
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo Could not stop everything on port %PORT%. Close the "Hotel Demand Forecaster" window manually.
    endlocal
    exit /b 1
)
if defined FOUND (
    echo Server on port %PORT% stopped.
) else (
    echo No server is running on port %PORT%.
)
endlocal
