# 財經數據分析平台

以 Flask + Plotly.js 建立的互動式台灣股市監控平台，支援大盤概況、國際股市比較、個股深度監控，並提供事件研究 CSV 自動產生功能。

---

## 快速操作指南（CMD）

於專案根目錄開啟命令提示字元（CMD）或 PowerShell（路徑請依你本機調整）。各腳本完整參數、產出檔案路徑與建議執行順序見 **`CLI_COMMANDS.md`** 與下方「命令列與腳本」。

**進入專案目錄**

```bash
cd 財經數據分析平台
```

**啟動網站（Flask）**

```bash
python app.py
```

**`scripts/`：資料處理與報告**

- `python scripts/consolidate_report_a_data.py` — 從 TEJ 股價統合報告 a 所需欄位 → `All_Data/事件資料/報告a_來源資料統合.csv`
- `python scripts/generate_report_a.py` — 產生研究報告 a（HTML 與相關 JSON／CSV）；有統合檔時預設優先讀取
- `python scripts/generate_report_a.py --from-source` — 同上，**強制**自 TEJ 原始 CSV 讀取（不使用統合檔）
- `python scripts/generate_event_csv.py` — 事件標記寬表 → `All_Data/事件資料/事件研究彙整.csv`
- `python scripts/generate_factor_returns_csv.py` — 因子報酬 → `All_Data/事件資料/因子報酬.csv`
- `python scripts/generate_factor_chars_loadings_csv.py` — 因子特徵與載荷 → `All_Data/事件資料/因子特徵與載荷.csv`（**須先**有 `因子報酬.csv`）

**`private/`：輔助／開發**

- `python private/generate_stats.py` — 私下統計報告 → `private/stats_report.html`
- `python private/_placeholder_template.py` — 一次性產生九份研究報告**佔位** HTML（**會覆寫** `private/report_a.html` … `report_i.html`；正式內容請勿隨意執行）

**其他**

- 啟動 `app.py` 或於網頁成功載入大盤統計 CSV 後，會自動覆寫 `All_Data/日資料/大盤統計/合併廣度_上市櫃興櫃.csv`（非獨立 CLI）。
- `data_service.py` 供程式 **import**，非命令列工具。

---

## 專案結構

```
財經數據分析平台/
├── app.py                  # Flask 主應用（路由 + API）
├── data_service.py         # 資料讀取與查詢函式
├── scripts/
│   ├── generate_event_csv.py           # 事件研究 CSV 產生腳本
│   ├── consolidate_report_a_data.py    # 報告 a 來源資料統合腳本
│   ├── generate_report_a.py            # 議題 a 振幅分析報告產生器
│   ├── generate_factor_returns_csv.py  # A. 因子報酬 CSV
│   └── generate_factor_chars_loadings_csv.py  # B+C. 因子特徵與載荷 CSV
├── templates/
│   └── index.html          # 主頁面模板
├── static/
│   ├── css/style.css       # 全站暗色主題樣式
│   └── js/charts.js        # 前端互動與 Plotly 圖表邏輯
├── All_Data/               # 資料來源目錄
│   ├── tej欄位說明.md      # TEJ 各 CSV 資料夾 ↔ PostgreSQL `raw.*` 欄位對照（詳細）
│   ├── 日資料/
│   │   ├── TEJ 股價資料庫/   # 個股日頻股價（主要資料來源）
│   │   ├── TEJ 籌碼資料庫/   # 個股日頻籌碼（法人買賣超、融資券）
│   │   ├── 大盤統計/
│   │   │   ├── 大盤統計資訊/        # TEJ 大盤統計原始 CSV（唯讀；程式不寫回）
│   │   │   └── 合併廣度_上市櫃興櫃.csv  # 衍生：年月日＋市場廣度震盪指標＋N日滾動標準差（載入大盤時自動更新）
│   │   ├── 國際股價指數/      # 國際指數
│   │   └── 國內銀行利率(日)_國內銀行匯率/  # 匯率
│   ├── 月資料/
│   │   └── 董監全體持股狀況/  # 董監持股月資料
│   ├── 季資料/
│   │   └── 以合併為主簡表(單季)-全產業/  # 季財務報表
│   └── 事件資料/
│       ├── 事件研究彙整.csv           # 自動產生（由腳本建立）
│       ├── 因子報酬.csv               # A. 因子報酬（由 generate_factor_returns_csv 建立）
│       ├── 因子特徵與載荷.csv         # B+C. 因子特徵與載荷（由 generate_factor_chars_loadings 建立）
│       └── 報告a_來源資料統合.csv      # 報告 a 統合資料（由腳本建立，可加速報告產生）
├── etl/                    # PostgreSQL ETL 模組（資料入庫工具）
│   ├── schema_wantgoo.sql  # 玩股網月營收表（亦可由 load 腳本自動建立）
│   ├── schema_full.sql  # 完整 raw/meta/wantgoo schema 初始化腳本
│   ├── migrate_wantgoo_to_month.sql  # 舊欄 year_month / date → month（手動備用）
│   ├── load_tej.py         # TEJ CSV → PostgreSQL（支援 --table / --all）
│   ├── load_crawler_fx.py  # Investing.com 匯率 CSV → PostgreSQL
│   ├── load_wantgoo_monthly_revenue.py  # 玩股網月營收 CSV → PostgreSQL
│   └── README.md           # ETL 模組詳細說明文件
├── scheduler/              # Windows 排程：日頻率／月頻率兩條管線（爬蟲 + ETL）
│   ├── _pipeline_common.ps1      # 日／月腳本共用的日誌與 Run-Task 邏輯
│   ├── run_daily_crawl_etl.ps1    # 日頻率（預設 investing.com 匯率 + 入庫；可擴充）
│   ├── run_monthly_crawl_etl.ps1  # 月頻率（預設玩股網月營收 + 入庫；可擴充）
│   ├── daily_etl.ps1       # 相容轉送：等同執行 run_daily_crawl_etl.ps1
│   ├── register_task.ps1   # 以系統管理員註冊「工作排程器」工作
│   └── logs/               # 排程執行記錄（daily_etl_*.log / monthly_etl_*.log）
├── Variable_setting/
│   ├── 類股清單.csv           # 產業/主題分類
│   ├── 股票市場別.csv         # （可選，若存在）四位代碼之上市/上櫃分類（`GET /api/market-institutional-flow` 全市場分拆用）
│   └── 上市櫃股票清單.csv     # 上市櫃股票基本資料
├── PLATFORM_SPEC.md        # 完整功能規格書（開發參考）
├── REPORT_A_FORMAT.md      # 報告 a 格式參照（撰寫 b～i 報告時對照）
├── CLI_COMMANDS.md         # 命令列：scripts / private / 網站啟動指令與產出檔說明
└── README.md               # 本文件
```

