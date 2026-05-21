# 玩股網月營收爬蟲

依 `Variable_setting/上市櫃股票清單.csv` 中的**代號**欄位，自 [玩股網每月營收](https://www.wantgoo.com/stock/2330/financial-statements/monthly-revenue) 取得歷史資料中的**當月營收**（對應網站 API 欄位 `monthRevenue`，單位為**仟元**）。

---

## 環境需求

- Python 3.10+（建議）
- 依賴套件見 `requirements.txt`

### 安裝步驟

```bash
pip install -r requirements.txt
playwright install chromium
```

第一次使用 Playwright 時必須執行 `playwright install chromium` 以下載 Chromium 瀏覽器核心。

---

## Windows 排程（與資料庫）

專案透過 `scheduler/run_monthly_crawl_etl.ps1` 串接：**玩股網月營收爬蟲**（`--rolling-months`、固定輸出 `output/月營收_scheduled_latest.csv`）→ **`python etl/load_wantgoo_monthly_revenue.py`**。
`register_task.ps1` 會註冊 **`FinPlatform_MonthlyWantgoo`**：每月 **15 日 15:00** 執行（詳見根目錄 **`README.md`**）。匯率仍由 **`FinPlatform_DailyFx`** 每日 18:00 執行 `run_daily_crawl_etl.ps1`。

若要單機模擬排程參數（等同排程中的月營收段）：

```powershell
cd 專案根目錄
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scheduler\run_monthly_crawl_etl.ps1"
```

等同執行：`powershell -NoProfile -ExecutionPolicy Bypass -File ".\玩股網爬蟲\run_scheduled_monthly.ps1"`。

試跑只要部分股票時，請先編輯 `scheduler\run_monthly_crawl_etl.ps1` 內 **`$WantgooStockLimit`**（例如 `"10"`），再執行上列指令。

---

## 快速啟動（雙擊 .bat）

**`run_月營收爬蟲.bat`** — 雙擊即可互動式設定後執行，不需手動輸入命令列：

```
========================================
  玩股網月營收爬蟲 - 互動啟動工具
========================================

起始年月（例如 2024/01，留空=不限）：2024/01
結束年月（例如 2026/03，留空=不限）：2026/03
只爬前 N 支股票（0 或留空=全部）：
接續代號（例如 4147，留空=從頭）：4147
```

| 互動問題 | 說明 |
|---------|------|
| 起始年月 | 只保留此月份（含）以後的資料；留空不限 |
| 結束年月 | 只保留此月份（含）以前的資料；留空不限 |
| 前 N 支  | 僅爬取清單前 N 支（測試用），0 或留空代表全部 |
| 接續代號 | 續爬用：輸入清單裡**最後一檔已跑完**的股票代號，程式自該代號的**下一列**起爬；留空＝從清單第一檔開始 |

---

## 中斷後續爬（關機／關閉視窗）

程式**不會**自動記住進度；關閉視窗後，本次執行即停止。

1. **保留已產生的 CSV**：`output/` 內的檔案是截至目前寫入的結果，請勿刪除（之後可用 Excel 或另寫腳本與續跑檔合併）。
2. **看最後一行進度的代號**：例如 `[1309/1924] 4147 中裕 ...`，請記 **4147**（該列的代號）。續跑時要輸入「**最後一檔已跑完**」的那一個代號，程式會從**下一檔**起爬（不會重爬 4147）。
3. **下次續跑**：使用與上次相同的 `--start-ym` / `--end-ym`，並加上 **`--after-code 4147`**（改成你畫面上最後那檔的代號），輸出為**新檔名**；最後將兩份 CSV 合併即可。`--after-code` 與 **`--offset` 擇一**，不要同時使用。
4. **互動模式**：「接續代號」一題輸入上述代號即可；留空＝從清單第一檔重跑。
5. **關閉方式**：盡量在出現新的一行進度後再關（程式已於每支股票寫入後 `flush` 磁碟）；避免在工作列強制結束程式，除非必要。

命令列續爬範例（請替換日期與代號）：

```bash
python scrape_monthly_revenue.py --start-ym 2024/01 --end-ym 2026/03 --after-code 4147
```

進階：若仍想用「略過清單前 N 列」的方式，可使用 `--offset N`（與 `--after-code` 互斥）。

---

## 主程式：`scrape_monthly_revenue.py`

### 功能說明

1. 讀取股票清單 CSV（**代號**必填；**名稱**選填，會一併寫入輸出）。
2. 依清單順序，對每支股票開啟玩股網「每月營收」頁面，於瀏覽器環境內呼叫官方資料 API `/stock/{代號}/financial-statements/monthly-revenue-data`，解析 JSON。
3. 依 `--start-ym` / `--end-ym` 篩選日期區間後，寫入 CSV。
4. **換股之間**隨機等待 **1～5 秒**，降低對伺服器請求頻率。
5. **User-Agent** 固定為 Chrome 桌面版 UA 字串，並停用 AutomationControlled 旗標，讓爬蟲能繞過玩股網對自動化請求的偵測。

### 命令列參數

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--list` | 股票清單 CSV 路徑 | `Variable_setting/上市櫃股票清單.csv` |
| `-o` / `--output` | 輸出 CSV 完整路徑 | `output/月營收[_區間]_YYYYMMDD_HHMMSS.csv` |
| `--start-ym` | 篩選起始年月（含），格式 `YYYY/MM` | 不限 |
| `--end-ym` | 篩選結束年月（含），格式 `YYYY/MM` | 不限 |
| `--rolling-months` | 排程用：含本月在內共 N 個曆月（不可與 `--start-ym`／`--end-ym` 併用；`-i` 時忽略） | 無 |
| `--limit` | 只處理清單中前 N 支股票（測試用）；`0` 表示全部 | `0` |
| `--after-code` | 續爬：從清單中此代號的**下一列**起爬（依 CSV 列順序）；與 `--offset` 擇一 | 無 |
| `--offset` | 進階：略過清單最前面 N 列；先 offset 再套用 `--limit`；與 `--after-code` 擇一 | `0` |
| `--page-wait-ms` | 個股頁 `load` 之後再等待的毫秒數（讓 cookie／腳本就緒） | `3000` |
| `--headless` / `--no-headless` | 是否無頭模式執行 Chromium | `--headless`（無頭） |

### 輸出 CSV 欄位

| 欄位 | 說明 |
|------|------|
| 代號 | 股票代碼 |
| 名稱 | 來自清單；清單無名稱欄則為空 |
| 年度月份 | 該筆月營收所屬年月（CSV 為 `YYYY/MM`）；入庫後為 `DATE` 欄位 **`"month"`**（該月一號，`yyyy-mm-dd`） |
| 當月營收_仟元 | 整數，與玩股網 API 一致 |

若有指定日期區間，輸出檔名會自動附帶區間標記，例如：
`月營收_202401-202603_20260430_120000.csv`

### 使用範例

```bash
# 依預設清單爬取全部月份，輸出至 output 目錄
python scrape_monthly_revenue.py

# 只取 2024 年 1 月至 2026 年 3 月
python scrape_monthly_revenue.py --start-ym 2024/01 --end-ym 2026/03

# 只測試前 5 支股票
python scrape_monthly_revenue.py --limit 5

# 排程用：近 4 個曆月寫入固定檔（供 etl/load_wantgoo_monthly_revenue.py）
python scrape_monthly_revenue.py --rolling-months 4 -o output/月營收_scheduled_latest.csv --headless

# 從代號 4147 的下一檔起續爬（日期區間須與上次一致）
python scrape_monthly_revenue.py --start-ym 2024/01 --end-ym 2026/03 --after-code 4147

# 進階：從清單第 1310 列起（略過前 1309 列）
python scrape_monthly_revenue.py --start-ym 2024/01 --end-ym 2026/03 --offset 1309

# 有頭模式（除錯用）
python scrape_monthly_revenue.py --no-headless --limit 1
```

---

## 反爬蟲措施說明

本程式採用以下三項措施應對玩股網的自動化偵測，**均為必要**：

| 措施 | 位置 | 原因 |
|------|------|------|
| **自訂 User-Agent** | `browser.new_context(user_agent=...)` | Playwright 的 headless Chromium 預設 UA 包含 `HeadlessChrome` 字樣，許多網站以此判定為機器人；替換為一般桌面 Chrome UA 可避免被識別 |
| **停用 AutomationControlled** | `--disable-blink-features=AutomationControlled` + `navigator.webdriver` 覆寫 | 部分網站的前端 JS 會讀取 `navigator.webdriver`；此旗標為 true 時會直接封鎖 API 請求，玩股網即屬此類（純 `requests` 會收到 HTTP 400） |
| **換股隨機等待 1～5 秒** | `random.uniform(1.0, 5.0)` | 上市櫃逾千支股票，若無等待間隔，短時間內大量請求易觸發速率限制（Rate Limit）或 IP 封鎖 |

> **注意**：本程式中沒有「換貨幣對」邏輯，此功能屬於另一個 `investing.com爬蟲` 模組，兩者的反爬蟲措施不互相影響。

---

## 目錄結構

```
玩股網爬蟲/
├── run_月營收爬蟲.bat          # 雙擊互動啟動（設定日期區間）
├── scrape_monthly_revenue.py   # 爬蟲主程式
├── requirements.txt
├── README.md
├── Variable_setting/
│   └── 上市櫃股票清單.csv      # 代號／名稱來源（爬蟲必需）
└── output/                     # 預設輸出目錄（自動建立）
```

---

## 免責與合規

本工具僅作技術示範與個人研究用途。請遵守玩股網服務條款與 robots／合理使用慣例；大量或商業用途請自行評估並取得授權。
