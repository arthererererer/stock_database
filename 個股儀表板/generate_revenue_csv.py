"""
generate_revenue_csv.py
從 PostgreSQL raw.wantgoo_monthly_revenue 生成 Tableau 月營收分析 CSV

三種模式與對應 Tableau 圖表：
  single  — 單一個股複合圖（月營收長條 + YoY 折線）
  multi   — 多檔 YoY 年增率折線比較（或指數化折線）
  sector  — 類股堆疊長條 + 整體 YoY 折線

用法：
  python generate_revenue_csv.py --mode single --codes 2330
  python generate_revenue_csv.py --mode multi  --codes 2330 2454 2303
  python generate_revenue_csv.py --mode sector --sector 上市半導體
  python generate_revenue_csv.py --mode sector --sector 上市半導體 --months 60

環境變數：
  DATABASE_URL   e.g. postgresql://user:pass@localhost:5432/dbname

輸出至本檔所在目錄（個股儀表板/）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg2

BASE_DIR = Path(__file__).resolve().parent
SECTOR_CSV = BASE_DIR.parent / "Variable_setting" / "類股清單.csv"


# ── 1. 類股清單解析 ──────────────────────────────────────────────────────────

def parse_sector_map(csv_path: Path) -> dict[str, list[str]]:
    """
    解析 類股清單.csv → {類股名稱: [股票代號, ...]}

    CSV 格式：
      第 1 列（row 0）：類股名稱，逗號分隔
      第 2 列起：各欄對應類股的成分股，格式為「名稱+代號」
                 e.g. 台積電2330、矽力*-KY6415

    解析邏輯：
      對每個儲存格以 regex r'(\\d{4,6})(?:[A-Z])?$' 擷取末尾數字代號
    """
    df = pd.read_csv(csv_path, header=None, dtype=str)
    sector_names = [str(s).strip() for s in df.iloc[0]]
    sector_map: dict[str, list[str]] = {}

    for col_idx, sector in enumerate(sector_names):
        if not sector or sector == "nan":
            continue
        codes: list[str] = []
        for row_idx in range(1, len(df)):
            cell = str(df.iloc[row_idx, col_idx]).strip()
            if not cell or cell == "nan":
                continue
            m = re.search(r"(\d{4,6})(?:[A-Z])?$", cell)
            if m:
                codes.append(m.group(1))
        if codes:
            sector_map[sector] = list(dict.fromkeys(codes))  # 去重保序

    return sector_map


# ── 2. 資料庫查詢 ────────────────────────────────────────────────────────────

def fetch_revenue(
    conn: psycopg2.extensions.connection,
    security_codes: list[str],
    output_months: int,
) -> pd.DataFrame:
    """
    查詢 raw.wantgoo_monthly_revenue。

    多取 13 個月供 YoY / MoM / YTD YoY 計算使用（這些資料不計入最終輸出，
    在 main() 中過濾）。
    """
    placeholders = ",".join(["%s"] * len(security_codes))
    sql = f"""
        SELECT
            security_code,
            security_name,
            "month",
            revenue_ntd_thousand
        FROM raw.wantgoo_monthly_revenue
        WHERE security_code IN ({placeholders})
          AND "month" >= (
              date_trunc('month', CURRENT_DATE)
              - INTERVAL '{output_months + 13} months'
          )::date
        ORDER BY security_code, "month"
    """
    df = pd.read_sql(sql, conn, params=security_codes)
    df["month"] = pd.to_datetime(df["month"])
    return df


# ── 3. 衍生欄位計算 ──────────────────────────────────────────────────────────

def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """
    計算所有衍生欄位。不做日期過濾（由 main() 負責）。

    ① revenue_ntd_billion（億元）
        = revenue_ntd_thousand ÷ 100,000

    ② yoy_growth_pct（月營收年增率 %）
        = (當月 revenue_ntd_thousand ÷ 去年同月 revenue_ntd_thousand − 1) × 100
        做法：以 pandas Period(M) 為 key，將 Period + 12 join 自身，
              取前一年同月值；若無資料則 NaN

    ③ mom_growth_pct（月增率 %）
        = (當月 revenue_ntd_thousand ÷ 前一個月 revenue_ntd_thousand − 1) × 100
        做法：Period + 1 join 自身

    ④ ytd_revenue_ntd_billion（當年累計營收 億元）
        = 同 security_code、同年 1 月至當月的 revenue_ntd_thousand 累計加總 ÷ 100,000
        做法：pandas groupby(security_code, year).cumsum()

    ⑤ ytd_yoy_growth_pct（累計年增率 %）
        = (今年累計 ÷ 去年同期累計 − 1) × 100
        「去年同期」= 去年 1 月至去年與當月相同月份數字的累計
        做法：對 ytd_revenue 以 Period + 12 join 自身

    ⑥ revenue_indexed（指數化，各股以資料集中最早月份 = 100）
        = (當月 revenue_ntd_thousand ÷ 該股資料集最早月份 revenue_ntd_thousand) × 100
        做法：groupby("security_code").transform("first")
    """
    df = df.sort_values(["security_code", "month"]).reset_index(drop=True)
    df["_ym"] = df["month"].dt.to_period("M")

    # ① 億元
    df["revenue_ntd_billion"] = (df["revenue_ntd_thousand"] / 100_000).round(2)

    # ② YoY — Period+12 self-join
    prev12 = df[["security_code", "_ym", "revenue_ntd_thousand"]].copy()
    prev12["_ym"] = prev12["_ym"] + 12
    prev12 = prev12.rename(columns={"revenue_ntd_thousand": "_rev12"})
    df = df.merge(prev12, on=["security_code", "_ym"], how="left")
    df["yoy_growth_pct"] = (
        (df["revenue_ntd_thousand"] / df["_rev12"] - 1) * 100
    ).round(2)
    df.drop(columns=["_rev12"], inplace=True)

    # ③ MoM — Period+1 self-join
    prev1 = df[["security_code", "_ym", "revenue_ntd_thousand"]].copy()
    prev1["_ym"] = prev1["_ym"] + 1
    prev1 = prev1.rename(columns={"revenue_ntd_thousand": "_rev1"})
    df = df.merge(prev1, on=["security_code", "_ym"], how="left")
    df["mom_growth_pct"] = (
        (df["revenue_ntd_thousand"] / df["_rev1"] - 1) * 100
    ).round(2)
    df.drop(columns=["_rev1"], inplace=True)

    # ④ YTD — cumsum within (security_code, year)
    df["_yr"] = df["month"].dt.year
    df = df.sort_values(["security_code", "month"])
    df["_ytd_rev"] = (
        df.groupby(["security_code", "_yr"])["revenue_ntd_thousand"].cumsum()
    )
    df["ytd_revenue_ntd_billion"] = (df["_ytd_rev"] / 100_000).round(2)

    # ⑤ YTD YoY — Period+12 self-join on ytd values
    ytd_lookup = df[["security_code", "_ym", "_ytd_rev"]].copy()
    ytd_lookup["_ym"] = ytd_lookup["_ym"] + 12
    ytd_lookup = ytd_lookup.rename(columns={"_ytd_rev": "_ytd12"})
    df = df.merge(ytd_lookup, on=["security_code", "_ym"], how="left")
    df["ytd_yoy_growth_pct"] = (
        (df["_ytd_rev"] / df["_ytd12"] - 1) * 100
    ).round(2)
    df.drop(columns=["_yr", "_ytd_rev", "_ytd12"], inplace=True)

    # ⑥ Indexed — 各股以資料集最早月份為基準 100
    first_rev = df.groupby("security_code")["revenue_ntd_thousand"].transform("first")
    df["revenue_indexed"] = (df["revenue_ntd_thousand"] / first_rev * 100).round(2)

    return df


# ── 4. 類股欄位 ──────────────────────────────────────────────────────────────

def add_sector_columns(df: pd.DataFrame, sector_name: str) -> pd.DataFrame:
    """
    加入類股彙總欄位（在 compute_derived 之後、月份過濾之前呼叫）。

    ⑦ sector_name — 類股名稱（直接帶入參數）

    ⑧ sector_total_revenue_billion（類股合計月營收 億元）
        = 同月所有成分股 revenue_ntd_billion 加總
        groupby("month").sum()

    ⑨ revenue_share_pct（個股占類股比重 %）
        = 個股 revenue_ntd_billion ÷ sector_total_revenue_billion × 100

    ⑩ sector_yoy_growth_pct（類股整體年增率 %）
        = (本月 sector_total ÷ 去年同月 sector_total − 1) × 100
        做法：對 sector_total 以 Period+12 join 自身（同 YoY 邏輯）
    """
    df = df.copy()
    df["sector_name"] = sector_name

    # ⑧ 同月類股加總
    sec_mo = (
        df.groupby("month")["revenue_ntd_billion"]
        .sum()
        .reset_index()
        .rename(columns={"revenue_ntd_billion": "sector_total_revenue_billion"})
    )
    sec_mo["sector_total_revenue_billion"] = sec_mo["sector_total_revenue_billion"].round(2)

    # ⑩ 類股 YoY
    sec_mo["_ym"] = sec_mo["month"].dt.to_period("M")
    prev12_sec = sec_mo[["_ym", "sector_total_revenue_billion"]].copy()
    prev12_sec["_ym"] = prev12_sec["_ym"] + 12
    prev12_sec = prev12_sec.rename(columns={"sector_total_revenue_billion": "_sec12"})
    sec_mo = sec_mo.merge(prev12_sec, on="_ym", how="left")
    sec_mo["sector_yoy_growth_pct"] = (
        (sec_mo["sector_total_revenue_billion"] / sec_mo["_sec12"] - 1) * 100
    ).round(2)
    sec_mo.drop(columns=["_ym", "_sec12"], inplace=True)

    df = df.merge(sec_mo, on="month", how="left")

    # ⑨ 個股占比
    df["revenue_share_pct"] = (
        df["revenue_ntd_billion"] / df["sector_total_revenue_billion"] * 100
    ).round(2)

    return df


# ── 5. 主程式 ────────────────────────────────────────────────────────────────

SINGLE_COLS = [
    "security_code", "security_name", "month",
    "revenue_ntd_billion", "yoy_growth_pct", "mom_growth_pct",
    "ytd_revenue_ntd_billion", "ytd_yoy_growth_pct",
]
MULTI_COLS = [
    "security_code", "security_name", "month",
    "revenue_ntd_billion", "yoy_growth_pct", "mom_growth_pct",
    "revenue_indexed",
]
SECTOR_COLS = [
    "sector_name", "security_code", "security_name", "month",
    "revenue_ntd_billion", "yoy_growth_pct",
    "sector_total_revenue_billion", "revenue_share_pct", "sector_yoy_growth_pct",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成 Tableau 月營收分析 CSV"
    )
    parser.add_argument("--mode", choices=["single", "multi", "sector"], required=True)
    parser.add_argument("--codes", nargs="+", help="股票代號（single/multi 模式）")
    parser.add_argument("--sector", help="類股名稱（sector 模式）")
    parser.add_argument("--months", type=int, default=36, help="輸出月數（預設 36）")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: 環境變數 DATABASE_URL 未設定", file=sys.stderr)
        sys.exit(1)

    # 確認股票代號
    if args.mode in ("single", "multi"):
        if not args.codes:
            print(f"ERROR: --mode {args.mode} 需要 --codes", file=sys.stderr)
            sys.exit(1)
        codes = args.codes
        sector_name = None
    else:
        if not args.sector:
            print("ERROR: --mode sector 需要 --sector", file=sys.stderr)
            sys.exit(1)
        sector_map = parse_sector_map(SECTOR_CSV)
        if args.sector not in sector_map:
            available = sorted(sector_map.keys())
            print(f"ERROR: 找不到類股「{args.sector}」", file=sys.stderr)
            print(f"可用類股（前 20）：{available[:20]}", file=sys.stderr)
            sys.exit(1)
        codes = sector_map[args.sector]
        sector_name = args.sector
        print(f"類股「{sector_name}」共 {len(codes)} 檔：{codes[:10]}{'...' if len(codes)>10 else ''}")

    # 查詢
    print(f"連線中…")
    conn = psycopg2.connect(db_url)
    try:
        df = fetch_revenue(conn, codes, args.months)
    finally:
        conn.close()

    if df.empty:
        print("WARNING: 查無資料，請確認股票代號與資料庫內容")
        sys.exit(0)

    print(f"取得 {len(df)} 筆原始資料，計算衍生欄位中…")

    # 計算
    df = compute_derived(df)

    if args.mode == "sector":
        df = add_sector_columns(df, sector_name)

    # 過濾：保留最近 output_months 個月
    cutoff_ym = df["_ym"].max() - (args.months - 1)
    df = df[df["_ym"] >= cutoff_ym].reset_index(drop=True)
    df.drop(columns=["_ym"], inplace=True)

    # 月份格式化
    df["month"] = df["month"].dt.strftime("%Y-%m-01")

    # 選欄輸出
    if args.mode == "single":
        out_cols = SINGLE_COLS
        fname = f"單股月營收_{args.codes[0]}.csv"
    elif args.mode == "multi":
        out_cols = MULTI_COLS
        fname = f"多股月營收_{'_'.join(args.codes)}.csv"
    else:
        out_cols = SECTOR_COLS
        fname = f"類股月營收_{sector_name}.csv"

    out_path = BASE_DIR / fname
    df[out_cols].to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"已輸出：{out_path}（{len(df)} 筆）")


if __name__ == "__main__":
    main()