---

## ETL 模組（PostgreSQL 資料入庫）

`etl/` 資料夾提供完整的 PostgreSQL Schema 設計與 ETL 腳本，支援 TEJ 批次 CSV、Investing.com 匯率爬蟲，以及**玩股網月營收**爬蟲 CSV 的入庫作業。

### Windows 自動排程（`scheduler/`：日／月兩檔）

1. 設定使用者環境變數 `DATABASE_URL`（或編輯 `register_task.ps1` 內連線字串後執行）。
2. 以**系統管理員**開啟 PowerShell，執行：  
   `powershell -ExecutionPolicy Bypass -File scheduler\register_task.ps1`  
   會註冊**兩個**工作（舊版單一 `FinPlatform_DailyETL` 會先刪除）：  
   - **`FinPlatform_DailyFx`**：每日 **18:00** → `run_daily_crawl_etl.ps1`（預設：`investing.com爬蟲` 匯率爬蟲 + `etl\load_crawler_fx.py`）  
   - **`FinPlatform_MonthlyWantgoo`**：每月 **15 日 15:00** → `run_monthly_crawl_etl.ps1`（預設：`玩股網爬蟲` 月營收 + `etl\load_wantgoo_monthly_revenue.py`；月排程以 `schtasks` 建立，相容無 `New-ScheduledTaskTrigger -Monthly` 的 PowerShell）
3. **試跑月營收（不要全清單）**：編輯 `scheduler\run_monthly_crawl_etl.ps1`，將 **`$WantgooStockLimit`** 改為例如 **`"10"`**；正式每月排程請改回 **`"0"`** 再存檔。
4. **擴充其他資料來源**：在 `run_daily_crawl_etl.ps1` 的 **`$dailyTasks`** 或 `run_monthly_crawl_etl.ps1` 的 **`$monthlyTasks`** 陣列**末端**依序加入任務區塊（`Name` / `Script` / `Args` / 可選 `EnvVars`）；共用執行邏輯見 `_pipeline_common.ps1`。日／月管線亦可分別從 `investing.com爬蟲\run_scheduled_daily.ps1`、`玩股網爬蟲\run_scheduled_monthly.ps1` 轉送執行（等同上述兩檔）。
5. 月營收爬蟲需 `玩股網爬蟲\Variable_setting\上市櫃股票清單.csv` 與 Playwright；單次最長 **8 小時**（`register_task.ps1` 內 `$settings`）。
6. 排程會即時把輸出寫入 `scheduler\logs\daily_etl_*.log` 或 `monthly_etl_*.log`；月營收耗時長時可開**工作管理員**看 `python.exe`／Chromium。
7. 手動觸發：  
   `Start-ScheduledTask -TaskName 'FinPlatform_DailyFx'`  
   `Start-ScheduledTask -TaskName 'FinPlatform_MonthlyWantgoo'`（或 `schtasks /Run /TN FinPlatform_MonthlyWantgoo`）  
   或直接：  
   `powershell -NoProfile -ExecutionPolicy Bypass -File ".\scheduler\run_daily_crawl_etl.ps1"`  
   `powershell -NoProfile -ExecutionPolicy Bypass -File ".\scheduler\run_monthly_crawl_etl.ps1"`  
   （舊指令 `daily_etl.ps1` 僅轉送日頻率管線。）記錄檔在 `scheduler\logs\`。

### 快速啟動

```bash
# 1. 設定連線字串（PowerShell）
$env:DATABASE_URL = "postgresql://finuser:finpass@localhost:5432/findb"

# 2. 啟動 Docker PostgreSQL
docker run -d --name findb -e POSTGRES_USER=finuser -e POSTGRES_PASSWORD=finpass `
  -e POSTGRES_DB=findb -p 5432:5432 -v findb_data:/var/lib/postgresql/data postgres:15

# 3. 初始化 Schema（首次執行）
# 注意：本專案目前包含 etl/schema_full.sql（完整 raw/meta/wantgoo schema 初始化），亦保留 etl/schema_wantgoo.sql 供參考。
psql $env:DATABASE_URL -f etl/schema_full.sql

# 4. 匯入全部 TEJ 資料
python etl/load_tej.py --all

# 5. 匯入匯率資料
python etl/load_crawler_fx.py

# 6.（選）玩股網月營收 CSV 入庫（排程會寫入固定檔名後由此載入）
python etl/load_wantgoo_monthly_revenue.py
```

### 資料表架構（raw schema）

