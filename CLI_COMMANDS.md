# 命令列與啟動指令說明

以下路徑皆以**專案根目錄**（`財經數據分析平台`）為準。請先在終端機（CMD 或 PowerShell）執行：

```bash
cd 財經數據分析平台
```

再執行下方各指令。

---

## 大盤合併廣度 CSV（非手動腳本）

啟動 `app.py` 或於網頁按「↺ 重新載入」並成功讀取 `All_Data/日資料/大盤統計/大盤統計資訊/*.csv` 後，會自動覆寫：

| 產出 | 說明 |
|------|------|
| `All_Data/日資料/大盤統計/合併廣度_上市櫃興櫃.csv` | 僅含：年月日、`市場廣度震盪指標`、`合併廣度_N日滾動標準差`（`export_unified_breadth_csv`） |

---

## 一、`scripts/`：資料處理與報告產生

| 指令 | 功能摘要 | 主要產出檔案 |
|------|----------|----------------|
| `python scripts/consolidate_report_a_data.py` | 從 `All_Data/日資料/TEJ 股價資料庫/*.csv` 讀取報告 a 所需欄位，寫成單一統合檔，減少後續 I/O。 | `All_Data/事件資料/報告a_來源資料統合.csv` |
| `python scripts/generate_report_a.py` | 產生**研究報告 a**（振幅大／小事件、持續性、市場振幅等完整 HTML）。預設若存在統合檔則優先讀取；若無則改讀 TEJ 多檔。 | 見下方「報告 a 附帶產出」 |
| `python scripts/generate_report_a.py --from-source` | 同上，但**強制**從 TEJ 原始 CSV 讀取，不使用 `報告a_來源資料統合.csv`（即使該檔存在）。 | 同上 |
| `python scripts/generate_event_csv.py` | 掃描 TEJ 股價，標記注意／處置／全額交割、振幅變大／變小等事件，輸出寬表。 | `All_Data/事件資料/事件研究彙整.csv` |
| `python scripts/generate_factor_returns_csv.py` | 依 Fama-French 風格與多因子定義計算日頻因子報酬（需股價與國內銀行利率等資料）。 | `All_Data/事件資料/因子報酬.csv` |
| `python scripts/generate_factor_chars_loadings_csv.py` | 產生因子特徵（B）與對因子報酬的滾動 beta 載荷（C）。**須先**有 `因子報酬.csv`。 | `All_Data/事件資料/因子特徵與載荷.csv` |

### 報告 a 附帶產出（`generate_report_a.py`）

| 檔案 | 說明 |
|------|------|
| `private/report_a.html` | 研究報告 a 主頁面 |
| `All_Data/事件資料/市場振幅比例.json` | 供大盤監控區使用 |
| `All_Data/事件資料/股票持續性機率.csv` | 供個股監控資料摘要使用 |
| `報告a_來源資料統合.csv`（若已存在） | 執行完成後可能將持續性機率相關欄位**合併寫回** |

### 建議執行順序（參考）

- **報告 a**：建議先 `consolidate_report_a_data.py`（可選但建議），再 `generate_report_a.py`。
- **因子管線**：先 `generate_factor_returns_csv.py`，再 `generate_factor_chars_loadings_csv.py`。
- **事件彙整**：`generate_event_csv.py` 可獨立執行，與報告 a 無硬性先後。

---

## 二、`private/`：輔助／開發用腳本

| 指令 | 功能摘要 | 主要產出檔案 |
|------|----------|----------------|
| `python private/generate_stats.py` | 私下統計分布報告（匯入 `data_service`），可用瀏覽器開啟產出 HTML。 | `private/stats_report.html` |
| `python private/_placeholder_template.py` | 一次性產生九份研究報告的**佔位** HTML（範本文字）。 | `private/report_a.html` … `private/report_i.html` |

**注意**：`_placeholder_template.py` 會**覆寫**上述 `report_*.html`。若 `report_a.html` 等已是正式產出內容，請勿隨意執行，以免被佔位頁覆蓋。

---

## 三、專案根目錄：網站啟動

| 指令 | 功能摘要 | 說明 |
|------|----------|------|
| `python app.py` | 啟動 **Flask** 網站（圖表、API；部分功能可透過網頁按鈕觸發 `scripts` 內腳本）。 | 不另產生固定報告檔；資料載入與快取在執行緒中進行。實際連線埠與除錯模式依 `app.py` 設定為準。 |

---

## 四、通常不作為 CLI 工具執行的檔案

| 檔案 | 說明 |
|------|------|
| `data_service.py` | 供 `app.py` 及其他模組 **import** 的資料讀取層，非「執行後產一個檔」的獨立 CLI。 |

---

*本文件與專案內腳本同步維護；若指令或產出路徑有變更，請一併更新此檔。*
