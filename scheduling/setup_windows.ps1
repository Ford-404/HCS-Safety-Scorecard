# One-time setup on the always-on PC. Run from the project folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scheduling\setup_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11+ from python.org first (tick 'Add to PATH')." }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-windows.txt
New-Item -ItemType Directory -Force logs, output, data | Out-Null
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - open it and fill in the Procore client ID and secret." -ForegroundColor Yellow }
Write-Host "Setup done. Test with:  .\.venv\Scripts\python.exe run_weekly.py --no-email" -ForegroundColor Green
