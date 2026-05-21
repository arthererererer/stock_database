# 相容轉送：日／月管線已拆分為 run_daily_crawl_etl.ps1、run_monthly_crawl_etl.ps1。
# 仍執行本檔時，等同只跑「日頻率」（舊 -Mode FxOnly）。月頻率請執行 run_monthly_crawl_etl.ps1。
$ErrorActionPreference = 'Continue'
$target = Join-Path $PSScriptRoot "run_daily_crawl_etl.ps1"
if (-not (Test-Path $target)) { Write-Error "找不到 $target"; exit 1 }
& $target
exit $LASTEXITCODE
