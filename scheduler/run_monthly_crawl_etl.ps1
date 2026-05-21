# =============================================================
# run_monthly_crawl_etl.ps1 — 月頻率：爬蟲 + 入庫
#   1. 玩股網 月營收
#   2. 主計處 總體統計資料庫（macro schema）
#
# 擴充：在 $monthlyTasks 陣列末端依序新增 hashtable（格式同 run_daily_crawl_etl.ps1）。
# =============================================================

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "_pipeline_common.ps1")

Initialize-EtlPipeline -ProjectRoot $ProjectRoot -LogTag "monthly_etl"

# ── 玩股網設定 ────────────────────────────────────────────────
$WantgooMrCsv      = Join-Path $ProjectRoot "玩股網爬蟲\output\月營收_scheduled_latest.csv"
$WantgooRollingMo  = "4"
# 只爬清單前 N 檔（試跑 5～20；正式全清單務必 "0"）
$WantgooStockLimit = "0"

$wantgooScrapeArgs = @(
    "--rolling-months", $WantgooRollingMo,
    "-o",               $WantgooMrCsv,
    "--headless"
)
if ($WantgooStockLimit -and ($WantgooStockLimit -ne "0")) {
    $wantgooScrapeArgs += @("--limit", $WantgooStockLimit)
}

# ── 主計處設定 ────────────────────────────────────────────────
$MacroRoot    = "C:\Users\User\Desktop\總經資料庫"
$MacroDataDir = Join-Path $MacroRoot "主計處統計資料庫爬蟲"

$monthlyTasks = @(

    @{
        Name   = "玩股網 月營收爬蟲"
        Script = Join-Path $ProjectRoot "玩股網爬蟲\scrape_monthly_revenue.py"
        Args   = $wantgooScrapeArgs
    },

    @{
        Name   = "玩股網 月營收 ETL（wantgoo_monthly_revenue）"
        Script = Join-Path $ProjectRoot "etl\load_wantgoo_monthly_revenue.py"
        Args   = @("--file", $WantgooMrCsv)
    },

    @{
        Name   = "主計處 總體統計資料庫爬蟲（scraper.py）"
        Script = Join-Path $MacroRoot "scraper.py"
        Args   = @("--force")
    },

    @{
        Name   = "主計處 總體統計資料庫 ETL（macro schema）"
        Script = Join-Path $MacroRoot "load_macro_dgbas.py"
        Args   = @("--data-dir", $MacroDataDir)
    },

    @{
        Name   = "中央銀行 月/季/年頻率爬蟲（scraper_cbc.py --freq 月,季,年,）"
        Script = Join-Path $MacroRoot "scraper_cbc.py"
        Args   = @("--force", "--freq", "月,季,年,")
    },

    @{
        Name   = "中央銀行 月/季/年頻率 ETL（cbc_observations --freq 月,季,年,）"
        Script = Join-Path $MacroRoot "load_cbc.py"
        Args   = @("--data-dir", (Join-Path $MacroRoot "中央銀行資料庫爬蟲"), "--freq", "月,季,年,")
    },

    @{
        Name   = "財政部 統計資料庫爬蟲（scraper_mof.py）"
        Script = Join-Path $MacroRoot "scraper_mof.py"
        Args   = @("--force")
    },

    @{
        Name   = "財政部 統計資料庫 ETL（mof_observations）"
        Script = Join-Path $MacroRoot "load_mof.py"
        Args   = @("--data-dir", (Join-Path $MacroRoot "財政部資料庫爬蟲"))
    },

    @{
        Name   = "經濟部統計處 資料庫爬蟲（scraper_moea.py）"
        Script = Join-Path $MacroRoot "scraper_moea.py"
        Args   = @("--force")
    },

    @{
        Name   = "經濟部統計處 資料庫 ETL（moea_observations）"
        Script = Join-Path $MacroRoot "load_moea.py"
        Args   = @("--data-dir", (Join-Path $MacroRoot "經濟部工業局資料庫爬蟲"))
    },

    @{
        Name   = "TWSE ISIN 證券清單爬蟲（股票/ETF/基金/指數/興櫃）"
        Script = Join-Path $ProjectRoot "scripts\scrape_isin_lists.py"
        Args   = @("--output-dir", (Join-Path $ProjectRoot "Variable_setting"))
    }

    # 未來其他「每月」來源請加在陣列末尾
)

Invoke-EtlTaskSequence -Title "月頻率 ETL" -Tasks $monthlyTasks