| 資料表 | 主鍵 | 欄位策略 |
|--------|------|---------|
| `raw.tej_stock_price` | security_code + trade_date | 29 欄顯式定義 |
| `raw.tej_chip` | security_code + trade_date | 24 主要欄位 + extras JSONB |
| `raw.tej_market_stats` | security_code + trade_date | 23 欄顯式定義 |
| `raw.tej_intl_index` | security_code + trade_date | 3 欄顯式定義 |
| `raw.tej_director_monthly` | security_code + year_month | 月底 DATE |
| `raw.tej_quarterly` | security_code + year_month | JSONB（200+ 財務欄位） |
| `raw.fx_crawler` | currency + date | 外幣/USD 計價，含 change_pct |
| `raw.wantgoo_monthly_revenue` | security_code + **month** | 當月營收（仟元）；`"month"` 為該月一號（`yyyy-mm-dd`）；查詢時欄名建議加雙引號 |
| `meta.security_master` | security_code | 自動由 TEJ ETL 維護 |

> 詳細說明、Docker 指令、匯率換算公式與進階查詢範例請見 **`etl/README.md`**。

---

## 命令列與腳本

各 `scripts/`、`private/` 腳本與根目錄 `app.py` 的啟動方式、產出檔案與建議順序，請見 **`CLI_COMMANDS.md`**。

---

## 功能說明

### 首頁圖表版面（大盤／國際／個股）

**大盤監控區最上方**為「**類股表現（類股清單）**」：左為最新交易日之**平均漲幅前八大類股**橫條圖；右為**累積報酬率％折線**（與下方勾選聯動）；其下為**三大法人**三張折線（外資／投信／自營，億元，同勾選聯動）與加總摘要表，再下為月頻本益比／淨值比。時間篩選器**下方**的大盤統計圖、國際股市兩張主圖、以及個股查詢後的統計圖，皆使用 **兩欄網格**：每列最多兩張圖並排。若該區圖表數為**奇數**，**最後一張**單獨佔滿整列（全寬）。**大盤監控區**之「合併廣度滾動標準差／每日振幅大個股比例」以 `.amp-vol-two-col` **左右並列**（窄螢幕改上下堆疊）；「市場廣度與漲跌幅分布」以 `.section-breadth-panel`、`.breadth-distribution-row` 佔滿整列。約 **1100px** 以下視窗改為單欄直向堆疊。樣式類別：`static/css/style.css` 的 `.charts-grid-2col`、`.amp-vol-two-col`、`.breadth-distribution-row`、個股區 `#stock-charts-grid`。

### 1. 大盤監控區

- **類股表現（類股清單）**（版面最上方）  
  - **介面**：區塊標題下不再顯示長篇操作說明；圖表區已加大——容器 `min-height` 為橫條／累積報酬 **460px**、本益比／淨值比 **400px**、三大法人單圖 **300px**（`.chart-sector-inst-line`，三欄並排窄螢幕改直向）（`static/css/style.css`）；Plotly 高度由 `static/js/charts.js` 對應調整。  
  - **資料來源**：`Variable_setting/類股清單.csv`（第一列為各類股名稱，每欄向下為該類成分；儲存格以字串中最後一組連續四位數為證券代碼，與 TEJ「四位數＋名稱」列比對）。  
  - **左圖（橫條）**：僅顯示 TEJ **最新交易日**、且該類在清單內可對應到股價資料之成分 **≥3 檔** 的類股中，依「**市值前 5 檔**（若該類超過 5 檔；否則用全部成分）之 `報酬率％` **平均**」排序後，**平均漲幅最高**的 **8** 個類股。橫條長度為該類上述有效成分之 **`市值比重％` 加總**（TEJ 欄位，代表佔全市場市值之比重加總）。圖右附註當日平均報酬率％（紅漲綠跌）。  
  - **右圖（折線）**：時間範圍與本區「日期篩選器」相同；顯示為**複利累積報酬率％**（由每日 `報酬率％` 依序換算，缺值日不參與複利）。**預設不勾選任何類股或比較個股**，圖表區僅留白（座標軸與標題）。勾選類股後可**展開成分**調整納入平均的個股（成分預設仍為與橫條規則一致：市值前 5 檔／未滿 5 檔則全選，待勾選該類股後才生效）；另可輸入四位代碼加入**比較個股**。
  - **三大法人**（累積報酬與本益比／淨值比之間）：與**累積報酬折線相同勾選**（類股平均＋比較個股）。將 **TEJ 籌碼**與**股價**對齊後，以「收盤價×買賣超(張)×1000」估算億元；**類股**為成分當日金額之簡單平均，**個股**為單一標的。並排**三張折線圖**：外資、投信、自營（各圖可含多條序列）。未勾選類股／個股時僅顯示提示。
  - **本益比／淨值比（三大法人下方）**：與上列**相同勾選**聯動；以 **TEJ** 欄位 `本益比-TSE`、`股價淨值比-TSE`（讀取各股**當月最後交易日**列；本益比／淨值比僅納入 &gt;0 者）對類股做**簡單平均**得到**月頻**序列。左欄為本益比圖、右欄為淨值比圖，**僅單一左軸（倍）**，不疊收盤價。背景五色帶為**第一條序列**（`series[0]`：勾選順序最先者）在圖間內之 10/30/50/70/90% 分位（資料點不足則不畫帶）。圖下表格為各標的之**最近有值月份**、**月增**、**年增**（與去年同月比）。  
  - **快取**：首次進入大盤區會載入類股 bootstrap；僅變更日期時只重算折線、不重抓整包 bootstrap。按下「↺ 重新載入」會清空快取並重讀 CSV。  
  - **後端**：`load_sector_classification`、`get_sector_performance_bootstrap`、`get_sector_performance_lines`、`get_sector_institutional_lines`（另保留 `get_market_institutional_flow` 供 `GET /api/market-institutional-flow`）；路由見下表。

