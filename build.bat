@echo off
rem Build the desktop app and installer (see packaging\build.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1" %*
if errorlevel 1 pause
