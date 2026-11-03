@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m UI
) else (
  py -m UI
)
if errorlevel 1 (
  echo.
  echo UI startup failed. Install requirements-ui.txt and check Python.
  pause
)
