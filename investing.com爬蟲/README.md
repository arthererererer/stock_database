# 匯率歷史資料爬蟲與分析工具

使用 Playwright 自動化瀏覽器，從 hk.investing.com 爬取多幣種兌美元（USD）的歷史匯率資料，合併輸出為 CSV，並進一步計算「區間漲跌幅」與「基準日起累積漲跌幅」兩份分析報表。

## 快速使用

雙擊 `匯率爬蟲與分析.bat`，填入日期後點擊「執行」即可。

### Windows 自動排程（每日 18:00）

專案根目錄註冊之 **`FinPlatform_DailyFx`** 會執行 `scheduler\run_daily_crawl_etl.ps1`（內含本資料夾之 `scrape_fx_history.py` 與 `etl\load_crawler_fx.py`）。亦可於本資料夾執行 **`run_scheduled_daily.ps1`** 轉送同一管線（需已設定 `DATABASE_URL`）。詳見根目錄 **`README.md`**。

## 安裝依賴

```bash
pip install playwright pandas beautifulsoup4
python -m playwright install chromium
```

---

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `匯率爬蟲與分析.bat` | 雙擊啟動圖形介面 |
| `run_fx_scraper_gui.ps1` | PowerShell 圖形介面主程式 |
| `run_scheduled_daily.ps1` | 轉送 `scheduler\run_daily_crawl_etl.ps1`（排程／手動測試用） |
| `compute_fx_returns.py` | 根據 CSV 計算兩份分析報表 |
| `build_intl_index_april_decomposition.py` | 合併 TEJ 國際指數與本目錄匯率 CSV，產生「本幣指數／貨幣／美元重編」累積漲跌幅之日序列範例 |
| `fx_history_combined.csv` | 爬蟲輸出：原始匯率歷史資料 |
| `example_intl_index_april_fx_decomposition.csv` | 範例輸出：指數×匯率分解（預設對應 --year 2025 --month 4） |

---

## 圖形介面（run_fx_scraper_gui.ps1）

### 輸入欄位

| 欄位 | 說明 | 格式 |
|------|------|------|
| 起始日（基準日） | 資料起始日，同時作為累積漲跌幅的基準點 | YYYYMMDD |
| 結束日 | 資料結束日 | YYYYMMDD |
| 區間漲跌幅 CSV 檔名 | 輸出檔案名稱，預設 fx_period_returns.csv | |
| 累積漲跌幅 CSV 檔名 | 輸出檔案名稱，預設 fx_cumulative_returns.csv | |

### 選項

- **僅重新計算分析，不重新爬蟲**：若 `fx_history_combined.csv` 已存在且包含所需期間，可勾選此項跳過爬蟲，直接重算兩份分析 CSV。

### 執行流程

1. 驗證輸入日期格式與順序
2. （若未勾選略過）啟動 Playwright 瀏覽器執行爬蟲
3. 爬蟲完成後自動執行分析計算
4. 完成後彈出成功訊息

### 錯誤提示

- 日期格式錯誤 → 提示正確格式
- 日期超出資料範圍 → 提示可用日期區間，要求調整或重新爬蟲
- 找不到 python / 指令碼 → 提示安裝方式

---

## 輸出資料

### fx_history_combined.csv（原始資料）

| 欄位 | 說明 |
|------|------|
| currency | 幣種代號（大寫），如 AUD、KRW |
| date | 日期（YYYY-MM-DD） |
| close | 收市價 |
| open | 開市價 |
| high | 當日最高 |
| low | 當日最低 |
| change% | 單日漲跌百分比 |

### fx_period_returns.csv（區間漲跌幅）

每種貨幣一列，記錄整段區間的累積漲跌幅。

| 欄位 | 說明 |
|------|------|
| 貨幣代碼 | 幣種代號 |
| 起始日 | 區間第一個交易日（YYYYMMDD） |
| 結束日 | 區間最後一個交易日（YYYYMMDD） |
| 區間累積漲跌幅(%) | (結束收盤 / 起始收盤 − 1) × 100 |

### fx_cumulative_returns.csv（基準日起累積漲跌幅）

每種貨幣 × 區間內每個交易日各一列，以起始日為基準逐日計算累積漲跌幅。

| 欄位 | 說明 |
|------|------|
| 貨幣代碼 | 幣種代號 |
| 基準日 | 區間起始日（YYYYMMDD） |
| 區間結束日 | 各交易日日期（YYYYMMDD） |
| 累積漲跌幅(%) | (當日收盤 / 基準日收盤 − 1) × 100 |

---

## 命令列使用方式

### 爬蟲（scrape_fx_history.py）

```bash
# 預設（2026-01-01 至今日）
python scrape_fx_history.py

# 指定日期（YYYYMMDD 或 YYYY-MM-DD 均可）
python scrape_fx_history.py --start-date 20260101 --end-date 20260410

# 指定輸出路徑
python scrape_fx_history.py --start-date 20260101 --end-date 20260410 --output my_fx.csv
```

### 分析（compute_fx_returns.py）

```bash
python compute_fx_returns.py --start-date 20260101 --end-date 20260410

# 自訂輸出檔名
python compute_fx_returns.py \
  --start-date 20260101 --end-date 20260410 \
  --period-output 區間漲跌幅.csv \
  --cumulative-output 累積漲跌幅.csv
```

若指定日期不在 `fx_history_combined.csv` 的範圍內，程式會顯示可用範圍並以 exit code 2 結束。

---

## 國際指數 × 匯率累積漲跌幅（範例）

