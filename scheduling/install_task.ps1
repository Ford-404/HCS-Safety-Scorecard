# Registers the weekly Windows scheduled task (default Monday 6:00 AM, PC local time).
#   powershell -ExecutionPolicy Bypass -File scheduling\install_task.ps1 [-Day Monday] [-Time 06:00]
# Runs as the signed-in user (Excel recalculation and OneDrive sync need the user session). Keep the user signed in
# (lock the screen rather than signing out) on the always-on PC.
param([string]$Day = "Monday", [string]$Time = "06:00", [string]$TaskName = "HCS Safety Health Report")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction -Execute (Join-Path $root "scheduling\run_weekly.bat") -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Scheduled '$TaskName' every $Day at $Time. Run it now with:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Green
