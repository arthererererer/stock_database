"""
scripts/consolidate_report_a_data.py
將研究報告 a 所需之變數資料，從多個 TEJ 股價 CSV 統合至單一 CSV。

目的：減少報告產生時的 I/O 開銷（單檔讀取 vs 多檔讀取+合併），
      導入更多時間序列資料時，報告產出時間成長較緩。

執行：python scripts/consolidate_report_a_data.py
輸出：All_Data/事件資料/報告a_來源資料統合.csv

變數來源：All_Data/日資料/TEJ 股價資料庫/*.csv
欄位：證券代碼, 年月日, 高低價差%, 報酬率％, 超額報酬(日)-大盤, 成交量(千股),
      市值(百萬元), 本益比-TSE, 股價淨值比-TSE, 現金股利率, CAPM_Beta 一年,
      注意股票(A), 處置股票(D), 全額交割(Y)
"""

import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
STOCK_PRICE_DIR = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
OUTPUT_DIR = BASE_DIR / "All_Data" / "事件資料"
OUTPUT_PATH = OUTPUT_DIR / "報告a_來源資料統合.csv"

LOAD_COLS = [
    "證券代碼", "年月日",
    "高低價差%", "報酬率％", "超額報酬(日)-大盤", "成交量(千股)",
    "市值(百萬元)", "本益比-TSE", "股價淨值比-TSE", "現金股利率", "CAPM_Beta 一年",
    "注意股票(A)", "處置股票(D)", "全額交割(Y)",
]
NUMERIC_COLS = [
    "高低價差%", "報酬率％", "超額報酬(日)-大盤", "成交量(千股)",
    "市值(百萬元)", "本益比-TSE", "股價淨值比-TSE", "現金股利率", "CAPM_Beta 一年",
]


def consolidate() -> pd.DataFrame:
    """從 TEJ 股價資料庫讀取所有 CSV，統合為單一 DataFrame（已預處理）。"""
    csvs = sorted(STOCK_PRICE_DIR.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"找不到 CSV：{STOCK_PRICE_DIR}")

    dfs = []
    for f in csvs:
        try:
            df = pd.read_csv(
                f, encoding="utf-16", sep="\t", dtype=str,
                usecols=lambda c: c in LOAD_COLS,
            )
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"  跳過 {f.name}: {e}", file=sys.stderr)

    raw = pd.concat(dfs, ignore_index=True)
    raw["證券代碼"] = raw["證券代碼"].astype(str).str.strip()
    raw["年月日"] = raw["年月日"].astype(str).str.strip()
    raw.sort_values("_src", inplace=True)
    raw.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    raw.drop(columns=["_src"], inplace=True)

    for col in NUMERIC_COLS:
        if col in raw.columns:
            raw[col] = pd.to_numeric(
                raw[col].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )

    raw["date"] = pd.to_datetime(raw["年月日"], format="%Y%m%d", errors="coerce")
    raw["stock_code"] = raw["證券代碼"].str.split().str[0]
    raw = raw.dropna(subset=["date"])
    raw.sort_values(["stock_code", "date"], inplace=True)
    raw.reset_index(drop=True, inplace=True)

    return raw


def main():
    print("=" * 55)
    print("報告 a 來源資料統合")
    print("=" * 55)
    print(f"\n來源：{STOCK_PRICE_DIR}")
    print(f"輸出：{OUTPUT_PATH}")

    print("\n[1/2] 載入並統合 CSVs...")
    df = consolidate()
    n_rows = len(df)
    n_codes = df["stock_code"].nunique()
    print(f"      共 {n_rows:,} 筆，{n_codes:,} 個代碼")

    print("\n[2/2] 儲存統合 CSV...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"      完成！檔案大小：{size_kb:.0f} KB")
    print("=" * 55)
    print("\n提示：generate_report_a.py 會優先讀取此統合檔，以加速報告產生。")
    print("      更新 TEJ 資料後請重新執行本腳本。\n")


if __name__ == "__main__":
    main()
