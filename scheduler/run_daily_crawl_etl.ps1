# =============================================================
# run_daily_crawl_etl.ps1 — 日頻率：爬蟲 + 入庫（預設 investing.com 匯率）
#
# 擴充：在 $dailyTasks 陣列末端依序新增 hashtable：
#   @{ Name = "顯示名稱"; Script = "完整路徑.py"; Args = @("arg1","arg2"); EnvVars = @{ KEY = "val" } }
# Script 建議以 Join-Path $ProjectRoot "子資料夾\腳本.py" 組出，便於搬移專案。
# =============================================================

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "_pipeline_common.ps1")

Initialize-EtlPipeline -ProjectRoot $ProjectRoot -LogTag "daily_etl"

$StartDate = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
$EndDate   = (Get-Date).ToString("yyyy-MM-dd")
$FxCsv     = Join-Path $ProjectRoot "investing.com爬蟲\fx_history_combined.csv"

$TipDate = (Get-Date).ToString("yyyyMMdd")
$TipCsv  = Join-Path $ProjectRoot "TIP台灣指數爬蟲\output\tip_${TipDate}_${TipDate}.csv"

$dailyTasks = @(

    @{
        Name   = "investing.com 匯率爬蟲"
        Script = Join-Path $ProjectRoot "investing.com爬蟲\scrape_fx_history.py"
        Args   = @(
            "--start-date", $StartDate,
            "--end-date",   $EndDate,
            "--output",     $FxCsv
        )
    },

    @{
        Name   = "匯率 ETL（fx_crawler → PostgreSQL）"
        Script = Join-Path $ProjectRoot "etl\load_crawler_fx.py"
        Args   = @("--file", $FxCsv)
    },

    @{
        Name   = "TIP 指數爬蟲（今日）"
        Script = Join-Path $ProjectRoot "TIP台灣指數爬蟲\scrape_tip_history.py"
        Args   = @("--all", "--today", "-o", $TipCsv)
    },

    @{
        Name   = "TIP 指數 ETL（today CSV → PostgreSQL）"
        Script = Join-Path $ProjectRoot "etl\load_tip.py"
        Args   = @("--file", $TipCsv)
    },

    @{
        Name   = "中央銀行 日頻率爬蟲（scraper_cbc.py --freq 日）"
        Script = "C:\Users\User\Desktop\總經資料庫\scraper_cbc.py"
        Args   = @("--force", "--freq", "日")
    },

    @{
        Name   = "中央銀行 日頻率 ETL（cbc_observations --freq 日）"
        Script = "C:\Users\User\Desktop\總經資料庫\load_cbc.py"
        Args   = @("--freq", "日")
    }

    # 未來其他「每日」來源請加在陣列末尾，例如：
    # @{ Name = "…"; Script = Join-Path $ProjectRoot "其他資料夾\crawl.py"; Args = @() },
    # @{ Name = "… ETL"; Script = Join-Path $ProjectRoot "etl\load_….py"; Args = @("--file", $someCsv) },
)

Invoke-EtlTaskSequence -Title "日頻率 ETL" -Tasks $dailyTasks
