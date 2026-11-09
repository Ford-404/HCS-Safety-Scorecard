@echo off
REM Runs the weekly Safety Health Report. Used by Windows Task Scheduler.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run_weekly.py >> "logs\scheduler.log" 2>&1
) else (
    python run_weekly.py >> "logs\scheduler.log" 2>&1
)
exit /b %ERRORLEVEL%
