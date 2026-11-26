$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "backup.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$helper`""
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "EQP4L-Database-Daily-Backup" -Action $action -Trigger $trigger -Settings $settings -Description "Daily EQP4L database and media volume backup" -Force
Write-Host "Registered daily local backup task: EQP4L-Database-Daily-Backup (database + media volume)"
