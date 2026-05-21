# register_task.ps1
# 以系統管理員執行：註冊兩個 Windows 工作排程器工作
#   1) 日頻率：每日 18:00 → run_daily_crawl_etl.ps1（investing.com 匯率 + 入庫）
#   2) 月頻率：每月 15 日 15:00 → run_monthly_crawl_etl.ps1（玩股網月營收 + 主計處總經 + 入庫）
#
# 若曾註冊舊版工作名稱（FinPlatform_DailyETL / FinPlatform_DailyFx / FinPlatform_MonthlyWantgoo），
# 本腳本會先移除，再以新名稱 Daily_task / Monthly_task 重新建立。

param()

# ★ 請改為你的 PostgreSQL 連線字串 ★
$DatabaseUrl = "postgresql://postgres:yourpassword@localhost:5432/postgres"

$ScriptDaily   = Join-Path $PSScriptRoot "run_daily_crawl_etl.ps1"
$ScriptMonthly = Join-Path $PSScriptRoot "run_monthly_crawl_etl.ps1"
$RunAt         = "18:00"

if (-not (Test-Path $ScriptDaily)) {
    Write-Error "找不到 run_daily_crawl_etl.ps1：$ScriptDaily"
    exit 1
}
if (-not (Test-Path $ScriptMonthly)) {
    Write-Error "找不到 run_monthly_crawl_etl.ps1：$ScriptMonthly"
    exit 1
}

[System.Environment]::SetEnvironmentVariable("DATABASE_URL", $DatabaseUrl, "User")
Write-Host "DATABASE_URL 已寫入使用者環境變數。"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# ── 移除所有舊版工作名稱（若存在）───────────────────────────
foreach ($old in @("FinPlatform_DailyETL", "FinPlatform_DailyFx", "FinPlatform_MonthlyWantgoo")) {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false -ErrorAction SilentlyContinue
    schtasks /Delete /TN $old /F 2>$null | Out-Null
}

# ── 工作 1：日頻率（每日 18:00）──────────────────────────────
$TaskNameFx = "Daily_task"
Unregister-ScheduledTask -TaskName $TaskNameFx -Confirm:$false -ErrorAction SilentlyContinue

$triggerFx = New-ScheduledTaskTrigger -Daily -At $RunAt
$argFx     = "-NoProfile -ExecutionPolicy Bypass -File ""$ScriptDaily"""
$actionFx  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argFx

Register-ScheduledTask `
    -TaskName $TaskNameFx `
    -Trigger $triggerFx `
    -Action $actionFx `
    -Settings $settings `
    -Principal $principal `
    -Description "日頻率 ETL：匯率爬蟲 + 入庫，每日 $RunAt"

# ── 工作 2：月頻率（每月 15 日 15:00；用 schtasks 支援 MONTHLY 觸發）────
$TaskNameMr = "Monthly_task"
Unregister-ScheduledTask -TaskName $TaskNameMr -Confirm:$false -ErrorAction SilentlyContinue
schtasks /Delete /TN $TaskNameMr /F 2>$null | Out-Null

$trMr   = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ScriptMonthly`""
$schOut = schtasks /Create /F /TN $TaskNameMr /TR $trMr /SC MONTHLY /D 15 /ST 15:00 /RL HIGHEST 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "schtasks 建立月排程失敗（exit $LASTEXITCODE）：$schOut"
    Write-Warning "請改用手動：工作排程器 → 建立工作 → 每月、第 15 日、15:00 → 程式：$ScriptMonthly"
} else {
    Write-Host $schOut
}

Write-Host ""
Write-Host "排程已建立：" -ForegroundColor Green
Write-Host "  [$TaskNameFx]  每日      $RunAt  →  run_daily_crawl_etl.ps1"
Write-Host "  [$TaskNameMr]  每月15日  15:00  →  run_monthly_crawl_etl.ps1"
Write-Host ""
Write-Host "日排程：$ScriptDaily"
Write-Host "月排程：$ScriptMonthly"
Write-Host "Logs   : $(Join-Path $PSScriptRoot 'logs')"
Write-Host ""
Write-Host "手動執行範例："
Write-Host "  Start-ScheduledTask -TaskName '$TaskNameFx'"
Write-Host "  schtasks /Run /TN '$TaskNameMr'"
Write-Host "或直接："
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$ScriptDaily`""
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$ScriptMonthly`""
Write-Host ""
Write-Host "移除排程："
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskNameFx' -Confirm:`$false"
Write-Host "  schtasks /Delete /TN '$TaskNameMr' /F"