- **合併廣度滾動標準差／每日振幅大個股比例（同一列）**：左為 σ<sub>t</sub> = std(過去 **N** 日合併廣度 **B**)，**B** =（上漲−下跌）÷ 總家數 ×100；**N** = `data_service.UNIFIED_BREADTH_STD_WINDOW`（預設 **10** 交易日；前 **N−1** 日為 null）。與日期篩選區間一致。右為當日振幅大事件個股佔全體比例（%）；需先產生報告 a。
- **市場廣度與漲跌幅分布（同一版面）**：
  - **市場廣度震盪指標**：**不區分**上市／上櫃／興櫃，將同日各市場的「上漲／下跌／持平家數」加總後計算（上漲 − 下跌）÷ 總家數 × 100；柱狀圖正值著紅、負值著綠（台股慣例）。
  - **漲跌幅區間家數**：以 **TEJ 股價資料庫**「最新交易日」、證券代碼為四位數之普通股列計 `報酬率％`，分桶為漲停、>5%、2～5%、0～2%（漲）、平盤、0～2%（跌）、2～5%（跌）、>5%（跌）、跌停；**漲跌停**優先讀欄位「漲跌停」，若無該欄則以 **±9.49%** 近似漲跌停。圖下方附**上漲／平盤／下跌**三色比例條。
- **日期篩選器**：預設近1年，支援近3月、近6月、自訂日期（影響廣度時序與左欄圖表、**類股表現累積報酬折線**、**三大法人**、**本益比／淨值比月頻**；**漲跌幅區間家數**與**類股橫條圖**僅顯示股價庫最新日，與篩選區間無關）。

> **註**：先前實作之「特徵溢酬監控」已自前端與 API **整組移除**；若改做與公開說明書／指數編製相關之功能，將另訂規格後實作。

> **已自首頁移除之前端區塊**（後端 API 仍保留，供腳本或其他工具使用）：`/api/gauge`（今日成交量位階）、`/api/capital-flow`（資金流向堆疊面積圖）。大盤監控區已不顯示「委買／委賣力道比」「成交金額趨勢」圖表；`GET /api/timeseries` 回應中各市場物件仍含 `委買委賣比`、`成交金額` 與其 MA／百分位欄位，供外部程式沿用。

### 2. 國際股市區

- **指數走勢圖（原始數值）**：主軸 / 副軸雙 Y 軸，支援自訂軸範圍與刻度。
- **累積報酬率圖（台幣計價）**：可拆解指數報酬 + 匯率貢獻。
- **指數選擇器**：搜尋、分組（台灣/亞洲/歐洲/美洲/MSCI），主副軸分配，互斥選取。
- **自訂基準日**：任意設定指數化報酬的起始基準日。
- **指數分組設定**（`data_service.py`）：清單分組以 `_intl_group()` 為底，再以 `_intl_group_refined(code, name)` 校正。台灣 OTC／櫃買相關**名稱**會優先於 `OC72` 判斷（避免與道瓊等同代碼時誤入美洲）；其餘含臺/台、連字號變體仍由 `_intl_name_compact` 輔助比對。美國紐約道瓊 → **美洲**；MSCI 美國房地產信託等 → **MSCI**。
- **折線預設色**（`charts.js` `INTL_SEQ_COLORS`）：依**勾選順序** — 第 1 水藍 `#6ec8ff`、第 2 土黃 `#c9a227`、第 3 紅 `#f85149`、第 4 綠 `#3fb950`、第 5 紫 `#8E44AD`；第六條起再循環。清除某軸勾選後會從順序中移除該代碼。單指數匯率拆解圖仍保留匯率線之獨立色。

### 3. 個股監控

- **查詢與初始化**：`charts.js` 於首頁 `init()` 即綁定查詢／Enter 等事件（`bindStockEventsOnce()`），不必等切換至個股頁籤。點「查詢」會先 `await initStockTab()`：向 `/api/stock/meta` 載入 TEJ 股價與季資料（**首次可能需數十秒**），成功後才設定日期區間並呼叫 `/api/stock/series` 等 API。若併發觸發（同時切換頁籤與查詢），以單一 `_stockTabInitPromise` 合併請求，避免重複載入。
- **代碼輸入**：支援輸入一或多個代碼（逗號分隔），如 `2330, 2303, 2317`。
- **時間範圍**：預設近1年，支援近3月、近6月、自訂。
- **多股顯示模式**：
  - *疊加比較*：所有股票指數化報酬（=100）疊於同一圖。
  - *各自子圖*：各股指數化報酬（=100）分開顯示（已無獨立收盤價圖）。
- **統計圖版面**：四張圖（累積報酬、振幅、法人買賣超、估值）以 **CSS Grid 兩欄並排**；窄螢幕改單欄。若未來擴充為**單數**張圖，最後一張會自動隱藏以免單格佔版。
- **圖表內容**：
  1. **累積報酬率比較**（疊加或子圖）+ 可選季財務指標（副軸，僅疊加模式；淡色點線）
  2. **振幅走勢**（高低價差%）+ 20日滾動均值 + 董監持股%（月頻，副軸）：左軸為日頻波動、右軸為月頻籌碼；若振幅線僅出現在部分年份，請對照該期間 TEJ **高低價差%** 是否缺值。
  3. **法人買賣超**（外資 / 投信 / 自營）
  4. **估值指標**（本益比 / 股淨比 / 殖利率）：左軸倍數、右軸殖利率%；三條序列固定為**實線**、線寬約 1.8px，配色與全站時序圖 **INTL_SEQ_COLORS** 之前三序一致——本益比水藍 `#6ec8ff`、股淨比土黃 `#c9a227`、殖利率紅 `#f85149`（不依個股 `stockColor` 染色，避免單檔時三線同色）。多檔比較時同指標共用同色，請以圖例代碼區分。
- **事件標記**：注意（A）、處置（D）、全額交割（Y）之彩色圓點繪於 **累積報酬率圖**（Y 為指數化報酬），與事件研究 CSV 一致。
- **季資料疊加**：從下拉選單選取季財務指標（如 EPS、ROE、毛利率等），疊加至 **累積報酬圖**右側副軸（僅疊加模式）。
- **資料摘要表**：最新日頻 / 月頻 / 季頻資料並列顯示；含「振幅大後高持續性機率」P(高持續性|振幅大事件)，由報告 a 產生時寫出。