`build_intl_index_april_decomposition.py` 讀取專案內 `All_Data/日資料/國際股價指數` 之 TEJ 匯出檔，與本資料夾之 `fx_history_combined.csv`（`close` 解讀為與爬蟲頁面相同之美元報價；用於兩日相除之累積報酬時，與常見的「每 1 日圓／每 100 日圓」等顯示方式在比例上自洽），合併產生**月內每一交易日**之累積變化。

```bash
python build_intl_index_april_decomposition.py --year 2025 --month 4
python build_intl_index_april_decomposition.py --tej "C:/path/20260315114403.csv" --fx "fx_history_combined.csv" -o my_out.csv
```

### 範例輸出欄位（`example_intl_index_april_fx_decomposition.csv`）

| 欄位 | 說明 |
|------|------|
| 日期 | 指數之交易日（ISO 日期） |
| 市場 | 市場名稱（如台灣、美國） |
| 代表指數_證券代碼列 | 與 TEJ「證券代碼」欄完全一致之代表大盤識別 |
| 報價幣別 | 指數計價幣別；東協、印度等若無單一兌美元序列則不填匯率欄 |
| 指數收盤_本幣 | 當日指數水準（本幣） |
| 匯率_USD每1單位本幣 | 來自爬蟲 `close`（若該日無資料則往前找最近一個交易日） |
| 累積漲跌幅_指數本幣_pct | 自該月第一個**該指數有資料之交易日**起算之本幣累積報酬 |
| 累積漲跌幅_兌USD貨幣_pct | 同樣基準日起算之「持有該幣兌美元」累積報酬 |
| 累積漲跌幅_美元重編近似_pct | \((S_t F_t)/(S_0 F_0)-1\)：將本幣指數水準依當日兌美元匯率換算後之累積漲跌幅（美國 S&P 僅有前兩欄與本欄同義；本幣欄以 0% 之美元為基準） |
| 累積漲跌幅_交互項_rS_rF_pct | **\(r_S\cdot r_F\)** 對應之百分點：精確滿足「美元重編 − 指數本幣 − 貨幣」；等同 \((1+r_S)(1+r_F)-1\) 減去線性項（以小數計 \(r_S=r_{eq}/100\)、\(r_F=r_{fx}/100\)）後再換算為百分點 |

**限制**：匯率爬蟲之 `CURRENCIES` 不含 **INR**；**韓元**：若 `krw-usd` 頁面回傳空表，則 `fx_history_combined.csv` **沒有 KRW 列**，合併後韓國列會出現「貨幣／美元重編／交互項」空白——這是**檔案缺資料**，不是公式否定「韓元兌美元存在」。可先另爬 **usd-krw** 並換算為「1 KRW = 多少 USD」後併入 CSV，或改用其它來源之 KRW/USD。**MSCI 東協 LOCAL**、**INR** 亦無單一合適之配對匯率時，上列欄位會留白。

### 分類指數之計價幣別（判讀要點）

| 分類 | 幣別／單位 |
|------|------------|
| 名稱含 **Local** 之 MSCI 區域指數 | 成分在地貨幣綜合之「本幣指數點」；與單一現匯交叉時僅近似 |
| 名稱含 **USD／EUR** 之 MSCI | 依名稱分別為 **美元**／**歐元** 計價 |
| 美國 S&P、道瓊、Nasdaq、Russell、VIX、費城半導體、MSCI 美國 REIT 等 | **美元**（指數點） |
| 加拿大 TSX REIT | **加元** |
| 各國官方大盤（英國富時、恆生、日經、DAX 等） | 該市場掛牌**當地幣** |
| **美元指數**、**泰德價差** | 前者為指數點；後者為利差類指標（非股票報酬） |

---

## 程式架構

### scrape_fx_history.py

#### 全域設定

- `CURRENCIES`：爬取的幣種清單（預設 9 個：KRW / EUR / JPY / GBP / AUD / CAD / HKD / CNY / TWD）
- `START_DATE`：起始日（由命令列參數或預設值 2026-01-01 決定）
- `END_DATE`：結束日（由命令列參數或預設今日決定）
- `OUTPUT_FILE`：輸出路徑（預設與程式同目錄）

#### 主要函數

- `_normalise_date(s)`：將 YYYYMMDD 轉為 YYYY-MM-DD
- `_parse_args()`：解析命令列參數（--start-date / --end-date / --output）
- `human_delay(lo, hi)`：隨機等待，模擬人類操作避免觸發速率限制
- `dismiss_popups(page)`：關閉 Cookie 同意、廣告、登入彈窗
- `set_date_range(page) -> bool`：設定日期選擇器（三層備用策略），回傳是否成功
- `_find_hist_table(soup)`：從 HTML 找到歷史數據表格（四層優先順序）
- `parse_table(page) -> DataFrame`：解析表格並轉換日期與數值格式
- `scrape_one(page, currency) -> DataFrame`：爬取單一幣種
- `main()`：啟動 Chromium；**每個幣種**建立新的 `BrowserContext` 與 `Page`，爬完後關閉 Context（清除 Cookie／儲存，降低 investing.com 連續請求觸發反爬蟲的機率），再合併輸出 CSV

### compute_fx_returns.py

- `normalise_date(s)`：日期格式統一（YYYYMMDD → YYYY-MM-DD）
- `yyyymmdd(dt)`：Timestamp → YYYYMMDD 字串
- `main()`：讀取 CSV → 驗證日期範圍 → 計算兩份報表 → 輸出

---

## 注意事項

1. 需要圖形介面環境（Playwright 使用非 headless 模式避免反爬蟲）
2. 9 個幣種全部爬完約需 10～20 分鐘（每幣種重建 Context 後可能略增）
3. 需要穩定的網路連線至 hk.investing.com
4. 若 `fx_history_combined.csv` 中已包含所需期間，可勾選「僅重新計算分析」節省時間
