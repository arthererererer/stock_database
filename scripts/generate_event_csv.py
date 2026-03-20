"""
generate_event_csv.py
產生事件研究彙整 CSV。

事件類型：
  - 注意股票_A  : 注意股票(A) 欄值 = 'A'
  - 處置股票_D  : 處置股票(D) 欄值 = 'D'
  - 全額交割_Y  : 全額交割(Y) 欄值 = 'Y'
  - 振幅變大    : 今日高低價差% > 前 20 交易日 rolling 第 90 百分位數
  - 振幅變小    : 今日高低價差% < 前 20 交易日 rolling 第 10 百分位數

輸出：All_Data/事件資料/事件研究彙整.csv
  - 格式：Wide format（每列一個 股票×日期，至少含一個事件 = 1）
  - 欄位：證券代碼, 年月日, 注意股票_A, 處置股票_D, 全額交割_Y, 振幅變大, 振幅變小
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent.parent
STOCK_PRICE_DIR = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
OUTPUT_DIR      = BASE_DIR / "All_Data" / "事件資料"
OUTPUT_PATH     = OUTPUT_DIR / "事件研究彙整.csv"

# ── 參數 ────────────────────────────────────────────────────────────────────
ROLLING_WINDOW      = 20   # 前 N 個交易日（不含當日）
AMPLITUDE_BIG_PCT   = 0.90
AMPLITUDE_SMALL_PCT = 0.10

# 只保留4碼起頭為數字的個股代碼（排除 SC300, TM100, Y9999 等指數）
_STOCK_CODE_RE = r"^\d{4}"


# ── 資料載入 ─────────────────────────────────────────────────────────────────

def load_price_data() -> pd.DataFrame:
    """讀取 TEJ 股價資料庫，只取計算事件所需欄位。"""
    csv_files = sorted(STOCK_PRICE_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到 CSV：{STOCK_PRICE_DIR}")

    needed = ["證券代碼", "年月日", "高低價差%", "注意股票(A)", "處置股票(D)", "全額交割(Y)"]
    dfs = []
    for f in csv_files:
        try:
            raw = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            # 只保留有的欄位（防止欄位缺失）
            cols = [c for c in needed if c in raw.columns]
            raw = raw[cols].copy()
            raw["_src"] = f.name
            dfs.append(raw)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}", file=sys.stderr)

    if not dfs:
        raise ValueError("所有 CSV 均讀取失敗")

    combined = pd.concat(dfs, ignore_index=True)
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()
    combined["年月日"]   = combined["年月日"].astype(str).str.strip()

    # 去重：保留最新檔案紀錄
    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    # 振幅欄位轉數值
    combined["高低價差%"] = pd.to_numeric(
        combined["高低價差%"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )

    # 日期欄
    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined.sort_values(["證券代碼", "date"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    return combined


# ── 事件計算 ─────────────────────────────────────────────────────────────────

def _extract_code(full: str) -> str:
    """從 '2330 台積電' 取出純代碼 '2330'。"""
    return str(full).strip().split()[0]


def generate_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    對每檔個股計算 rolling 振幅百分位事件，並整合監理事件標記。
    只保留至少有一個事件 = 1 的列。
    """
    # 篩選個股（排除指數）
    is_stock = df["證券代碼"].str.match(_STOCK_CODE_RE, na=False)
    df = df[is_stock].copy()

    print(f"  個股數量：{df['證券代碼'].nunique():,}，紀錄筆數：{len(df):,}")

    results = []

    for full_code, group in df.groupby("證券代碼"):
        g = group.sort_values("date").reset_index(drop=True)
        amp = g["高低價差%"]

        # Rolling 百分位（前 N 日，不含當日）：先 shift(1) 再 rolling
        shifted = amp.shift(1)
        roll_90 = shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(AMPLITUDE_BIG_PCT)
        roll_10 = shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(AMPLITUDE_SMALL_PCT)

        amp_big = ((amp > roll_90) & roll_90.notna()).astype(int)
        amp_sml = ((amp < roll_10) & roll_10.notna()).astype(int)

        # 監理事件
        attn = (g.get("注意股票(A)", pd.Series([""] * len(g))).astype(str).str.strip() == "A").astype(int)
        disp = (g.get("處置股票(D)", pd.Series([""] * len(g))).astype(str).str.strip() == "D").astype(int)
        full_del = (g.get("全額交割(Y)", pd.Series([""] * len(g))).astype(str).str.strip() == "Y").astype(int)

        evt = pd.DataFrame({
            "證券代碼":   _extract_code(full_code),
            "年月日":     g["年月日"].astype(int),
            "注意股票_A": attn.values,
            "處置股票_D": disp.values,
            "全額交割_Y": full_del.values,
            "振幅變大":   amp_big.values,
            "振幅變小":   amp_sml.values,
        })

        # 只保留有事件的列
        has_event = evt[["注意股票_A", "處置股票_D", "全額交割_Y", "振幅變大", "振幅變小"]].sum(axis=1) > 0
        results.append(evt[has_event])

    if not results:
        return pd.DataFrame(columns=["證券代碼", "年月日", "注意股票_A", "處置股票_D", "全額交割_Y", "振幅變大", "振幅變小"])

    output = pd.concat(results, ignore_index=True)
    output.sort_values(["年月日", "證券代碼"], inplace=True)
    output.reset_index(drop=True, inplace=True)
    return output


# ── 主程式 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("事件研究 CSV 產生腳本")
    print("=" * 50)

    print("\n[1/3] 載入股價資料...")
    df = load_price_data()
    print(f"      合計 {len(df):,} 筆")

    print("\n[2/3] 計算事件...")
    events = generate_events(df)

    counts = events[["注意股票_A", "處置股票_D", "全額交割_Y", "振幅變大", "振幅變小"]].sum()
    print(f"      事件筆數彙整：")
    for k, v in counts.items():
        print(f"        {k}: {int(v):,}")
    print(f"      總計含事件列數：{len(events):,}")

    print(f"\n[3/3] 儲存至：{OUTPUT_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print("      完成！")
    print("=" * 50)


if __name__ == "__main__":
    main()