### 4. 研究報告 ▾（下拉選單）

導覽列右側提供私人研究報告連結（RMarkdown 輸出 HTML），按主題分組：

| 類別 | 報告 |
|------|------|
| 技術面 | a. 振幅分析、b. 指數穩定/連續上漲、c. 缺口開盤、h. 連板研究 |
| 籌碼面 | f. 融資維持率、g. 借券賣超、i. 法人買賣超 |
| 統計/綜合 | d. 變數統計分布、e. 事件重疊觀察 |

### 5. 議題 a 振幅分析報告 — 計算與解讀

- **累積報酬**：以對數報酬加總法計算，Π(1+r)−1。
- **累積超額報酬**：正確公式 (1+R_s)/(1+R_m)−1，其中 R_s、R_m 為個股與大盤（Y9999）之累積報酬，可避免加總近似法產生不合理數值。
- **解讀指南**：

- 報告頁面頂部提供「**📖 解讀指南**」區塊，依章節說明衡量議題與定義：
  - **1. 振幅大事件**（定義：今日振幅 > 前20日 P90）— 1.1 後續累積報酬、1.2 超額報酬、1.3 持續性積分分析（改為比較 T+20 超額累積報酬）、1.4 注意股分組比較、1.5 財務特徵分組。
  - **2. 振幅小事件**（定義：今日振幅 < 前20日 P10）— 2.1~2.5 對應同上。
  - **持續性分析**：積分 = Σ 異常振幅(T+k)，異常振幅 = 當日振幅÷基準期均值−1；高持續性 = 積分 ≥ P80。1.3／2.3 統計表改為比較超額累積報酬（vs 大盤）。
  - **高 vs 一般持續性**：敘述統計比較 T 日特徵（市值、Beta、注意股占比、事件強度），並以 Mann-Whitney U 檢定 p 值標註顯著性。
  - **高持續性預測：Logistic 迴歸**：因變數為高持續性=1（非報酬）；自變數為 log(1+市值)、CAPM Beta、注意股、事件強度。
  - **3. 市場振幅偏多／偏少**：以振幅大個股比例為主軸擇一呈現；振幅小比例與其互補，統計意義相同。
  - **5. 結論**：綜合整體觀點、高持續性事件解讀（振幅大／小）、市場層級意涵，以及注意股與炒作風險。實際數值以各章節圖表為準。

### 6. 研究報告 PDF 匯出

- 在 **a. 振幅分析** 報告頁面，點擊「**📄 匯出 PDF**」按鈕，可將整份報告（含 Plotly 圖表與解讀指南）匯出為靜態 PDF 檔。
- 需先安裝 Playwright 並下載 Chromium：
  ```bash
  pip install playwright
  playwright install chromium
  ```
- 匯出約需 10–30 秒（依報告內容與圖表數量而定）。

### 7. 事件研究 CSV 自動產生

- 點擊導覽列「**⚡ 更新事件CSV**」按鈕，呼叫後端腳本重新計算並產生 `All_Data/事件資料/事件研究彙整.csv`。
- 也可直接執行：`python scripts/generate_event_csv.py`

### 8. 因子 CSV 產生（A. 因子報酬、B+C. 因子特徵與載荷）

- **A. 因子報酬**（`scripts/generate_factor_returns_csv.py`）  
  輸出 `All_Data/事件資料/因子報酬.csv`，欄位：`年月日, Rm_Rf, SMB, HML, WML_ep, WML_dy, UMD, STR`  
  - Rm_Rf：市場溢酬（加權指數報酬 − 無風險利率），無風險利率取自各家銀行一年定存之日平均  
  - SMB、HML：Fama-French 2×3 投資組合（規模 × 淨值市價比）  
  - WML_ep、WML_dy、UMD、STR：益本比、股利殖利率、動能、短期反轉因子溢酬  

- **B+C. 因子特徵與載荷**（`scripts/generate_factor_chars_loadings_csv.py`）  
  輸出 `All_Data/事件資料/因子特徵與載荷.csv`，欄位：`證券代碼, 年月日, 規模, 淨值市價比, 益本比, 股利殖利率, 動能, 短期反轉, beta_Rm_Rf, beta_SMB, ...`  
  - 因子特徵：每檔個股、每天的特徵值（市值、B/M、E/P、殖利率、動能、短期反轉）  
  - 因子載荷：每檔個股對各因子報酬的 beta（滾動 252 日迴歸），需先執行 A 產生因子報酬  

- **執行順序**：先 `python scripts/generate_factor_returns_csv.py`，再 `python scripts/generate_factor_chars_loadings_csv.py`

### 9. 報告 a 來源資料統合（加速報告產生）

- **目的**：將報告 a 從多個 TEJ 股價 CSV 擷取的變數統合至單一 `All_Data/事件資料/報告a_來源資料統合.csv`，減少報告產生時的 I/O 開銷。
- **效益**：
  - **單檔讀取**：讀取 1 個檔案取代 N 個 TEJ CSV，減少檔案的開啟、合併與編碼轉換。
  - **導入更多時間序列資料時**：新增歷史資料（更多 CSV 或更大檔案）後，報告產生時間成長較緩，因為只需讀取單一統合檔。
- **使用方式**：
  - 在 **a. 振幅分析** 報告頁面點擊「**📦 更新統合資料**」按鈕，或
  - 直接執行：`python scripts/consolidate_report_a_data.py`
