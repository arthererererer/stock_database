# -*- coding: utf-8 -*-
"""
自 TEJ 國際股價指數（PostgreSQL 或 CSV）與匯率資料產生：
各市場大盤指數每日本幣累積漲跌幅、貨幣累積漲跌幅
及美元重編累積漲跌幅（精確公式：(1+dI)(1+dF)-1 = dI + dF + dI·dF）。

輸出（專案根目錄）：
  international_index_decomposition_tableau.csv   — 每日分解（Tableau 用）
  intl_rolling_stats_tableau.csv                  — 滾動波動度 / Sortino（Tableau 用）
  intl_summary_stats.csv                          — 全期統計 + 回歸摘要

使用方式：
  # 全部從 PostgreSQL 讀取（TEJ 指數 + 匯率），推薦
  python build_intl_index_april_decomposition.py --start-date 20250101 --end-date 20251231 --from-db
  # 便利模式（整年）
  python build_intl_index_april_decomposition.py --year 2025 --from-db
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# (市場中文, 市場英文, TEJ 證券代碼全名, 報價幣別)
MARKET_ROWS: list[tuple[str, str, str, str]] = [
    ("台灣",   "Taiwan",   "SB01 台灣發行量加權股價指數1966=100",      "TWD"),
    ("韓國",   "Korea",    "SB12 韓國綜合股價指數",                    "KRW"),
    ("日本",   "Japan",    "SB04 日本東京日經225指數",                  "JPY"),
    ("中國",   "China",    "SB6903 中國滬深300指數",                   "CNY"),
    ("香港",   "HongKong", "SB05 香港恆生指數",                        "HKD"),
    ("美國",   "USA",      "SB23 美國紐約史坦普爾500股價指數",          "USD"),
    ("印度",   "India",    "SB7708 印度NIFTY 50",                     "INR"),
    ("歐洲",   "Europe",   "SB92 泛歐道瓊600指數",                      "EUR"),
    ("英國",   "UK",       "SB16 英國倫敦金融時報一百種股價指數",        "GBP"),
    ("德國",   "Germany",  "SB08 德國DAX指數",                         "EUR"),
    ("法國",   "France",   "SB75 法國巴黎CAC 40指數",                   "EUR"),
    ("澳洲",   "Australia","SB2501 澳洲雪梨ASX 200股價指數",             "AUD"),
    ("加拿大", "Canada",   "SB14 加拿大-多倫多綜合股價指數",             "CAD"),
]

CCY_TO_FX_COL: dict[str, str] = {
    "TWD": "TWD",
    "KRW": "KRW",
    "JPY": "JPY",
    "CNY": "CNY",
    "HKD": "HKD",
    "EUR": "EUR",
    "GBP": "GBP",
    "CAD": "CAD",
    "AUD": "AUD",
    "INR": "INR",
    "USD": "USD",
}


def _split_code_name(sec_code: str) -> tuple[str, str]:
    """'SB23 美國紐約史坦普爾500股價指數' → ('SB23', '美國紐約史坦普爾500股價指數')"""
    parts = sec_code.split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (sec_code, "")


def _find_latest_tej_csv(repo_root: Path) -> Path:
    d = repo_root / "All_Data" / "日資料" / "國際股價指數"
    if not d.is_dir():
        raise FileNotFoundError(f"找不到目錄：{d}")
    csvs = sorted(d.glob("*.csv"), key=lambda p: p.name)
    if not csvs:
        raise FileNotFoundError(f"{d} 內無 CSV")
    return csvs[-1]


def _load_tej_long(path: Path) -> pd.DataFrame:
    with open(path, "rb") as bf:
        raw = bf.read(4)
    enc = "utf-16" if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") else "utf-8-sig"
    rows = []
    with open(path, "r", encoding=enc, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code = (row.get("證券代碼") or "").strip()
            ds = (row.get("年月日") or "").strip()
            lv = row.get("指數")
            if not code or not ds:
                continue
            try:
                dt = datetime.strptime(ds, "%Y%m%d").date()
            except ValueError:
                continue
            try:
                level = float(lv.replace(",", ""))
            except (TypeError, ValueError):
                continue
            rows.append({"證券代碼": code, "date": dt, "index_level": level})
    return pd.DataFrame(rows)


def _load_fx(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _load_fx_from_db(start: date, end: date) -> pd.DataFrame:
    """從 raw.fx_crawler 讀取指定日期區間的匯率（需環境變數 DATABASE_URL）。"""
    try:
        import psycopg2
    except ImportError:
        raise SystemExit("請先安裝 psycopg2-binary：pip install psycopg2-binary")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("未設定 DATABASE_URL，請先執行：$env:DATABASE_URL = 'postgresql://...'")

    sql = """
        SELECT currency, date, close
        FROM raw.fx_crawler
        WHERE date BETWEEN %s AND %s
        ORDER BY currency, date
    """
    with psycopg2.connect(db_url) as conn:
        df = pd.read_sql(sql, conn, params=(start, end))

    df["date"] = pd.to_datetime(df["date"]).dt.date
    print(f"  DB 匯率：{len(df)} 列，幣種 {sorted(df['currency'].unique().tolist())}")
    return df


def _load_tej_from_db(start: date, end: date) -> pd.DataFrame:
    """從 raw.tej_intl_index 讀取指定日期區間的國際指數（需環境變數 DATABASE_URL）。"""
    try:
        import psycopg2
    except ImportError:
        raise SystemExit("請先安裝 psycopg2-binary：pip install psycopg2-binary")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("未設定 DATABASE_URL，請先執行：$env:DATABASE_URL = 'postgresql://...'")

    codes_needed = [row[2] for row in MARKET_ROWS]

    sql = """
        SELECT security_code, date, index_value
        FROM raw.tej_intl_index
        WHERE date BETWEEN %s AND %s
          AND security_code = ANY(%s)
        ORDER BY security_code, date
    """
    with psycopg2.connect(db_url) as conn:
        df = pd.read_sql(sql, conn, params=(start, end, codes_needed))

    df["date"] = pd.to_datetime(df["date"]).dt.date
    # 統一欄位名稱，與 _load_tej_long 的輸出格式相同
    df = df.rename(columns={"security_code": "證券代碼", "index_value": "index_level"})
    print(f"  DB TEJ：{len(df)} 列，代碼 {sorted(df['證券代碼'].unique().tolist())}")
    return df


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _align_fx(
    index_dates: list[date],
    ccy: str,
    fx_by_ccy: dict[str, pd.DataFrame],
) -> list[float]:
    """回傳與 index_dates 等長的匯率序列（無資料日往前填補）。USD 全為 1.0。"""
    if ccy == "USD":
        return [1.0] * len(index_dates)

    col = CCY_TO_FX_COL.get(ccy)
    fdf = fx_by_ccy.get(col) if col else None
    if fdf is None or fdf.empty:
        return [float("nan")] * len(index_dates)

    dm = fdf.set_index("date")["close"]
    result = []
    for d in index_dates:
        if d in dm.index:
            result.append(float(dm.loc[d]))
        else:
            prev = dm[dm.index <= d]
            result.append(float(prev.iloc[-1]) if len(prev) else float("nan"))
    return result


def build_output(
    tej_df: pd.DataFrame,
    fx_df: pd.DataFrame,
    start: date,
    end: date,
) -> pd.DataFrame:
    fx_by_ccy: dict[str, pd.DataFrame] = {}
    if not fx_df.empty and "currency" in fx_df.columns:
        for ccy_val in fx_df["currency"].unique():
            sub = fx_df[fx_df["currency"] == ccy_val].sort_values("date")
            fx_by_ccy[str(ccy_val).upper()] = sub

    out_rows: list[dict] = []

    for market_cn, market_en, sec_code, ccy in MARKET_ROWS:
        index_code, index_name = _split_code_name(sec_code)

        sub = tej_df[tej_df["證券代碼"] == sec_code].copy()
        if sub.empty:
            print(f"  [跳過] {market_cn}：TEJ 找不到 {sec_code!r}")
            continue
        sub = sub[(sub["date"] >= start) & (sub["date"] <= end)].sort_values("date")
        if sub.empty:
            print(f"  [跳過] {market_cn}：{start} ～ {end} 無資料")
            continue

        index_dates = sub["date"].tolist()
        levels = sub["index_level"].tolist()
        fx_vals = _align_fx(index_dates, ccy, fx_by_ccy)

        s0 = levels[0]
        f0 = fx_vals[0]
        prev_level = s0
        prev_fx = f0

        for i, (dt, st, ft) in enumerate(zip(index_dates, levels, fx_vals)):
            # 日報酬（第一日 = 0）
            daily_idx = (st / prev_level - 1.0) * 100.0 if i > 0 else 0.0
            if ccy == "USD":
                daily_fx = 0.0
                daily_total = daily_idx
            elif prev_fx != prev_fx or ft != ft or prev_fx == 0:
                daily_fx = float("nan")
                daily_total = float("nan")
            else:
                daily_fx = (ft / prev_fx - 1.0) * 100.0 if i > 0 else 0.0
                daily_total = ((1 + daily_idx / 100.0) * (1 + daily_fx / 100.0) - 1.0) * 100.0

            # 累積報酬（從整個時間序列第一個交易日起算，不中途重置）
            cum_idx = (st / s0 - 1.0) * 100.0
            if ccy == "USD":
                cum_fx = 0.0
                cum_total = cum_idx
                cum_cross = 0.0
            elif f0 != f0 or ft != ft or f0 == 0:
                cum_fx = float("nan")
                cum_total = float("nan")
                cum_cross = float("nan")
            else:
                cum_fx = (ft / f0 - 1.0) * 100.0
                cum_total = ((st * ft) / (s0 * f0) - 1.0) * 100.0
                cum_cross = cum_total - cum_idx - cum_fx

            _nan = float("nan")

            out_rows.append({
                "date":             dt.isoformat(),
                "market_cn":        market_cn,
                "market_en":        market_en,
                "index_code":       index_code,
                "index_name":       index_name,
                "currency":         ccy,
                "index_value":      round(st, 4),
                "daily_index_pct":  round(daily_idx, 4),
                "daily_fx_pct":     round(daily_fx, 4) if daily_fx == daily_fx else "",
                "daily_total_pct":  round(daily_total, 4) if daily_total == daily_total else "",
                "cum_index_pct":    round(cum_idx, 4),
                "cum_fx_pct":       round(cum_fx, 4) if cum_fx == cum_fx else "",
                "cum_cross_pct":    round(cum_cross, 6) if cum_cross == cum_cross else "",
                "cum_total_pct":    round(cum_total, 4) if cum_total == cum_total else "",
            })

            prev_level = st
            prev_fx = ft

        print(f"  ✓ {market_cn} ({market_en})：{len(sub)} 筆，幣別 {ccy}")

    return pd.DataFrame(out_rows)


def _rolling_sortino(returns: pd.Series, window: int = 20) -> pd.Series:
    """
    滾動 Sortino Ratio（年化）。
    公式：(mean_return_ann) / (downside_std_ann)
    downside_std 只用窗口內負報酬的標準差（無負報酬時回傳 NaN）。
    """
    results = np.full(len(returns), np.nan)
    arr = returns.to_numpy(dtype=float)
    for i in range(window - 1, len(arr)):
        window_r = arr[i - window + 1 : i + 1]
        mean_ann = np.nanmean(window_r) * 252
        neg = window_r[window_r < 0]
        if len(neg) < 2:
            continue
        down_std_ann = np.nanstd(neg, ddof=1) * np.sqrt(252)
        if down_std_ann == 0:
            continue
        results[i] = mean_ann / down_std_ann
    return pd.Series(results, index=returns.index)


def build_volatility_stats(
    main_df: pd.DataFrame,
    window: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    從主 CSV DataFrame 計算滾動波動度與 Sortino，以及全期統計 + 回歸。

    回傳：
      rolling_df  — 每市場每日的滾動指標（Tableau 用）
      summary_df  — 每市場全期摘要 + 與 cum_cross_pct 的 OLS 回歸
    """
    rolling_rows: list[dict] = []
    summary_rows: list[dict] = []

    for code, grp in main_df.groupby("index_code", sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        market_cn = grp["market_cn"].iloc[0]
        market_en = grp["market_en"].iloc[0]

        # daily_total_pct：第 0 日為 0，排除後計算統計
        r_raw = pd.to_numeric(grp["daily_total_pct"], errors="coerce").fillna(0.0)
        cross = pd.to_numeric(grp["cum_cross_pct"], errors="coerce")

        roll_std = r_raw.rolling(window).std() * np.sqrt(252)
        roll_sortino = _rolling_sortino(r_raw, window)

        # 每日滾動 CSV
        for i in range(len(grp)):
            rolling_rows.append({
                "date":           grp["date"].iloc[i],
                "market_cn":      market_cn,
                "market_en":      market_en,
                "index_code":     code,
                "daily_total_pct": round(float(r_raw.iloc[i]), 4),
                "cum_cross_pct":  round(float(cross.iloc[i]), 6) if not np.isnan(float(cross.iloc[i])) else "",
                f"roll{window}d_std_ann":   (round(float(roll_std.iloc[i]), 4) if not np.isnan(roll_std.iloc[i]) else ""),
                f"roll{window}d_sortino":   (round(float(roll_sortino.iloc[i]), 4) if not np.isnan(roll_sortino.iloc[i]) else ""),
            })

        # 全期統計（跳過第 0 日 = 0）
        r_valid = r_raw[r_raw != 0.0]
        ann_mean = float(r_valid.mean()) * 252
        ann_std  = float(r_valid.std(ddof=1)) * np.sqrt(252)
        neg      = r_valid[r_valid < 0]
        down_std = float(neg.std(ddof=1)) * np.sqrt(252) if len(neg) >= 2 else np.nan
        sortino  = ann_mean / down_std if not np.isnan(down_std) and down_std != 0 else np.nan
        sharpe   = ann_mean / ann_std  if ann_std != 0 else np.nan

        # OLS：roll_std ~ cum_cross_pct
        def _ols(x: pd.Series, y: pd.Series) -> dict:
            mask = x.notna() & y.notna()
            xi = x[mask].astype(float)
            yi = y[mask].astype(float)
            if len(xi) < 10 or xi.std() == 0:
                return {"slope": "", "r2": "", "pvalue": ""}
            sl, _, rv, pv, _ = scipy_stats.linregress(xi.values, yi.values)
            return {"slope": round(sl, 6), "r2": round(rv**2, 4), "pvalue": round(pv, 4)}

        reg_std  = _ols(cross, roll_std)
        reg_sor  = _ols(cross, roll_sortino)

        summary_rows.append({
            "index_code":   code,
            "market_cn":    market_cn,
            "market_en":    market_en,
            "n_days":       int(len(r_valid)),
            "ann_mean_pct": round(ann_mean, 4),
            "ann_std_pct":  round(ann_std, 4),
            "ann_sortino":  round(sortino, 4) if not np.isnan(sortino) else "",
            "ann_sharpe":   round(sharpe, 4)  if not np.isnan(sharpe)  else "",
            f"std_vs_cross_slope":  reg_std["slope"],
            f"std_vs_cross_r2":     reg_std["r2"],
            f"std_vs_cross_pvalue": reg_std["pvalue"],
            f"sortino_vs_cross_slope":  reg_sor["slope"],
            f"sortino_vs_cross_r2":     reg_sor["r2"],
            f"sortino_vs_cross_pvalue": reg_sor["pvalue"],
        })

    return pd.DataFrame(rolling_rows), pd.DataFrame(summary_rows)


def _parse_date(s: str) -> date:
    s = s.strip().replace("-", "")
    return datetime.strptime(s, "%Y%m%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="國際指數 × 匯率：任意日期區間每日累積漲跌幅（Tableau 用途 CSV）",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "範例：\n"
            "  # 指定月份（便利模式）\n"
            "  python build_intl_index_april_decomposition.py --year 2025 --month 4 --from-db\n\n"
            "  # 自訂區間\n"
            "  python build_intl_index_april_decomposition.py --start-date 20250101 --end-date 20251231 --from-db\n"
        ),
    )
    parser.add_argument("--start-date", type=str, default="", help="起始日 YYYYMMDD 或 YYYY-MM-DD（與 --year/--month 互斥）")
    parser.add_argument("--end-date",   type=str, default="", help="結束日 YYYYMMDD 或 YYYY-MM-DD（與 --year/--month 互斥）")
    parser.add_argument("--year",    type=int, default=0,  help="便利模式：指定年份（搭配 --month）")
    parser.add_argument("--month",   type=int, default=0,  help="便利模式：指定月份（搭配 --year）")
    parser.add_argument("--tej",     type=str, default="", help="TEJ 國際股價指數 CSV 路徑（覆蓋 DB，可選）")
    parser.add_argument("--fx",      type=str, default="", help="fx_history_combined.csv 路徑（可選，與 --from-db 互斥）")
    parser.add_argument("--from-db", action="store_true",  help="從 PostgreSQL 讀取 TEJ 指數（raw.tej_intl_index）與匯率（raw.fx_crawler）")
    parser.add_argument("--window",  type=int, default=20, help="滾動波動度/Sortino 窗口（交易日，預設 20）")
    parser.add_argument(
        "-o", "--output", type=str, default="",
        help="主 CSV 輸出路徑（預設：專案根目錄 international_index_decomposition_tableau.csv）",
    )
    args = parser.parse_args()

    # ── 決定日期區間 ──────────────────────────────────────
    if args.start_date and args.end_date:
        start = _parse_date(args.start_date)
        end   = _parse_date(args.end_date)
    elif args.year and args.month:
        start, end = _month_bounds(args.year, args.month)
    elif args.year and not args.month:
        start = date(args.year, 1, 1)
        end   = date(args.year, 12, 31)
    else:
        parser.error("請提供 --start-date/--end-date 或 --year/--month")

    here = Path(__file__).resolve().parent   # 指數儀錶板/
    repo = here.parent                        # 財經數據分析平台/（專案根目錄）

    out_path = Path(args.output) if args.output else here / "international_index_decomposition_tableau.csv"

    print(f"區間：{start} ～ {end}")

    # ── 載入 TEJ 指數 ──────────────────────────────────────
    if args.tej:
        tej_path = Path(args.tej)
        print(f"TEJ（CSV）：{tej_path}")
        tej_long = _load_tej_long(tej_path)
    elif args.from_db:
        print("TEJ：PostgreSQL raw.tej_intl_index")
        tej_long = _load_tej_from_db(start, end)
    else:
        tej_path = _find_latest_tej_csv(repo)
        print(f"TEJ（CSV）：{tej_path}")
        tej_long = _load_tej_long(tej_path)

    # ── 載入匯率 ──────────────────────────────────────────
    if args.from_db:
        print("FX ：PostgreSQL raw.fx_crawler")
        fx_df = _load_fx_from_db(start, end)
    else:
        fx_path = Path(args.fx) if args.fx else repo / "investing.com爬蟲" / "fx_history_combined.csv"
        print(f"FX ：{fx_path}")
        fx_df = _load_fx(fx_path) if fx_path.is_file() else pd.DataFrame()
        if fx_df.empty:
            print("[警告] 未載入匯率資料，貨幣欄位將全為空白")

    # ── 產生主 CSV ────────────────────────────────────────
    df = build_output(tej_long, fx_df, start, end)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[1/4] 主 CSV：{out_path}（{len(df)} 列，{df['market_cn'].nunique() if not df.empty else 0} 個市場）")

    if not df.empty:
        # ── 產生期末快照 CSV ──────────────────────────────
        num_cols = ["cum_index_pct", "cum_fx_pct", "cum_cross_pct", "cum_total_pct"]
        snap = df.copy()
        snap["date"] = pd.to_datetime(snap["date"])
        for c in num_cols:
            snap[c] = pd.to_numeric(snap[c], errors="coerce")

        snap = snap.sort_values("date").groupby("market_en", sort=False).last().reset_index()
        snap["period_start"] = df["date"].min()
        snap["period_end"]   = snap["date"].dt.strftime("%Y-%m-%d")
        snap["fx_share_of_total_pct"] = (
            snap["cum_fx_pct"] / snap["cum_total_pct"] * 100
        ).round(1)

        snap_cols = [
            "market_en", "market_cn", "currency",
            "period_start", "period_end",
            "cum_index_pct", "cum_fx_pct", "cum_cross_pct", "cum_total_pct",
            "fx_share_of_total_pct",
        ]
        snap = snap[snap_cols].sort_values("cum_total_pct", ascending=False)
        snap_path = here / "intl_index_snapshot_tableau.csv"
        snap.to_csv(snap_path, index=False, encoding="utf-8-sig")
        print(f"[2/4] 期末快照：{snap_path}（{len(snap)} 個市場，區間 {snap['period_start'].iloc[0]} ～ {snap['period_end'].max()}）")

        # ── 產生滾動統計 CSV ──────────────────────────────
        rolling_df, summary_df = build_volatility_stats(df, window=args.window)

        rolling_path = here / "intl_rolling_stats_tableau.csv"
        summary_path = here / "intl_summary_stats.csv"

        rolling_df.to_csv(rolling_path, index=False, encoding="utf-8-sig")
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

        print(f"[3/4] 滾動統計（{args.window}d window）：{rolling_path}（{len(rolling_df)} 列）")
        print(f"[4/4] 全期摘要 + 回歸：{summary_path}（{len(summary_df)} 個市場）")


if __name__ == "__main__":
    main()
