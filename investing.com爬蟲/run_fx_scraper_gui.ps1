$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Test-YyyyMmDd {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    $clean = $Text.Trim()
    if ($clean.Length -ne 8) { return $false }
    try {
        [datetime]::ParseExact($clean, 'yyyyMMdd', $null) | Out-Null
        return $true
    }
    catch { return $false }
}

function Show-Error {
    param([string]$Title, [string]$Body)
    [System.Windows.Forms.MessageBox]::Show(
        $Body, $Title, 'OK',
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Show-Info {
    param([string]$Title, [string]$Body)
    [System.Windows.Forms.MessageBox]::Show(
        $Body, $Title, 'OK',
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

$form = New-Object System.Windows.Forms.Form
$form.Text        = '匯率爬蟲 — investing.com'
$form.Font        = New-Object System.Drawing.Font('Microsoft JhengHei', 10)
$form.Size        = New-Object System.Drawing.Size(500, 320)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$lbStyle = @{ Width = 180; Left = 20 }
$tbStyle = @{ Width = 260; Left = 210 }

$l1 = New-Object System.Windows.Forms.Label
$l1.Text  = '起始日'
$l1.Top   = 26; $l1.Left = $lbStyle.Left; $l1.Width = $lbStyle.Width
$form.Controls.Add($l1)

$tbStart = New-Object System.Windows.Forms.TextBox
$tbStart.Top  = 22; $tbStart.Left = $tbStyle.Left; $tbStart.Width = $tbStyle.Width
$tbStart.Text = '20260101'
$form.Controls.Add($tbStart)

$l1h = New-Object System.Windows.Forms.Label
$l1h.Text = 'YYYYMMDD'
$l1h.Top  = 46; $l1h.Left = $tbStyle.Left; $l1h.Width = 120
$l1h.ForeColor = [System.Drawing.Color]::Gray
$l1h.Font = New-Object System.Drawing.Font('Microsoft JhengHei', 8)
$form.Controls.Add($l1h)

$l2 = New-Object System.Windows.Forms.Label
$l2.Text  = '結束日'
$l2.Top   = 74; $l2.Left = $lbStyle.Left; $l2.Width = $lbStyle.Width
$form.Controls.Add($l2)

$tbEnd = New-Object System.Windows.Forms.TextBox
$tbEnd.Top  = 70; $tbEnd.Left = $tbStyle.Left; $tbEnd.Width = $tbStyle.Width
$tbEnd.Text = (Get-Date).ToString('yyyyMMdd')
$form.Controls.Add($tbEnd)

$l2h = New-Object System.Windows.Forms.Label
$l2h.Text = 'YYYYMMDD'
$l2h.Top  = 94; $l2h.Left = $tbStyle.Left; $l2h.Width = 120
$l2h.ForeColor = [System.Drawing.Color]::Gray
$l2h.Font = New-Object System.Drawing.Font('Microsoft JhengHei', 8)
$form.Controls.Add($l2h)

$sep1 = New-Object System.Windows.Forms.Label
$sep1.BorderStyle = [System.Windows.Forms.BorderStyle]::Fixed3D
$sep1.Top = 120; $sep1.Left = 20; $sep1.Width = 440; $sep1.Height = 2
$form.Controls.Add($sep1)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = (
    '說明：' + [Environment]::NewLine +
    '爬取 investing.com 10 種幣種對 USD 的歷史匯率。' + [Environment]::NewLine +
    '幣種：KRW、EUR、JPY、GBP、AUD、CAD、HKD、CNY、TWD、INR' + [Environment]::NewLine + [Environment]::NewLine +
    '爬蟲會開啟瀏覽器視窗，執行時間約 10~20 分鐘。' + [Environment]::NewLine +
    '完成後輸出：fx_history_combined.csv（存於本程式所在資料夾）'
)
$hint.Top    = 132; $hint.Left = 20; $hint.Width = 450; $hint.Height = 110
$hint.ForeColor = [System.Drawing.Color]::DimGray
$hint.Font = New-Object System.Drawing.Font('Microsoft JhengHei', 9)
$form.Controls.Add($hint)

$btnRun = New-Object System.Windows.Forms.Button
$btnRun.Text   = '開始爬蟲'
$btnRun.Top    = 248; $btnRun.Left = 100; $btnRun.Width = 130; $btnRun.Height = 34
$btnRun.Font   = New-Object System.Drawing.Font('Microsoft JhengHei', 10, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($btnRun)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = '關閉'
$btnClose.Top  = 248; $btnClose.Left = 250; $btnClose.Width = 100; $btnClose.Height = 34
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

$btnRun.Add_Click({
    $start = $tbStart.Text.Trim()
    $end   = $tbEnd.Text.Trim()

    if (-not (Test-YyyyMmDd $start)) {
        Show-Error '日期格式錯誤' '起始日格式錯誤或空白。
請輸入 8 碼日期，例如：20260401。'
        return
    }
    if (-not (Test-YyyyMmDd $end)) {
        Show-Error '日期格式錯誤' '結束日格式錯誤或空白。
請輸入 8 碼日期，例如：20260410。'
        return
    }
    $dtStart = [datetime]::ParseExact($start, 'yyyyMMdd', $null)
    $dtEnd   = [datetime]::ParseExact($end,   'yyyyMMdd', $null)
    if ($dtStart -gt $dtEnd) {
        Show-Error '日期順序錯誤' '起始日不可晚於結束日。'
        return
    }

    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Show-Error '找不到 Python' '找不到 python 指令。
請安裝 Python 並確認已加入 PATH。'
        return
    }

    $scrapeScript = Join-Path $PSScriptRoot 'scrape_fx_history.py'
    if (-not (Test-Path $scrapeScript)) {
        Show-Error '找不到程式' '找不到 scrape_fx_history.py。
請確認與本程式放在同一資料夾。'
        return
    }

    [System.Windows.Forms.MessageBox]::Show(
        '即將開啟瀏覽器進行爬蟲，執行時間約 10~20 分鐘。

請勿關閉彈出的瀏覽器或主控台視窗，
完成後本視窗會自動通知您。',
        '開始爬蟲', 'OK',
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null

    $form.Hide()

    $startFmt = '{0}-{1}-{2}' -f $start.Substring(0,4), $start.Substring(4,2), $start.Substring(6,2)
    $endFmt   = '{0}-{1}-{2}' -f $end.Substring(0,4),   $end.Substring(4,2),   $end.Substring(6,2)

    $scrapeArgs = @(
        $scrapeScript,
        '--start-date', $startFmt,
        '--end-date',   $endFmt
    )
    $proc = Start-Process $py.Source -ArgumentList $scrapeArgs `
        -WorkingDirectory $PSScriptRoot -Wait -PassThru

    $form.Show()
    $form.BringToFront()

    if ($proc.ExitCode -ne 0) {
        Show-Error '爬蟲執行失敗' (
            '爬蟲程式異常結束（代碼 {0}）。
請查看主控台視窗內的錯誤訊息。' -f $proc.ExitCode
        )
        return
    }

    $fxCsv = Join-Path $PSScriptRoot 'fx_history_combined.csv'
    if (-not (Test-Path $fxCsv)) {
        Show-Error '找不到輸出檔' '爬蟲已完成，但找不到 fx_history_combined.csv。
可能所有貨幣均爬取失敗，請重新執行。'
        return
    }

    Show-Info '爬蟲完成' (
        '匯率資料已成功儲存至：
{0}

下一步：執行 ETL 腳本將資料匯入資料庫：
python etl/load_crawler_fx.py --file "{0}"' -f $fxCsv
    )
})

[void]$form.ShowDialog()