- **注意**：更新 TEJ 股價資料後請重新執行統合腳本，報告產生器會優先使用統合檔。若需強制從原始 CSVs 讀取，可執行：`python scripts/generate_report_a.py --from-source`
- **股票持續性機率**：報告 a 產生時會計算並寫出 `All_Data/事件資料/股票持續性機率.csv`，並合併至統合 CSV；個股監控資料摘要會顯示機率與（高持續性次數／振幅大事件次數）。欄位見下段。
- **統合 CSV 與個股監控摘要：關鍵變數說明**（與 TEJ／報告 a 定義一致）：
  - **高低價差%**：日頻；當日 (最高價−最低價)÷昨收×100%，反映**單日價格波動幅度**。個股監控「資料摘要」表與「振幅走勢」圖主軸之**振幅%**即為此欄位之時序。若圖上僅近期有線段、早期為空白，通常為該段期間**欄位缺值**或資料未匯入，非圖表錯誤。
  - **董監持股%（最新月）**：月頻；董監事及經理人持股占發行股數比例。個股監控「振幅走勢」圖以**右軸點線**疊加，與左軸日頻振幅**頻率不同**（月對日），僅供對照長期籌碼結構。
  - **振幅大後高持續性機率**（`stock_persist_prob`）：依報告 a 之**全樣本**振幅大事件定義與持續性積分，對每檔股票在**最後一筆歷史振幅大事件**時，以**該日之前**至少 5 筆振幅大事件估計「過去事件中高持續性所占比例」（無前視偏誤）。**高持續性**＝該事件之持續性積分 ≥ 全樣本振幅大事件積分之 P80。
  - **stock_persist_hi_n／stock_persist_amp_n**：用於計算上述機率之**歷史樣本**內，高持續性事件筆數／該段歷史內振幅大事件總次數（分母 ≥5 才有機率）。摘要表顯示為 `xx.x%（hi/amp）`。

### 10. `generate_report_a.py`（議題 a HTML 報告）重點

- **輸出**：`private/report_a.html`。
- **持續性／事件研究圖表版面**：1.3、2.3 小節中，「積分演化」「累積報酬演化」「累積超額報酬演化」均為 **單一 Plotly 圖表內左右兩子圖**，左為高持續性、右為一般事件（各含中位數連線與 P25～P75 灰階面積），以減少垂直堆疊、避免單一全寬圖過扁佔版。
- **並排子圖樣式**：以 `update_xaxes`／`update_yaxes` 套用至**全部**子圖軸，避免第二子圖仍使用 Plotly 預設而出現粗白格線；左右 Y 軸仍各自自動縮放，以免量級差異大時右側曲線被壓扁。
- **圖例**：P25、P75 僅顯示一次；兩條中位數以「高持續性·中位數」「一般·中位數」區分顏色（橙／灰）。

---

## API 端點

### 大盤 / 國際股市

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/meta` | 大盤資料日期範圍與標的清單 |
| GET | `/api/gauge` | 各市場成交量百分位儀表板資料（首頁已不顯示，仍可供外部呼叫） |
| GET | `/api/timeseries?start=&end=` | 各市場時序資料（漲跌比例、委買賣、分市場廣度等）；另含鍵 `unified_breadth`：`廣度震盪`（B）、`滾動標準差`（過去 N 日 B 之樣本標準差）、`滾動標準差視窗`（預設 10） |
| GET | `/api/change-distribution` | 漲跌幅區間家數（TEJ 股價庫最新交易日）；失敗時 `status: no_data` 與 `message` |
| GET | `/api/sector-performance` | 類股表現 bootstrap：`as_of`、`bars`（前八大類摘要）、`sectors`（各類成分與 `in_default_avg` 標記）、`stock_universe`（比較個股用代碼清單）；失敗時 `status: no_data` |
| POST | `/api/sector-performance/lines` | JSON body：`start`、`end`、`sector_series`、`stock_codes`；回傳 `dates` 與 `series`（**複利累積報酬率％**，由日報酬換算）、`metric`: `cumulative_return_pct` |
| POST | `/api/sector-performance/valuation` | 與 `lines` 相同 body；回傳月頻 `months`、`series`（每條含 `pe`／`pb`）、`pe_bands`／`pb_bands`（分位邊界）、`pe_summary`／`pb_summary`（最近月、月增、年增） |
| POST | `/api/sector-performance/institutional` | 與 `lines` 相同 body；回傳 `dates`、`lines`（每條含 `label`、`foreign_bn`、`trust_bn`、`dealer_bn`、`line` 樣式）、`unit`、`note` |
| GET | `/api/market-institutional-flow?start=&end=` | （選用）全市場／上市／上櫃加總之堆疊柱資料；首頁類股區已改為依勾選之 `POST …/institutional` |
| GET | `/api/capital-flow?start=&end=` | 資金流向（成交金額佔比）（首頁已不顯示） |
| GET | `/api/heatmap` | 市場廣度熱力圖 |
| GET | `/api/market-amp?start=&end=` | 每日振幅大個股比例與 rolling 門檻（%）；資料來自報告 a 產出之 JSON |
| GET | `/api/breadth-amp-correlation?start=&end=&full_sample=&lag_min=&lag_max=` | 合併廣度 **N** 日滾動標準差 σ 與振幅大比例之**皮爾森相關**，滯後 **k** 預設 **−20…+20**（corr(σ_t, P_{t+k})，k 為交易日）；`full_sample=1` 時忽略 `start`／`end`，改用廣度與 `市場振幅比例.json` 之**全部**交集；`lag_min`／`lag_max` 可覆寫滯後範圍（絕對值上限 `BREADTH_AMP_CORR_LAG_ABS_CAP`，預設 60） |
| GET | `/api/intl/indices` | 國際指數清單 |
| GET | `/api/intl/chart-data?codes=&start=&end=&base=` | 國際指數走勢與報酬率 |
| GET | `/api/reload` | 重新載入所有資料快取 |

### 個股監控

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/stock/meta` | 個股清單、季資料欄位清單、日期範圍 |
| GET | `/api/stock/series?codes=&start=&end=` | 個股日頻股價 + 籌碼時序；每檔含 `stock_persist_prob`、`stock_persist_hi_n`、`stock_persist_amp_n`（由 `股票持續性機率.csv`，報告 a 產生後才有；`start`/`end` 無效字串視同未傳） |
| GET | `/api/stock/monthly?codes=` | 個股月頻董監持股資料 |
| GET | `/api/stock/quarterly?codes=&cols=` | 個股季頻財務資料（指定欄位） |

