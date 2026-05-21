# 轉送專案「日頻率」排程管線（爬蟲 + 入庫）。實際任務清單在 ..\scheduler\run_daily_crawl_etl.ps1。
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$target = Join-Path $ProjectRoot "scheduler\run_daily_crawl_etl.ps1"
if (-not (Test-Path $target)) { Write-Error "找不到 $target"; exit 1 }
& $target
exit $LASTEXITCODE
