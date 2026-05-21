# TIP 臺灣指數公司 — 歷史指數 CSV 下載與合併

從 [TIP 各項指數（一次載入全部）](https://taiwanindex.com.tw/indexes?count=-1&page=1) 取得所有指數代碼與名稱後，可下載單一指數歷史 CSV，或以 `--all` 將**全部指數**在指定日期區間內的歷史資料**合併為同一個 CSV**（每列含指數代碼、指數名稱）。

## 快速操作指南（CMD）

於**專案根目錄**開啟命令提示字元（路徑請依你本機調整）。`scrape_tip_history.py` 與 `merge_daily_into_all_history.py` 的完整參數見下方「程式說明」。

### 爬蟲：`scrape_tip_history.py`

**全部指數合併為單一 CSV（慣例主檔名）**

```cmd
python scrape_tip_history.py --all --start 2026/01/01 --end 2026/03/30 -o output\all_history.csv
```

**僅前 N 支指數（測試／縮短執行時間）**  
`--all` 且**未**指定 `-o` 時，預設輸出為 `output\all_indexes_history.csv`（不是 `all_history.csv`）。若要寫入主檔請加上 `-o output\all_history.csv`。

```cmd
python scrape_tip_history.py --all --limit 3 --start 2026/03/20 --end 2026/03/30
python scrape_tip_history.py --all --limit 3 --start 2026/03/20 --end 2026/03/30 -o output\all_history.csv
```

**短區間＋少數指數（例如驗證合併流程前先產小檔）**

```cmd
python scrape_tip_history.py --all --limit 5 --start 2026/04/01 --end 2026/04/03 -o output\daily_test.csv
```

**單一指數**（未指定 `-o` 時預設 `output\<代碼>_history.csv`）

```cmd
python scrape_tip_history.py --code IX0232 --start 2026/03/20 --end 2026/03/30
```

**起訖為「今天」／「昨天」**（與 `--start`／`--end` 同時寫在命令列時，以 `--today`／`--yesterday` 為準；兩者不可併用）

```cmd
python scrape_tip_history.py --all --today -o output\daily_manual.csv
python scrape_tip_history.py --all --limit 5 --yesterday -o output\daily_test.csv
```

### 備份與合併主檔：`merge_daily_into_all_history.py`

將**日排程／手動產生的合併 CSV**併入 `all_history.csv`。合併會**覆寫** `-o` 指定的主檔，建議先備份。  
**日檔路徑為必填**，須與 `python merge_daily_into_all_history.py` 寫在**同一行**（不可只執行 `python merge_daily_into_all_history.py` 而無檔名）。

```cmd
copy output\all_history.csv output\all_history_backup.csv
python merge_daily_into_all_history.py output\daily_schedule_20260331_20260403.csv --dry-run
python merge_daily_into_all_history.py output\daily_schedule_20260331_20260403.csv -o output\all_history.csv
```

- `--dry-run`：只顯示日檔列數、與主檔重疊筆數、合併後總列數，**不寫入**。  
- 省略 `-o` 時預設主檔為 `output\all_history.csv`。  
- 若出現 `Permission denied`，多為 `all_history.csv` 正被其他程式開啟（例如 Excel），關閉後再執行。

### 與排程腳本的關係

每日互動排程成功後會自動合併進 `output\all_history.csv`；若你**手動**產生日檔，再用上列 `merge_daily_into_all_history.py` 即可。詳見下一節。

## 每日下午 6 點排程（互動視窗 + 合併主檔）

**每日 18:00** 由工作排程器啟動 **`run_daily_tip_interactive.ps1`**（PowerShell 視窗，可全螢幕操作）。流程：

1. 詢問**是否執行爬蟲**（Y/N，畫面上為英文 `Run scrape now?`）；選 N 則結束。  
2. 詢問**開始日、結束日**：可輸入 **`YYYY/MM/DD`** 或 **`YYYYMMDD`**（例如 `2026/04/01` 或 `20260401`）。  
3. 執行 `python scrape_tip_history.py --all --start … --end … -o output\daily_schedule_開始_結束.csv`（檔名為兩個日期的 **YYYYMMDD**）。  
4. 爬蟲**成功**後自動執行 `merge_daily_into_all_history.py`，合併進 **`output\all_history.csv`**（失敗則**不**合併）。  
5. 同次執行另寫 **`output\daily_schedule_YYYYMMDD_YYYYMMDD.log`**。

| 檔案 | 說明 |
|------|------|
| `run_daily_tip_interactive.ps1` | 上述互動流程；提示為**英文 ASCII**（避免 Windows PowerShell 5.1 將無 BOM 的 UTF-8 腳本誤判編碼而亂碼）。 |
| `launch_interactive_scrape.cmd` | 雙擊或從 CMD 呼叫，效果等同手動開一次互動爬蟲（不必等到 18:00）。 |
| `register_tip_daily_task.ps1` | **以系統管理員身分**執行一次，註冊 **`TIP-Daily-TIP-History`**：**每日 18:00**、**互動式登入**（`LogonType Interactive`），須**已登入 Windows** 才會跳出視窗。 |
| `run_daily_tip.ps1` | （選用）**無互動**：`--today` 單檔 `daily_YYYYMMDD.csv`，**不含**自動合併；舊版靜音排程若要保留可自行改排程動作指向此檔。 |

**註冊排程（僅需做一次）：** 系統管理員 PowerShell：

```powershell
Set-Location -LiteralPath 'C:\Users\User\Desktop\TIP台灣指數爬蟲\scripts'
.\register_tip_daily_task.ps1
```

**必備條件：** 18:00 觸發時請**保持登入**（勿僅鎖定到無法顯示前景視窗的狀態視環境而定）；排程身分須能執行 `python` 且已安裝 Playwright Chromium。若看不到視窗，請在 `taskschd.msc` 確認工作為「僅在登入時執行」且使用者為你本人。

**注意：** 遠端桌面斷線、切換使用者等可能導致互動工作無法顯示在前景，請依實際環境測試。

### 在 CMD（命令提示字元）中執行

**手動開啟互動爬蟲（與排程相同）：**

```bat
cd /d "C:\Users\User\Desktop\TIP台灣指數爬蟲"
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File "C:\Users\User\Desktop\TIP台灣指數爬蟲\scripts\run_daily_tip_interactive.ps1"
```

或：

```bat
"C:\Users\User\Desktop\TIP台灣指數爬蟲\scripts\launch_interactive_scrape.cmd"
```

**註冊每日 18:00 排程（系統管理員 CMD）：**

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\User\Desktop\TIP台灣指數爬蟲\scripts\register_tip_daily_task.ps1"
```

**靜音當日爬蟲（不自動合併、檔名 `daily_YYYYMMDD.csv`）：**

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\User\Desktop\TIP台灣指數爬蟲\scripts\run_daily_tip.ps1"
```

**查詢排程：**

```bat
schtasks /query /tn "TIP-Daily-TIP-History" /v /fo LIST
```

**直接命令列爬蟲（非互動）：** 與先前相同，例如：

```bat
cd /d "C:\Users\User\Desktop\TIP台灣指數爬蟲"
python scrape_tip_history.py --all --today -o output\daily_manual.csv
```

**手動合併主檔（互動流程已自動合併時可略）：**

```bat
python merge_daily_into_all_history.py output\daily_manual.csv --dry-run
python merge_daily_into_all_history.py output\daily_manual.csv -o output\all_history.csv
```

合併會**覆寫寫入** `output\all_history.csv`（建議先備份）。`run_daily_tip_interactive.ps1` 成功後會自動執行合併，無須再手動打 merge。

**編碼：** `run_daily_tip.ps1` 與 `run_daily_tip_interactive.ps1` 的**提示字串皆為 ASCII**；互動腳本勿改回繁中內嵌字串，否則在繁中 Windows 的 PowerShell 5.1 上易出現**亂碼**並導致看不懂 `Read-Host`、日期未輸入而失敗。

## 環境需求

- Python 3.10+（建議）
- 依賴套件見 `requirements.txt`

### 安裝

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## 程式說明

### `merge_daily_into_all_history.py`

將**單日**合併 CSV 併入 **`all_history.csv`**（標準庫 `csv`，無需額外套件）。

| 參數 | 說明 |
|------|------|
| `daily`（位置參數） | 日檔路徑，例如 `output\daily_20260402.csv` |
| `-o` / `--output` | 主歷史檔路徑，預設 `output\all_history.csv` |
| `--dry-run` | 只印統計（日檔列數、重疊筆數、合併後總列數），**不寫檔** |

合併規則：以 **（指數代碼, 日期）** 為鍵；日檔列覆寫主檔同鍵列；其餘主檔列保留。日期會正規化為 `YYYY/MM/DD` 再比對。

### `scrape_tip_history.py`

結合 **requests**（列表頁、自訂 User-Agent）與 **Playwright**（歷史頁日期與下載）。

| 常數 / 設定 | 說明 |
|-------------|------|
| `BASE` | 官網網址，預設 `https://taiwanindex.com.tw` |
| `INDEX_LIST_URL` | 指數列表頁，預設 `/indexes?count=-1&page=1`（與官網「全部」筆數一致） |
| `USER_AGENT` | 模擬 Chrome 146 on Windows，用於 **requests** 與 **Playwright** |
| `EXCLUDED_INDEX_SLUGS` | 非指數詳情頁的 `/indexes/<slug>`（如 `comparison`、`board`）略過 |
| `DEFAULT_INDEX_NAME` | 單筆模式預設要比對的指數名稱 |
| `BTN_SEARCH` / `BTN_DOWNLOAD` | 「搜尋」「下載」按鈕文字（Unicode 轉義，避免編碼問題） |
| `MERGED_COLUMNS` | `--all` 合併檔的欄位順序：指數代碼、指數名稱、日期、價格指數值、報酬指數值、漲跌點數、漲跌百分比 |

| 函式 | 說明 |
|------|------|
| `session_with_ua()` | 建立帶 `User-Agent`、`Accept`、`Accept-Language` 的 `requests.Session` |
| `_apply_dates_to_history_inputs(page, start_date, end_date)` | 同步日期至前端元件狀態，使 `--start` / `--end` 與官網搜尋一致 |
| `_wait_after_history_search(page)` | 按下「搜尋」後等待 `networkidle`、固定緩衝與 loading 消失，再下載，減少**空檔或尚未套用日期區間**就下載 |
| `_filter_rows_by_query_range(rows, start_date, end_date)` | 依起訖日（ISO 字串比對）過濾官網 CSV 列，避免誤把**整段歷史**寫入僅查單日／短區間的合併檔 |
| `_dismiss_blocking_overlays(page)` | 搜尋後關閉／繞過官網 `alert-drop-shadow`、`alert-container` 等浮層（ESC、關閉 `pointer-events`、點擊內建關閉鈕），避免擋住「下載」 |
| `_register_index(seen, code, name)` | 將代碼與名稱寫入去重字典（略過排除清單） |
| `list_all_indexes()` | GET `INDEX_LIST_URL`，解析 `div.index-box`（長列表）及 `<tr>` 表格列，回傳排序後的 `[(代碼, 名稱), ...]` |
| `resolve_index_code(index_name)` | 在完整列表中以子字串比對指數名稱，回傳代碼 |
| `_download_history_on_page(page, index_code, start_date, end_date, dest)` | 開啟歷史頁；套用日期後按「搜尋」、`_wait_after_history_search`、`_dismiss_blocking_overlays`；**下載**以 `click(force=True)` 觸發 |
| `scrape_history_csv(...)` | **單一指數**：啟動瀏覽器並下載一個官方格式 CSV |
| `_read_official_history_rows(csv_path)` | 讀取官網下載的 CSV（UTF-8 BOM）；表頭鍵名會 `strip`，回傳資料列字典 |
| `scrape_all_merged_csv(...)` | **全部指數**：同一瀏覽器連續處理；下載列經 `_filter_rows_by_query_range` 再寫入；**每支成功後即寫入並 flush** 合併 CSV；**每兩支指數之間**隨機等待 1～5 秒；失敗寫入 `.errors.txt`。執行中可在終端機按 **Ctrl+C** 中斷 |
| `main()` | 命令列進入點 |

### 命令列參數

| 參數 | 說明 |
|------|------|
| `--all` | 抓取列表中的**全部**指數並合併為單一 CSV |
| `--index-name` | 單筆模式：列表上的指數名稱（子字串比對） |
| `--code` | 單筆模式：直接指定代碼（如 `IX0232`） |
| `--start` / `--end` | 起訖日期，格式 `YYYY/MM/DD` |
| `--today` | 將 `--start` 與 `--end` 皆設為**本機今天**；與 `--start` / `--end` 一併寫在命令列時**以此為準**；**不可與 `--yesterday` 併用** |
| `--yesterday` | 將 `--start` 與 `--end` 皆設為**本機昨天**，方便在**當日收盤資料尚未上線**時測試或補資料 |
| `-o` / `--output` | 輸出路徑。單筆預設 `output/<CODE>_history.csv`；`--all` 預設 `output/all_indexes_history.csv` |
| `--headed` | 顯示瀏覽器視窗（除錯） |
| `--limit` | 僅處理前 N 支指數（`0` 表示不限制；可用於測試） |

### 使用範例

**全部指數合併**（程式會在**每兩支指數之間**自動隨機等待 **1～5 秒**）：

```bash
python scrape_tip_history.py --all --start 2026/01/01 --end 2026/03/30 -o output/all_history.csv
```

**只測試前 3 支：**

```bash
python scrape_tip_history.py --all --limit 3 --start 2026/03/20 --end 2026/03/30
```

**單一指數（與先前相同）：**

```bash
python scrape_tip_history.py --code IX0232 --start 2026/03/20 --end 2026/03/30
```

## 前端儀表板（`web/`）

瀏覽器端以 **Plotly.js** 呈現：多指數**淨值折線圖**（基準日歸一為 100）、**風險統計表**、**累積報酬直條圖**（台股慣例：紅漲綠跌、依報酬由高到低排序、X 軸代碼垂直顯示）。資料來源為與爬蟲相同的合併 CSV（欄位：`指數代碼`、`指數名稱`、`日期`、`價格指數值` 等）。

### 檔案

| 檔案 | 說明 |
|------|------|
| `web/index.html` | 頁面：載入 CSV、複選指數、基準日／結束日、直條圖頻率分頁（當日、5／20／60／120 交易日） |
| `web/styles.css` | 深色版面樣式 |
| `web/app.js` | CSV 解析（Papa Parse）、指標計算、繪圖邏輯 |

### 本機預覽（建議）

因瀏覽器對 `file://` 的 `fetch` 有限制，請在**專案根目錄**啟動簡易 HTTP 伺服器後再開頁面：

```bash
python -m http.server 8765
```

瀏覽器開啟：`http://localhost:8765/web/index.html`  
點選 **「載入 output/all_history.csv」** 即可讀取根目錄下的 `output/all_history.csv`；亦可改用 **選擇檔案** 載入任意路徑的合併 CSV。

### 功能與指標定義（摘要）

- **淨值走勢**：自**基準日**（含）起，以該日（或之後首個交易日）**價格指數值**為 100 換算後續淨值；**結束日**可留白，則用到資料內共同範圍。
- **折線顏色**（第 1～5 條）：水藍 `#6ec8ff`、土黃 `#c9a227`、暗紅 `#b01030`、綠 `#3fb950`、紫 `#8E44AD`，之後循環。
- **Beta**：以 CSV 中 **發行量加權股價指數**（代碼 **`t00`**）為市場，與各指數在**共同交易日**的**日報酬**計算樣本共變異／市場變異數。
- **Sortino**：日報酬平均／**下行偏差**（僅負報酬平方平均再開根號）再乘以 **√252**（年化風險調整後之簡化 Sortino；無風險利率假設為 0）。
- **VaR 95%**：**歷史模擬法**，單日報酬分配之 **5% 左尾**對應之損失（以正值顯示）。
- **平均回撤**：自區間起算之累積淨值（由日報酬複利）對**歷史峰值的日回撤**，再取**算術平均**。
- **下行波動率（年化）**：`sqrt(平均( min(0, 日報酬)^2 )) × sqrt(252)`。
- **直條圖**：以所選指數**共同最後交易日**為截止點，回溯 **1、5、20、60、120 個交易日**之**價格累積報酬**；分頁切換時更新圖與下方數值表。主內容寬度與初期相同（**max-width: 1280px**）；繪圖區**加高**約 **min(72vh, 900px)**、min-height **640px**；Y 軸留白與 `cliponaxis: false` 保留，避免柱外百分比被切掉。若歷史長度不足則該檔不顯示於該頻率。

**免責**：網頁統計為教育／分析用途，公式與樣本區間不同時結果會與其他平台不一致；投資決策請自行驗證。

## 輸出 CSV 欄位

- **單筆下載**：與官網相同（`日期`、`價格指數值`、`報酬指數值`、`漲跌點數`、`漲跌百分比`）。
- **`--all` 合併**：上述五欄前加上 **`指數代碼`**、**`指數名稱`**。

若部分指數下載失敗，已成功列仍會留在合併檔中，並另存 `<輸出檔名>.errors.txt` 記錄錯誤。

### 常見失敗原因（`*.errors.txt`）

- **官網提示「查無指數相關歷史資料」**：所選區間內沒有資料（例如部分聯名指數、尚未發布歷史），浮層曾擋住日期欄導致逾時；程式已改以 `fill(..., force=True)` 填日期以降低此情況。
- **沒有兩個日期輸入欄**：多為 **產業類股指數**（代碼常為 `t01`、`t02`…）等頁面與「一般指數」歷史下載介面不同，無法用同一流程自動下載。
- **逾時**：網路慢、伺服器回應久，可改 `--headed` 觀察或稍後重跑失敗代碼。

## 注意事項

- **「今天」可能查無列**：收盤後官網未必立刻更新**當日**指數列；非交易日亦無當日資料。若 `--today` 合併結果為 **+0 列**，可改 **`--yesterday`** 或明確指定 **`--start` / `--end` 為上一交易日** 再測。
- **`--start` / `--end` 與指數基期**：若指數基期（例如 2025 年才發布）晚於 `--start`，官網本來就沒有更早的歷史，CSV 最早列只會從實際有資料的日期起跳，不會出現基期之前的年份。
- CLI 可用 `2023/01/01` 或 `2023-01-01`；程式會轉成官網 flatpickr 使用的 **ISO（連字號）** 並在必要時以鍵盤輸入備援。
- `--all` 指數數量多時執行時間長（已內建每支之間隨機 1～5 秒間隔），請遵守網站使用條款。
- 列表頁版面若改版，`list_all_indexes` 的 `index-box` / 表格解析可能需調整。
- 歷史頁 UI 變更時請以 `--headed` 除錯並更新選擇器。