### 研究報告

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/report/generate/<id>` | 觸發指定研究報告腳本重新產生 HTML |
| POST | `/api/report/export-pdf/<id>` | 將指定報告匯出為 PDF 下載（目前支援 a） |

### 事件研究與資料統合

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/event-csv/generate` | 觸發事件研究 CSV 產生腳本 |
| POST | `/api/report-a/consolidate` | 觸發報告 a 來源資料統合腳本 |

### `data_service.py` 大盤相關函式（摘要）

| 函式 | 說明 |
|------|------|
| `load_all_data()` | 讀取並合併 `大盤統計資訊` 目錄下 CSV；成功後呼叫 `export_unified_breadth_csv` 更新衍生檔 |
| `_unified_breadth_daily(df)` | 內部：按日加總上市／上櫃／興櫃家數，算 **B** 與滾動標準差 |
| `export_unified_breadth_csv(df)` | 將上列結果寫入 `UNIFIED_BREADTH_CSV`（UTF-8-BOM） |
| `UNIFIED_BREADTH_CSV` | 預設 `All_Data/日資料/大盤統計/合併廣度_上市櫃興櫃.csv` |
| `get_meta(df)` | 日期範圍、證券代碼清單、顯示標籤 |
| `get_gauge_data(df)` | 各標的成交金額滾動一年百分位與四期比較（首頁未用） |
| `get_timeseries_data(df, start, end)` | 分市場時序；回傳物件含各 `證券代碼` 鍵與 **`unified_breadth`**（全市場加總家數後之廣度震盪） |
| `get_capital_flow_data(df, start, end)` | 成交金額佔比時序（首頁未用） |
| `get_heatmap_data(df)` | 市場廣度熱力圖資料 |
| `_rolling_std_last_n_valid(s, n)` | 內部：最近 n 個**非 NaN** 的 B 之樣本標準差（缺值日不計入） |
| `_compute_unified_breadth_oscillator(filtered)` | 內部：加總家數算 **B**，`滾動標準差` 由 `_rolling_std_last_n_valid` 計算 |
| `UNIFIED_BREADTH_STD_WINDOW` | 合併廣度 **B** 之滾動標準差視窗 **N**（交易日，預設 10） |
| `get_change_distribution_latest(price_df)` | 內部：股價庫最新日之漲跌幅分桶家數與上漲／平／跌合計 |
| `get_market_amp_data(start, end)` | 市場振幅大個股比例（讀 JSON） |
| `get_breadth_sigma_amp_correlation(df, start, end, …)` | 關鍵字參數：`lag_min`／`lag_max`（預設 `BREADTH_AMP_CORR_LAG_DEFAULT_MIN`／`MAX`，即 ±20）、`use_full_sample`（忽略日期篩選）。回傳 `lags`（各滯後之 `pearson_r`、`n`）、`lag_range`、`full_sample`、`date_range` |
| `BREADTH_AMP_CORR_LAG_DEFAULT_MIN`／`MAX` | API 預設滯後區間（交易日，預設 −20、+20） |
| `BREADTH_AMP_CORR_LAG_ABS_CAP` | 查詢參數允許之 \|k\| 上限（預設 60） |

---

## 資料來源格式

**TEJ 原始匯出**之 CSV 均為 **UTF-16 + Tab 分隔**。本平台**不會**將計算結果寫回 `大盤統計資訊/` 內任何原始檔；衍生指標另存新檔（見下）。

### 合併廣度衍生檔 `合併廣度_上市櫃興櫃.csv`

- **是什麼**：由 `大盤統計資訊` 原始 CSV **即時加總**上市／上櫃／興櫃家數後算出兩個指標，**另存**於此檔（不修改原始 TEJ 檔）。
- **路徑**：`All_Data/日資料/大盤統計/合併廣度_上市櫃興櫃.csv`
- **更新時機**：每次執行 `load_all_data()`（含啟動時首次載入、按下「↺ 重新載入」觸發之重讀）。
- **編碼**：UTF-8（含 BOM，方便 Excel 開啟）。
- **欄位（僅三欄）**：
  - `年月日`（YYYYMMDD）
  - `市場廣度震盪指標`：**B** =（合併上漲家數 − 合併下跌家數）÷（上漲+下跌+持平）×100（百分點）
  - `合併廣度_10日滾動標準差`：取**最近 N 個有效**（非空白）的 **B** 計算樣本標準差（N = `UNIFIED_BREADTH_STD_WINDOW`，預設 10）；**B 缺值之日不納入視窗**（略過不計）。欄位名隨 N 變為 `合併廣度_N日滾動標準差`。累積有效 B 未滿 N 個前，儲存格為**空白**屬正常。
- **為何滾動標準差常出現 0**：若連續 10 日的 **B 完全相同**（例如測資每天家數都一樣），標準差定義上為 **0**，不是程式錯誤。實盤資料中 B 會波動，此欄通常為正數。

---

以下為 **TEJ 原始資料夾** 欄位說明（UTF-16 + Tab）。

### TEJ 股價資料庫（日資料）

