#Requires -Version 5.1
# Interactive scrape (18:00 task): Y/N, start/end date -> daily_schedule_YYYYMMDD_YYYYMMDD.csv -> merge all_history.csv
# All prompts in ASCII so Windows PowerShell 5.1 does not mis-decode UTF-8 without BOM.
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

Write-Host ''
Write-Host '=== TIP index scrape (interactive) ==='
$yn = Read-Host 'Run scrape now? (Y/N)'
if ($yn -notmatch '^[Yy]') {
    Write-Host 'Cancelled.'
    Read-Host 'Press Enter to exit'
    exit 0
}

Write-Host ''
Write-Host 'Accepted formats: YYYY/MM/DD  or  YYYYMMDD  (examples: 2026/04/01  or  20260401)'
$d1 = Read-Host 'Start date'
$d2 = Read-Host 'End date'
$d1 = $d1.Trim()
$d2 = $d2.Trim()
if (-not $d1 -or -not $d2) {
    Write-Host 'ERROR: start and end dates are required.'
    Read-Host 'Press Enter to exit'
    exit 1
}

function Parse-UserDate([string]$raw) {
    $s = $raw.Trim()
    if ([string]::IsNullOrWhiteSpace($s)) {
        throw 'Empty date string'
    }
    if ($s -match '^\d{8}$') {
        $y = [int]$s.Substring(0, 4)
        $mo = [int]$s.Substring(4, 2)
        $d = [int]$s.Substring(6, 2)
        return Get-Date -Year $y -Month $mo -Day $d -Hour 12 -Minute 0 -Second 0
    }
    $norm = ($s -replace '\.', '/') -replace '-', '/'
    $formats = @('yyyy/M/d', 'yyyy/MM/dd', 'yyyy/M/dd', 'yyyy/MM/d')
    foreach ($f in $formats) {
        try {
            return [datetime]::ParseExact($norm, $f, [cultureinfo]::InvariantCulture, 'None')
        } catch { }
    }
    throw "Cannot parse date (use YYYY/MM/DD or YYYYMMDD): '$raw'"
}

try {
    $dt1 = Parse-UserDate $d1
    $dt2 = Parse-UserDate $d2
} catch {
    Write-Host $_.Exception.Message
    Read-Host 'Press Enter to exit'
    exit 1
}

$s1 = $dt1.ToString('yyyyMMdd')
$s2 = $dt2.ToString('yyyyMMdd')
$py1 = $dt1.ToString('yyyy/MM/dd')
$py2 = $dt2.ToString('yyyy/MM/dd')

$outRel = "output\tip_${s1}_${s2}.csv"
$logRel = "output\tip_${s1}_${s2}.log"
$outFile = Join-Path $ProjectRoot $outRel
$logFile = Join-Path $ProjectRoot $logRel

$logDir = Split-Path $logFile -Parent
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$startLine = '[{0}] START scrape_tip_history --all --start {1} --end {2} -> {3}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $py1, $py2, $outFile
Add-Content -LiteralPath $logFile -Value $startLine -Encoding UTF8

Write-Host ''
Write-Host "Running scrape -> $outRel ..."
& python scrape_tip_history.py --all --start $py1 --end $py2 -o $outFile 2>&1 | Tee-Object -FilePath $logFile -Append
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "Scrape failed (exit $code). Merge skipped."
    Read-Host 'Press Enter to exit'
    exit $code
}

$allHist = Join-Path $ProjectRoot 'output\all_history.csv'
Write-Host 'Merging into output\all_history.csv ...'
& python merge_daily_into_all_history.py $outFile -o $allHist
$code2 = $LASTEXITCODE
if ($code2 -ne 0) {
    Write-Host "Merge failed (exit $code2)"
    Read-Host 'Press Enter to exit'
    exit $code2
}

Write-Host 'Done: daily CSV saved and merged into all_history.csv'
Read-Host 'Press Enter to exit'
