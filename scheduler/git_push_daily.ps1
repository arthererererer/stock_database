$repoPath = "C:\Users\User\Desktop\個股資料庫"
$logFile  = "$repoPath\scheduler\logs\git_push_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Set-Location $repoPath
Log "=== 開始每日 GitHub push ==="

# 檢查是否有變更
$status = git status --porcelain 2>&1
if (-not $status) {
    Log "無變更，略過 commit。"
} else {
    git add -A 2>&1 | ForEach-Object { Log $_ }
    $msg = "daily update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git commit -m $msg 2>&1 | ForEach-Object { Log $_ }
    Log "Commit 完成：$msg"
}

git push origin main 2>&1 | ForEach-Object { Log $_ }
Log "=== Push 完成 ==="