主要欄位：`證券代碼`, `年月日`, `開盤價(元)`, `最高價(元)`, `最低價(元)`, `收盤價(元)`, `成交量(千股)`, `報酬率％`, `週轉率％`, `市值(百萬元)`, `本益比-TSE`, `股價淨值比-TSE`, `股價營收比-TEJ`, `現金股利率`, `高低價差%`, `超額報酬(日)-大盤`, `CAPM_Beta 一年`, `漲跌停`, `注意股票(A)`, `處置股票(D)`, `全額交割(Y)`

### TEJ 籌碼資料庫（日資料）

主要欄位（`data_service.CHIP_NUMERIC` 會嘗試轉為數值）：**買賣超相關**除 `外資買賣超(張)`、`投信買賣超(張)`、`自營買賣超(張)` 外，尚有 **`合計買賣超(張)`**（通常為三法人合計）；另可含 **`外資買賣超日數`**、**`投信買賣超日數`**、**`自營買賣超日數`**、**`法人買賣超日數`**（連續買賣超日數，非張數）。TEJ 匯出若另有「連續累計買賣超」等欄位，需視實際 CSV 表頭為準（本平台三大法人折線僅使用前三者張數）。其餘常見：`外資總投資股率%`, `投信持股率%`, `合計持股率%`, `融資餘額(張)`, `融券餘額(張)`, `融資維持率`, `借券賣出餘額(張)` 等。

### 董監全體持股狀況（月資料）

主要欄位：`證券代碼`, `年月`, `董監持股%`, `大股東持股(TSE)%`

### 以合併為主簡表（季資料）

包含 200+ 財務指標欄位，含 EPS、ROE、毛利率、營業收入等。

---

## 事件研究 CSV 格式

輸出路徑：`All_Data/事件資料/事件研究彙整.csv`

| 欄位 | 說明 |
|------|------|
| `證券代碼` | 4碼純代碼（如 2330） |
| `年月日` | YYYYMMDD 整數 |
| `注意股票_A` | 1 = 注意股票（A），否則 0 |
| `處置股票_D` | 1 = 處置股票（D），否則 0 |
| `全額交割_Y` | 1 = 全額交割（Y），否則 0 |
| `振幅變大` | 1 = 今日高低價差% > 前20日第90百分位數 |
| `振幅變小` | 1 = 今日高低價差% < 前20日第10百分位數 |

> 僅保留至少一個事件欄位 = 1 的列。

---

## 啟動方式

```bash
cd 財經數據分析平台
pip install -r requirements.txt
python app.py
```

瀏覽器開啟：[http://localhost:5000](http://localhost:5000)

- **PowerShell**：若 `cd ... && python app.py` 報語法錯誤，請改為同一行使用分號：`cd 專案路徑; python app.py`

---

## 除錯與常見問題

### 瀏覽器顯示「無法連上這個網站」／`ERR_CONNECTION_REFUSED`（127.0.0.1:5000）

代表本機**沒有任何程式在監聽 5000 埠**，通常是尚未啟動 Flask。請在專案根目錄執行 `python app.py`，終端機出現 `Running on http://127.0.0.1:5000` 後再重新整理瀏覽器。若關閉該終端機視窗，伺服器會一併停止。

### NumPy 2.x 相容性錯誤

若啟動時出現 `AttributeError: _ARRAY_API not found` 或 `A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x`：

- **解法一**：降級 NumPy（已於 `requirements.txt` 指定 `numpy<2`）
  ```bash
  pip install "numpy<2"
  ```
- **解法二**：升級相依套件以支援 NumPy 2
  ```bash
  pip install --upgrade pandas numexpr bottleneck
  ```

### 資料載入失敗

- 確認 `All_Data/` 下各資料夾內有對應的 CSV 檔案（UTF-16、Tab 分隔）
- 大盤資料：`All_Data/日資料/大盤統計/大盤統計資訊/`
- 國際指數：`All_Data/日資料/國際股價指數/`
- **國際指數 × 匯率分解範例 CSV**：`investing.com爬蟲/example_intl_index_april_fx_decomposition.csv`（以 `build_intl_index_april_decomposition.py` 合併 TEJ 與 `fx_history_combined.csv`，詳見 `investing.com爬蟲/README.md`）
- 匯率：`All_Data/日資料/國內銀行利率(日)_國內銀行匯率/`

### 前端顯示「資料載入失敗」

- 確認後端 `python app.py` 已成功啟動
- 檢查瀏覽器開發者工具（F12）的 Console 與 Network 分頁

### 個股監控按查詢沒有圖表

- **首次 `/api/stock/meta` 較慢**：須待載入完成後才有日期區間與後續查詢；請等全頁 loading 結束再查，或再按一次查詢。
- **代碼須與 TEJ 股價庫一致**：請輸入 4 碼數字代碼（如 `2330`），勿加 `.TW` 等後綴。
- **Network 檢查**：`series` 回傳空物件 `{}` 時代表代碼對不到或區間內無資料；確認 `codes`、`start`、`end` 參數是否合理。

### 漲跌幅區間長條圖顯示「無法載入」

- **須能讀取 TEJ 股價資料庫**：路徑見 `data_service.py` 之 `STOCK_PRICE_DIR`（預設為專案下 `All_Data/日資料/TEJ 股價資料庫`）；目錄內需有 UTF-16 Tab 分隔之 CSV。
- **欄位**：至少需有 `證券代碼`、`年月日`、`報酬率％`；有 `漲跌停` 欄時漲跌停分類較準確。

---

## 待實作 / 未來方向

- **除權息日期篩選**：取得除權息日期 CSV 後，在 RMarkdown 研究報告中排除除權息前後 3 個交易日（參見 `PLATFORM_SPEC.md` 第 9 章）。
- **RMarkdown 研究報告**：9 份議題報告（a–i），詳見 `PLATFORM_SPEC.md` 第 3–4 章。
- **統計分布報告**：`/stats` 路由，由 `private/generate_stats.py` 產生。

---

*最後更新：2026-04-01*
