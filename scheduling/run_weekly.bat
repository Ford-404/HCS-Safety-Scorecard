@echo off
REM Runs the weekly Safety Health Report. Used by Windows Task Scheduler.
cd /d "%~dp0.."
REM The email is handed to Power Automate through OneDrive, so make sure OneDrive is running.
tasklist /fi "imagename eq OneDrive.exe" | find /i "OneDrive.exe" >nul || (
    if exist "%ProgramFiles%\Microsoft OneDrive\OneDrive.exe" (start "" "%ProgramFiles%\Microsoft OneDrive\OneDrive.exe" /background) else if exist "%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe" (start "" "%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe" /background)
    echo %date% %time% Started OneDrive >> "logs\scheduler.log"
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run_weekly.py >> "logs\scheduler.log" 2>&1
) else (
    python run_weekly.py >> "logs\scheduler.log" 2>&1
)
exit /b %ERRORLEVEL%
