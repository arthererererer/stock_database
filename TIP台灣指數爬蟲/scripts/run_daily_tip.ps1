#Requires -Version 5.1
# Daily: scrape all TIP indices for --today -> output/daily_YYYYMMDD.csv + log
# Strings are ASCII-only so Big5/ANSI default encoding on zh-TW Windows does not break parsing.
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

$stamp = Get-Date -Format 'yyyyMMdd'
$logDir = Join-Path $ProjectRoot 'output'
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$logFile = Join-Path $logDir "daily_schedule_$stamp.log"
$outCsv = Join-Path $logDir "daily_$stamp.csv"

$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$startMsg = '[{0}] START scrape_tip_history --all --today -> {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $outCsv
Add-Content -LiteralPath $logFile -Value $startMsg -Encoding UTF8
Write-Host $startMsg

try {
    & python scrape_tip_history.py --all --today -o $outCsv 2>&1 | Tee-Object -FilePath $logFile -Append
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "python exit code $code"
    }
    $okMsg = '[{0}] OK.' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    Add-Content -LiteralPath $logFile -Value $okMsg -Encoding UTF8
    Write-Host $okMsg
} catch {
    $errMsg = '[{0}] FAIL: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $_
    Add-Content -LiteralPath $logFile -Value $errMsg -Encoding UTF8
    Write-Error $_
    exit 1
}
