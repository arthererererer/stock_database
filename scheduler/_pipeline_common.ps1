# 共用：日／月排程腳本請先 . 本檔，再呼叫 Initialize-EtlPipeline、Invoke-EtlTaskSequence。
# 任務 hashtable：Name, Script, Args（陣列）, EnvVars（可選 hashtable）

$script:EtlLogFile     = $null
$script:EtlProjectRoot = $null

function Initialize-EtlPipeline {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$LogTag
    )
    $script:EtlProjectRoot = $ProjectRoot
    $logDir = Join-Path $ProjectRoot "scheduler\logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $script:EtlLogFile = Join-Path $logDir ("{0}_{1}.log" -f $LogTag, (Get-Date -Format "yyyyMMdd_HHmmss"))
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts][$Level] $Message"
    Write-Host $line
    Add-Content -Path $script:EtlLogFile -Value $line -Encoding UTF8
}

function Test-DatabaseUrlConfigured {
    if (-not $env:DATABASE_URL) {
        Write-Log "DATABASE_URL 未設定，ETL 中止" "ERROR"
        return $false
    }
    return $true
}

function Run-Task {
    param($Task)
    Write-Log "--- 開始：$($Task.Name) ---"
    Write-Log "  （長時間任務會即時寫入下列輸出；另可開工作管理員查看 python.exe / Chromium 是否在使用 CPU）"

    if (-not (Test-Path $Task.Script)) {
        Write-Log "找不到腳本，跳過：$($Task.Script)" "SKIP"
        return $false
    }

    if ($Task.EnvVars) {
        foreach ($kv in $Task.EnvVars.GetEnumerator()) {
            [System.Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, 'Process')
        }
    }

    $env:PYTHONUNBUFFERED = "1"
    if (-not $env:PYTHONIOENCODING) { $env:PYTHONIOENCODING = "utf-8" }

    $wd = Split-Path $Task.Script -Parent
    $exitCode = -1

    $wdEsc = $wd.Replace('"', '""')
    $scriptEsc = "$($Task.Script)".Replace('"', '""')
    $argParts = foreach ($a in $Task.Args) {
        $as = "$a"
        if ($as -match '[\s"]') { '"' + ($as.Replace('"', '""')) + '"' } else { $as }
    }
    $argStr = $argParts -join ' '
    # 避免雙引號巢狀造成 PS5 解析錯誤，改以字串串接組 cmd 內文
    $cmdInner = ('cd /d "{0}" && set PYTHONUNBUFFERED=1 && python -u "{1}" {2}' -f $wdEsc, $scriptEsc, $argStr)

    try {
        cmd /c $cmdInner 2>&1 | ForEach-Object {
            $line = if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $_.Exception.Message
            } else {
                "$_"
            }
            if ($line -match "UserWarning|numexpr|bottleneck|from pandas") { return }
            Write-Log "  $line"
        }
        $exitCode = $LASTEXITCODE
    }
    catch {
        Write-Log "  執行例外：$_" "ERROR"
        $exitCode = 1
    }

    if ($exitCode -eq 0) {
        Write-Log "完成（exit 0）"
        return $true
    }
    elseif ($exitCode -eq -1) {
        Write-Log "無法取得結束代碼（請確認 python 是否在 PATH）" "ERROR"
        return $false
    }
    else {
        Write-Log "執行失敗（exit $exitCode）" "ERROR"
        return $false
    }
}

function Invoke-EtlTaskSequence {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][object[]]$Tasks
    )

    $env:PYTHONIOENCODING = "utf-8"
    if (-not (Test-DatabaseUrlConfigured)) { exit 1 }

    Write-Log "========== $Title 開始 =========="
    Write-Log "專案根目錄：$script:EtlProjectRoot"

    $successCount = 0
    $failCount    = 0
    foreach ($task in $Tasks) {
        $ok = Run-Task -Task $task
        if ($ok) { $successCount++ } else { $failCount++ }
        Write-Log ""
    }

    Write-Log "========== $Title 結束 =========="
    Write-Log "成功：$successCount 個任務　失敗：$failCount 個任務"
    if ($failCount -gt 0) { exit 1 } else { exit 0 }
}
