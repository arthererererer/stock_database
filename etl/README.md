# ETL 模組使用說明

財經數據分析平台 — PostgreSQL 資料匯入工具集

---

## 目錄

1. [環境需求](#1-環境需求)
2. [PostgreSQL 連線設定](#2-postgresql-連線設定)
3. [Docker 啟動 PostgreSQL](#3-docker-啟動-postgresql)
4. [初始化 Schema](#4-初始化-schema)
5. [執行 TEJ ETL（load_tej.py）](#5-執行-tej-etlload_tejpy)
6. [執行匯率 ETL（load_crawler_fx.py）](#6-執行匯率-etlload_crawler_fxpy)
6a. [玩股網月營收 ETL（load_wantgoo_monthly_revenue.py）](#6a-玩股網月營收-etlload_wantgoo_monthly_revenuepy)
7. [匯率計價說明](#7-匯率計價說明)
8. [Schema 設計說明](#8-schema-設計說明)
9. [已知注意事項](#9-已知注意事項)

---

## 1. 環境需求

| 項目 | 版本 |
|------|------|
| Python | 3.12+ |
| pandas | 2.0+ |
| psycopg2-binary | 2.9+ |
| PostgreSQL | 15+ |

安裝依賴套件：

```bash
pip install pandas psycopg2-binary
```

> 若已安裝 Anaconda 環境，可改用：
> ```bash
> conda install psycopg2
> pip install psycopg2-binary  # 備用
> ```

---

## 2. PostgreSQL 連線設定

所有 ETL 腳本透過環境變數 `DATABASE_URL` 讀取連線字串，格式如下：

```
postgresql://<使用者>:<密碼>@<主機>:<port>/<資料庫名稱>
```

### Windows PowerShell 設定方式

```powershell
$env:DATABASE_URL = "postgresql://finuser:finpass@localhost:5432/findb"
```

### Windows CMD 設定方式

```cmd
set DATABASE_URL=postgresql://finuser:finpass@localhost:5432/findb
```

### Linux / macOS

```bash
export DATABASE_URL="postgresql://finuser:finpass@localhost:5432/findb"
```

---

## 3. Docker 啟動 PostgreSQL

### 快速啟動（單次執行）

```bash
docker run -d \
  --name findb \
  -e POSTGRES_USER=finuser \
  -e POSTGRES_PASSWORD=finpass \
  -e POSTGRES_DB=findb \
  -p 5432:5432 \
  -v findb_data:/var/lib/postgresql/data \
  postgres:15
```

### Windows PowerShell 版本

```powershell
docker run -d `
  --name findb `
  -e POSTGRES_USER=finuser `
  -e POSTGRES_PASSWORD=finpass `
  -e POSTGRES_DB=findb `
  -p 5432:5432 `
  -v findb_data:/var/lib/postgresql/data `
  postgres:15
```

### 常用管理指令

```bash
# 確認容器狀態
docker ps

# 停止
docker stop findb

# 重新啟動
docker start findb

# 進入 psql shell
docker exec -it findb psql -U finuser -d findb
```

---

## 4. 初始化 Schema

在首次使用前，可執行 `schema_full.sql` 以建立 `raw`、`meta` 以及 `raw.wantgoo_monthly_revenue` 的完整 schema。
本倉庫仍保留 `schema_wantgoo.sql` 作為玩股網月營收表的參考。

### 方法一：透過 psql（推薦）

```bash
psql $DATABASE_URL -f etl/schema_full.sql
```

PowerShell：

```powershell
psql $env:DATABASE_URL -f etl\schema_full.sql
```

### 方法二：透過 Docker exec

```bash
docker exec -i findb psql -U finuser -d findb < etl/schema_wantgoo.sql
```

### 方法三：進入 psql 後貼上 SQL

```bash
docker exec -it findb psql -U finuser -d findb
# 進入後執行：
\i /path/to/etl/schema_wantgoo.sql
```

---

## 5. 執行 TEJ ETL（load_tej.py）

### 腳本位置

```
etl/load_tej.py
```

### 資料來源資料夾對應

| `--table` 參數 | 讀取資料夾 | 資料型態 |
|---------------|-----------|---------|
| `tej_stock_price` | `All_Data/日資料/TEJ 股價資料庫/` | 日 |
| `tej_chip` | `All_Data/日資料/TEJ 籌碼資料庫/` | 日 |
| `tej_market_stats` | `All_Data/日資料/大盤統計/大盤統計資訊/` | 日 |
| `tej_intl_index` | `All_Data/日資料/國際股價指數/` | 日 |
| `tej_director_monthly` | `All_Data/月資料/董監全體持股狀況/` | 月 |
| `tej_quarterly` | `All_Data/季資料/以合併為主簡表(單季)-全產業/` | 季 |

> **注意**：`All_Data/日資料/國內銀行利率(日)_國內銀行匯率/` 資料夾已排除，
> 匯率統一由 `load_crawler_fx.py` 從 Investing.com 爬蟲資料匯入。

### 執行指令

```bash
# 匯入單一資料表
python etl/load_tej.py --table tej_stock_price
python etl/load_tej.py --table tej_chip
python etl/load_tej.py --table tej_market_stats
python etl/load_tej.py --table tej_intl_index
python etl/load_tej.py --table tej_director_monthly
python etl/load_tej.py --table tej_quarterly

# 一次匯入全部資料表（依上述順序逐一執行）
python etl/load_tej.py --all
```

### 參數說明

| 參數 | 說明 |
|------|------|
| `--table <名稱>` | 指定單一資料表（與 `--all` 互斥） |
| `--all` | 依序匯入全部 6 個 TEJ 資料表 |

### 重複執行安全性

使用 `INSERT ... ON CONFLICT DO NOTHING`，同一筆（security_code + date）重複匯入不會報錯，也不會改寫已存在的資料。兩個 ETL 腳本均採此策略，包含 `load_crawler_fx.py`。

### 匯入前自動備份

每次執行 ETL 時，會在 `backup` Schema 自動建立快照，命名規則：

```
backup.<table_name>_YYYYMMDD_HHMMSS
```

例如：`backup.tej_chip_20260430_153000`

若匯入後發現異常，可用下列 SQL 還原：

```sql
TRUNCATE raw.tej_chip;
INSERT INTO raw.tej_chip SELECT * FROM backup.tej_chip_20260430_153000;
```

清理舊備份（視需要執行）：

```sql
DROP TABLE IF EXISTS backup.tej_chip_20260430_153000;
```

### 匯入後日期範圍驗證

每次 ETL 結束後，會自動在 log 輸出：
- 目前資料表總筆數
- 本次新增筆數
- 日期範圍（最早 → 最新）

### 副作用：自動更新 meta.security_master

每次匯入任一 TEJ 資料表後，腳本會自動解析 `證券代碼` 欄位（格式：`"XXXX 名稱"`），並將新發現的證券代碼寫入 `meta.security_master` 對照表。

---

## 6. 執行匯率 ETL（load_crawler_fx.py）

### 腳本位置

```
etl/load_crawler_fx.py
```

### 預設 CSV 路徑

```
investing.com爬蟲/fx_history_combined.csv
```

### 執行指令

```bash
# 使用預設路徑
python etl/load_crawler_fx.py

# 指定自訂路徑
python etl/load_crawler_fx.py --file /path/to/fx_history_combined.csv
```

### 參數說明

| 參數 | 說明 |
|------|------|
| `--file <路徑>` | 指定 fx_history_combined.csv 的路徑（可選） |

### 匯入策略

使用 `INSERT ... ON CONFLICT (currency, date) DO NOTHING`：
- 同一幣種同一日期已存在時略過，不覆蓋已有資料
- 匯入前自動在 `backup.fx_crawler_YYYYMMDD_HHMMSS` 建立快照
- 匯入後自動輸出各幣種筆數與日期範圍至 log

### 執行後輸出範例

```
===========================================================
  匯率匯入統計報表
===========================================================
  總筆數：18,432
  日期範圍：2015-01-02  →  2026-04-25

  幣種      筆數      最早日期      最新日期    JPY 缺值
  -----------------------------------------------------------
  AUD      2048    2015-01-02    2026-04-25          —
  CAD      2048    2015-01-02    2026-04-25          —
  CNY      2048    2015-01-02    2026-04-25          —
  EUR      2048    2015-01-02    2026-04-25          —
  GBP      2048    2015-01-02    2026-04-25          —
  HKD      2048    2015-01-02    2026-04-25          —
  JPY      2048    2015-01-02    2026-04-25         3 筆
  KRW      2048    2015-01-02    2026-04-25          —
  TWD      2048    2015-01-02    2026-04-25          —

  ⚠ JPY 有 3 筆 close 缺值，請以 IS NULL 查詢確認。
===========================================================
```

---

## 6a. 玩股網月營收 ETL（load_wantgoo_monthly_revenue.py）

將 `玩股網爬蟲/scrape_monthly_revenue.py` 產出之 CSV（欄位：`代號`、`名稱`、`年度月份`、`當月營收_仟元`）寫入 **`raw.wantgoo_monthly_revenue`**。主鍵為 `(security_code, "month")`；**`month`** 為月頻時間欄位，型別 `DATE`，存該月一號（`yyyy-mm-dd`）。若主鍵衝突則更新營收與名稱。

- **DDL 參考**：`schema_wantgoo.sql`（執行 load 時亦會 `CREATE TABLE IF NOT EXISTS`，並將舊欄位 `year_month` 或 `"date"` 自動更名為 `month`）
- **僅手動遷移**：舊庫可執行 `migrate_wantgoo_to_month.sql`
- **預設檔案路徑**：`玩股網爬蟲/output/月營收_scheduled_latest.csv`（與排程 `scheduler/run_monthly_crawl_etl.ps1` 寫入路徑一致）

### 命令列

```bash
# 使用預設 CSV 路徑
python etl/load_wantgoo_monthly_revenue.py

# 指定檔案
python etl/load_wantgoo_monthly_revenue.py --file "玩股網爬蟲/output/月營收_202401-202603_20260502_120000.csv"
```

須設定環境變數 `DATABASE_URL`。

---

## 7. 匯率計價說明

### 計價基準：外幣/USD

`raw.fx_crawler` 的匯率欄位（`close`、`open`、`high`、`low`）均以  
**「1 單位外幣可換多少 USD」** 為計價基準。

| currency | close  | 意義 |
|----------|--------|------|
| AUD      | 0.6672 | 1 AUD = 0.6672 USD |
| JPY      | 0.0068 | 1 JPY = 0.0068 USD |
| TWD      | 0.0307 | 1 TWD = 0.0307 USD |

### TWD 對其他外幣交叉匯率

TWD 幣種資料作為橋接，可換算任意外幣對台幣的匯率：

$$
\text{TWD/外幣} = \frac{\text{TWD close}}{\text{外幣 close}}
$$

**範例**：TWD/JPY（1 JPY 可換多少 TWD）

```sql
SELECT
    t.date,
    t.close AS twd_usd,
    j.close AS jpy_usd,
    ROUND(t.close / j.close, 4) AS twd_per_jpy   -- 1 JPY = ? TWD
FROM raw.fx_crawler t
JOIN raw.fx_crawler j ON j.currency = 'JPY' AND j.date = t.date
WHERE t.currency = 'TWD'
ORDER BY t.date DESC
LIMIT 10;
```

### 使用內建 View

Schema 已提供 `raw.v_fx_twd_cross` 交叉匯率 View，可直接查詢：

```sql
-- 查詢所有幣種最新交叉匯率
SELECT currency, date, twd_per_foreign
FROM raw.v_fx_twd_cross
WHERE date = (SELECT MAX(date) FROM raw.fx_crawler);
```

---

## 8. Schema 設計說明

### 資料表清單

| 資料表 | Schema | 主鍵 | 備註 |
|--------|--------|------|------|
| `tej_stock_price` | raw | security_code + trade_date | 29 個欄位，全部顯式定義 |
| `tej_chip` | raw | security_code + trade_date | 31 個主要欄位 + extras JSONB |
| `tej_market_stats` | raw | security_code + trade_date | 23 個欄位 |
| `tej_intl_index` | raw | security_code + trade_date | 3 個欄位 |
| `tej_director_monthly` | raw | security_code + year_month | 月底 DATE |
| `tej_quarterly` | raw | security_code + year_month | JSONB 儲存 200+ 財務欄位 |
| `fx_crawler` | raw | currency + date | 含 change_pct 清洗後數值 |
| `wantgoo_monthly_revenue` | raw | security_code + **month** | 玩股網月營收（仟元）；見 `schema_wantgoo.sql`、`migrate_wantgoo_to_month.sql` |
| `security_master` | meta | security_code | 自動由 TEJ ETL 維護 |

### tej_quarterly 採用 JSONB 的理由

1. **欄位數達 200+**：逐一建立欄位成本高，且欄位名含複雜中文及特殊符號，SQL 使用需加引號
2. **稀疏性高**：各產業/公司申報科目不同，正規化方案會產生大量 NULL
3. **無縫擴展**：會計準則更新（如 IFRS 修訂）新增科目時，不需 ALTER TABLE
4. **查詢支援**：GIN 索引支援 JSONB 全文搜尋，常用指標可建 Materialized View 提升效能

### tej_chip extras JSONB

籌碼資料庫欄位分為三層處理：

| 層級 | 欄位數 | 說明 |
|------|--------|------|
| 主要欄位（顯式） | 31 | 直接對應資料庫具名欄位，支援 SQL 直接查詢與索引 |
| extras JSONB | 其餘 | 連續累計買賣超、單邊買賣張數、市值版本等備用欄位 |
| 忽略（不寫入） | 7 | 與 `tej_stock_price` 重複的股價/基本面欄位，完全略過 |

**忽略的欄位**（`CHIP_IGNORE_COLS`）：`當日收盤`、`未調整收盤價(元)`、`流通在外股數(千股)`、`外資/投信/自營/合計買賣超(千股)`

**新增正式欄位**（相較舊版從 extras 升級）：

| CSV 欄位名 | 資料庫欄位名 | 意義 |
|---|---|---|
| 融券買進(張) | `short_buy_lot` | 空單回補張數 |
| 融券維持率 | `short_maint_ratio` | 融券維持率（有別於融資維持率） |
| 整戶維持率 | `overall_maint_ratio` | 信用帳戶整體維持率 |
| 融資限額 | `margin_limit_lot` | 融資額度上限 |
| 融券限額 | `short_limit_lot` | 融券額度上限 |
| 融券(買+賣)/成交量 % | `short_vol_ratio_pct` | 融券活躍度指標 |
| 融資(買+賣)/成交量 % | `margin_vol_ratio_pct` | 融資活躍度指標 |

### 日期儲存規則

| 頻率 | 原始格式 | 轉換方式 | 範例 |
|------|---------|---------|------|
| 日資料 | YYYYMMDD 字串 | → DATE | `20260315` → `2026-03-15` |
| 月/季資料 | YYYYMM 字串 | → 月底 DATE | `202603` → `2026-03-31` |

---

## 9. 已知注意事項

### JPY 缺值問題

JPY 因假日與各市場差異，偶有數日缺值。匯入後可執行以下 SQL 確認：

```sql
SELECT date, close
FROM raw.fx_crawler
WHERE currency = 'JPY' AND close IS NULL
ORDER BY date;
```

如需前後插值補全，可使用：

```sql
-- 以最近一筆有效值前向填補（參考用，實際補值依業務需求）
SELECT
    currency,
    date,
    close,
    LAST_VALUE(close) IGNORE NULLS OVER (
        PARTITION BY currency ORDER BY date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS close_filled
FROM raw.fx_crawler
WHERE currency = 'JPY';
```

> PostgreSQL 不支援 `IGNORE NULLS`，可改用 `FILTER` 子查詢或 Python 前處理。

### 季財報欄位數量

`tej_quarterly.data` JSONB 欄位包含 200+ 中文財務科目。常用指標查詢範例：

```sql
-- 查詢特定公司 EPS（每股盈餘）
SELECT
    security_code,
    year_month,
    (data->>'每股盈餘')::NUMERIC AS eps
FROM raw.tej_quarterly
WHERE security_code LIKE '2330%'
ORDER BY year_month DESC;

-- 建立常用財務比率的 Materialized View（建議在分析層建立）
CREATE MATERIALIZED VIEW analytics.quarterly_kpi AS
SELECT
    security_code,
    year_month,
    (data->>'每股盈餘')::NUMERIC          AS eps,
    (data->>'ROE(A)－稅後')::NUMERIC      AS roe,
    (data->>'ROA(A)稅後息前')::NUMERIC    AS roa,
    (data->>'營業毛利率')::NUMERIC        AS gross_margin,
    (data->>'稅後淨利率')::NUMERIC        AS net_margin,
    (data->>'負債比率')::NUMERIC          AS debt_ratio
FROM raw.tej_quarterly;
```

### 證券代碼格式

TEJ 所有資料表的 `security_code` 欄位保留「`XXXX 名稱`」完整格式（代碼空格名稱），
查詢時請用 `LIKE` 或 `security_master` 做關聯：

```sql
-- 精確查詢台積電
SELECT * FROM raw.tej_stock_price
WHERE security_code LIKE '2330%'
ORDER BY trade_date DESC LIMIT 10;

-- 透過 meta 表查詢
SELECT s.*, m.market
FROM raw.tej_stock_price s
JOIN meta.security_master m USING (security_code)
WHERE m.ticker = '2330';
```

### 國際股價指數 security_code 較長

`tej_intl_index` 的 security_code 可能含有較長的英文索引名稱（如 `SPX 標普500指數`），
欄位已設計為 `VARCHAR(50)` 以容納。

---

## 附錄：快速執行清單

```bash
# 1. 設定連線字串
export DATABASE_URL="postgresql://finuser:finpass@localhost:5432/findb"

# 2. 啟動 Docker PostgreSQL
docker start findb  # 若已建立；或用 docker run（見第 3 節）

# 3. 初始化 Schema（首次執行）
# 注意：本倉庫目前包含 etl/schema_full.sql（完整 raw/meta/wantgoo schema 初始化）。
psql $DATABASE_URL -f etl/schema_full.sql

# 4. 匯入所有 TEJ 資料
python etl/load_tej.py --all

# 5. 匯入匯率資料
python etl/load_crawler_fx.py

# 6. 驗證資料筆數
psql $DATABASE_URL -c "
SELECT schemaname, tablename, n_live_tup AS rows
FROM pg_stat_user_tables
WHERE schemaname IN ('raw','meta')
ORDER BY schemaname, tablename;
"
```
