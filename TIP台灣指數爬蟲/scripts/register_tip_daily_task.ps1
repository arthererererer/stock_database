#Requires -Version 5.1
#Requires -RunAsAdministrator
# Register daily 18:00 interactive task (TIP-Daily-TIP-History).
$ErrorActionPreference = 'Stop'

$interactivePath = (Resolve-Path (Join-Path $PSScriptRoot 'run_daily_tip_interactive.ps1')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not (Test-Path -LiteralPath $interactivePath)) {
    throw "Script not found: $interactivePath"
}

$taskName = 'TIP-Daily-TIP-History'
$userId = $env:USERNAME
if ($env:USERDOMAIN -and ($env:USERDOMAIN -ne $env:COMPUTERNAME)) {
    $userId = "$($env:USERDOMAIN)\$($env:USERNAME)"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File `"$interactivePath`""
try {
    $action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $arg -WorkingDirectory $projectRoot
} catch {
    $action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $arg
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$trigger = New-ScheduledTaskTrigger -Daily -At '6:00PM'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Daily 18:00 interactive: ask Y/N and date range; save output\daily_schedule_YYYYMMDD_YYYYMMDD.csv then merge to all_history.csv' | Out-Null

Write-Host "Registered scheduled task: $taskName (daily 18:00, interactive)"
Write-Host "  Script: $interactivePath"
Write-Host "  Working dir: $projectRoot"
Write-Host "  Principal: $userId (Interactive - must be logged on at 18:00 to see the window)"
Write-Host "Open taskschd.msc -> Task Scheduler Library to verify."
