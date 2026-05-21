# 個股資料庫

台灣股市資料收集、ETL 入庫與量化分析工具集。資料存於本機 PostgreSQL（Docker），分析結果輸出為 CSV 供 Tableau 使用。

---

## 專案結構

```
個股資料庫/
├── etl/                    # 資料入庫腳本（TEJ、TIP、玩股網、investing.com）
├── scripts/                # 分析腳本（研究報告、事件研究、因子分析）
├── scheduler/              # 自動排程腳本（每日 ETL + GitHub push）
├── TIP台灣指數爬蟲/         # TIP 台灣指數歷史爬蟲
├── investing.com爬蟲/      # 國際匯率爬蟲
├── 玩股網爬蟲/              # 月營收爬蟲
├── 個股儀表板/              # Tableau 個股儀表板相關腳本
├── 指數儀錶板/              # Tableau 指數儀錶板相關腳本
├── Variable_setting/       # 設定檔（股票清單、類股、ETF 等）
├── All_Data/               # 原始資料（本機，不進版本控制）
└── 總指令.txt              # 所有手動執行指令彙整
```

---

## 資料來源

| 來源 | 內容 | 更新頻率 |
|---|---|---|
| TEJ | 股價、籌碼、季報、董監持股、大盤統計、國際指數 | 手動匯入 |
| TIP | 台灣各類指數歷史報酬 | 每日自動 |
| investing.com | 國際匯率 | 每日自動 |
| 玩股網 | 月營收 | 每月自動 |
| ISIN 清單 | 上市櫃、ETF、基金、興櫃、指數清單 | 每月自動 |

---

## 排程

| 任務 | 時間 | Task Scheduler 名稱 |
|---|---|---|
| 每日 ETL（爬蟲 + 入庫） | 每日 18:00 | `Daily_task` |
| 每月 ETL（月營收 + ISIN） | 每月 15 日 15:00 | `Monthly_task` |
| GitHub Push | 每日 21:00 | `股票資料庫_每日GitHub_Push` |

---

## 快速開始

所有手動執行指令（爬蟲、入庫、報告產出、Tableau CSV）詳見 **`總指令.txt`**。

**環境設定**（每次開新終端機執行）
```powershell
$env:DATABASE_URL = "postgresql://postgres:yourpassword@localhost:5432/postgres"
```

**啟動資料庫**（Docker）
```powershell
net stop winnat
docker start findb
net start winnat
```

---

## 環境需求

- Python 3.12
- PostgreSQL（Docker 容器 `findb`）
- Tableau Desktop
- 套件：`pip install -r requirements.txt`
