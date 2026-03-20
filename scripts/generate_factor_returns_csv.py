"""
generate_factor_returns_csv.py
產生因子報酬（A）CSV。

因子定義（Fama-French 風格，2×3 投資組合）：
  - Rm_Rf : 市場溢酬 = 加權指數報酬 − 無風險利率
  - SMB   : 規模溢酬 = (小型股組合 − 大型股組合) 市值加權
  - HML   : 淨值市價比溢酬 = (高 B/M − 低 B/M) 市值加權
  - WML_ep: 益本比溢酬 = (高 E/P − 低 E/P) 市值加權
  - WML_dy: 股利殖利率溢酬 = (高殖利率 − 低殖利率) 市值加權
  - UMD   : 動能溢酬 = (高動能 − 低動能) 市值加權，過去 12–1 月報酬
  - STR   : 短期反轉溢酬 = (低過去1月 − 高過去1月) 市值加權

無風險利率：國內銀行利率 CSV 各家銀行「一年定存」之日平均。

輸出：All_Data/事件資料/因子報酬.csv
  欄位：年月日, Rm_Rf, SMB, HML, WML_ep, WML_dy, UMD, STR
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).resolve().parent.parent
STOCK_PRICE_DIR  = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
BANK_RATE_DIR    = BASE_DIR / "All_Data" / "日資料" / "國內銀行利率(日)_國內銀行匯率"
OUTPUT_DIR       = BASE_DIR / "All_Data" / "事件資料"
OUTPUT_PATH      = OUTPUT_DIR / "因子報酬.csv"

# 只保留個股（4 碼數字起頭）
_STOCK_CODE_RE = r"^\d{4}"
# 大盤指數識別
_MARKET_PATTERNS = ["Y9999", "加權指數"]

# 分組百分位（30% / 70%）
_PCT_LOW, _PCT_HIGH = 0.30, 0.70
# 動能形成期：過去 12 個月扣除最近 1 個月（約 252−21 交易日）
_MOM_LOOKBACK = 252 - 21
# 短期反轉：過去 1 個月（約 21 交易日）
_STR_LOOKBACK = 21
# 市值加權最小門檻（百萬）
_MIN_MV = 100


def _extract_code(full: str) -> str:
    return str(full).strip().split()[0]


def _is_market(sec: str) -> bool:
    code = _extract_code(sec)
    return code == "Y9999" or "加權" in str(sec)


def load_stock_data() -> pd.DataFrame:
    """讀取 TEJ 股價資料庫。"""
    csv_files = sorted(STOCK_PRICE_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到 CSV：{STOCK_PRICE_DIR}")

    needed = [
        "證券代碼", "年月日", "報酬率％", "市值(百萬元)",
        "本益比-TSE", "股價淨值比-TSE",
        "股利殖利率-TSE", "現金股利率",
    ]
    dfs = []
    for f in csv_files:
        try:
            raw = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            cols = [c for c in needed if c in raw.columns]
            raw = raw[cols].copy()
            raw["_src"] = f.name
            dfs.append(raw)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}", file=sys.stderr)

    combined = pd.concat(dfs, ignore_index=True)
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()
    combined["年月日"] = combined["年月日"].astype(str).str.strip()
    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    for c in ["報酬率％", "市值(百萬元)", "本益比-TSE", "股價淨值比-TSE", "股利殖利率-TSE", "現金股利率"]:
        if c in combined.columns:
            combined[c] = pd.to_numeric(combined[c].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")

    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined.sort_values(["證券代碼", "date"], inplace=True)
    return combined


def load_risk_free() -> pd.Series:
    """讀取無風險利率（各家銀行一年定存之日平均）。"""
    csv_files = sorted(BANK_RATE_DIR.glob("*.csv"))
    if not csv_files:
        print("[警告] 找不到銀行利率 CSV，無風險利率設為 0", file=sys.stderr)
        return None

    dfs = []
    for f in csv_files:
        try:
            raw = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            if "一年定存" not in raw.columns or "年月日" not in raw.columns:
                continue
            raw = raw[["證券代碼", "年月日", "一年定存"]].copy()
            raw["一年定存"] = pd.to_numeric(raw["一年定存"].astype(str).str.strip(), errors="coerce")
            raw = raw[raw["一年定存"].notna() & (raw["一年定存"] > 0)]
            if len(raw) > 0:
                dfs.append(raw)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}", file=sys.stderr)

    if not dfs:
        print("[警告] 無有效一年定存資料，無風險利率設為 0", file=sys.stderr)
        return None

    all_df = pd.concat(dfs, ignore_index=True)
    all_df["年月日"] = all_df["年月日"].astype(str).str.strip()
    rf = all_df.groupby("年月日")["一年定存"].mean()
    rf.index = pd.to_datetime(rf.index, format="%Y%m%d", errors="coerce")
    rf = rf[rf.index.notna()]
    return rf


def compute_momentum_returns(df: pd.DataFrame) -> pd.DataFrame:
    """計算每檔股票過去 12–1 月、過去 1 月累積報酬。"""
    df = df.sort_values(["證券代碼", "date"]).copy()
    df["ret"] = df["報酬率％"] / 100.0
    df["cumret_12_1"] = np.nan
    df["cumret_1m"] = np.nan

    for code, grp in df.groupby("證券代碼"):
        grp = grp.sort_values("date").reset_index(drop=True)
        ret_arr = grp["ret"].values
        dates = grp["date"].values

        for i in range(len(grp)):
            di = pd.Timestamp(dates[i])
            # 過去 12–1 月：從 i 往前 252 日至 22 日（約 231 日）
            # 過去 1 月：從 i 往前 21 日至當日（約 21 日）
            # 使用交易日索引（簡化：假設連續排列即為交易日）
            start_mom = max(0, i - _MOM_LOOKBACK)
            end_mom = max(0, i - _STR_LOOKBACK)
            if end_mom > start_mom and end_mom < i:
                sub = 1.0 + np.array(ret_arr[start_mom:end_mom])
                sub = sub[~np.isnan(sub)]
                if len(sub) > 0:
                    df.loc[grp.index[i], "cumret_12_1"] = (np.prod(sub) - 1) * 100

            start_str = max(0, i - _STR_LOOKBACK)
            if start_str < i:
                sub = 1.0 + np.array(ret_arr[start_str:i])
                sub = sub[~np.isnan(sub)]
                if len(sub) > 0:
                    df.loc[grp.index[i], "cumret_1m"] = (np.prod(sub) - 1) * 100

    return df


def _vwret(df: pd.DataFrame, col_ret: str, col_w: str = "市值(百萬元)") -> float:
    """市值加權報酬。"""
    df = df.dropna(subset=[col_ret, col_w])
    df = df[df[col_w] >= _MIN_MV]
    if len(df) == 0:
        return np.nan
    w = df[col_w].values
    r = df[col_ret].values
    return np.average(r, weights=w)


def build_factor_returns(df: pd.DataFrame, rf_series: pd.Series) -> pd.DataFrame:
    """建構因子報酬。"""
    is_stock = df["證券代碼"].str.match(_STOCK_CODE_RE, na=False)
    stocks = df[is_stock].copy()
    if stocks.empty:
        raise ValueError("無個股資料")

    # 大盤報酬
    mkt = df[df["證券代碼"].apply(_is_market)].copy()
    if mkt.empty:
        # 備用：搜尋 Y9999
        mkt = df[df["證券代碼"].str.contains("Y9999", na=False)]
    if mkt.empty:
        raise ValueError("找不到大盤指數 Y9999")

    mkt = mkt[["年月日", "date", "報酬率％"]].drop_duplicates("年月日")
    mkt_ser = mkt.set_index("date")["報酬率％"] / 100.0

    # 動能、短期反轉
    stocks = compute_momentum_returns(stocks)

    dates = sorted(stocks["date"].dropna().unique())
    results = []

    for d in dates:
        di = pd.Timestamp(d)
        day_stocks = stocks[stocks["date"] == di].copy()
        if len(day_stocks) < 30:
            continue

        day_stocks = day_stocks.dropna(subset=["報酬率％", "市值(百萬元)"])
        day_stocks = day_stocks[day_stocks["市值(百萬元)"] >= _MIN_MV]
        if len(day_stocks) < 20:
            continue

        # 使用前一交易日特徵（避免 look-ahead），此處簡化用當日
        size = day_stocks["市值(百萬元)"]
        pb = day_stocks["股價淨值比-TSE"]
        pe = day_stocks["本益比-TSE"]
        dy = day_stocks["股利殖利率-TSE"].fillna(day_stocks["現金股利率"])

        # B/M = 1/PB，排除 PB<=0 或缺失
        bm = 1.0 / pb.replace(0, np.nan)
        ep = 1.0 / pe.replace(0, np.nan)
        ep = ep.clip(upper=1.0)
        dy = dy.fillna(0)

        day_stocks["_size"] = size
        day_stocks["_bm"] = bm
        day_stocks["_ep"] = ep
        day_stocks["_dy"] = dy
        day_stocks["_mom"] = day_stocks["cumret_12_1"]
        day_stocks["_str"] = day_stocks["cumret_1m"]

        valid = day_stocks.dropna(subset=["_size"])
        if len(valid) < 20:
            continue

        # 規模：中位數分大小
        sz_med = valid["_size"].median()
        is_small = valid["_size"] < sz_med
        is_big = ~is_small

        # B/M：30/70 分位
        bm_valid = valid["_bm"].dropna()
        if len(bm_valid) >= 10:
            bm_30, bm_70 = bm_valid.quantile(_PCT_LOW), bm_valid.quantile(_PCT_HIGH)
            is_h = valid["_bm"] >= bm_70
            is_l = valid["_bm"] <= bm_30
        else:
            is_h = pd.Series(False, index=valid.index)
            is_l = pd.Series(False, index=valid.index)

        # E/P：30/70
        ep_valid = valid["_ep"].dropna()
        ep_valid = ep_valid[ep_valid > 0]
        if len(ep_valid) >= 10:
            ep_30, ep_70 = ep_valid.quantile(_PCT_LOW), ep_valid.quantile(_PCT_HIGH)
            is_ep_h = valid["_ep"] >= ep_70
            is_ep_l = valid["_ep"] <= ep_30
        else:
            is_ep_h = pd.Series(False, index=valid.index)
            is_ep_l = pd.Series(False, index=valid.index)

        # 股利殖利率：30/70
        dy_valid = valid["_dy"][valid["_dy"] > 0]
        if len(dy_valid) >= 10:
            dy_30, dy_70 = dy_valid.quantile(_PCT_LOW), dy_valid.quantile(_PCT_HIGH)
            is_dy_h = valid["_dy"] >= dy_70
            is_dy_l = valid["_dy"] <= dy_30
        else:
            is_dy_h = pd.Series(False, index=valid.index)
            is_dy_l = pd.Series(False, index=valid.index)

        # 動能：30/70
        mom_valid = valid["_mom"].dropna()
        if len(mom_valid) >= 10:
            mom_30, mom_70 = mom_valid.quantile(_PCT_LOW), mom_valid.quantile(_PCT_HIGH)
            is_mom_h = valid["_mom"] >= mom_70
            is_mom_l = valid["_mom"] <= mom_30
        else:
            is_mom_h = pd.Series(False, index=valid.index)
            is_mom_l = pd.Series(False, index=valid.index)

        # 短期反轉：30/70（STR 為低過去1月做多、高做空）
        str_valid = valid["_str"].dropna()
        if len(str_valid) >= 10:
            str_30, str_70 = str_valid.quantile(_PCT_LOW), str_valid.quantile(_PCT_HIGH)
            is_str_h = valid["_str"] >= str_70
            is_str_l = valid["_str"] <= str_30
        else:
            is_str_h = pd.Series(False, index=valid.index)
            is_str_l = pd.Series(False, index=valid.index)

        # 六組 (S,H)(S,M)(S,L)(B,H)(B,M)(B,L)
        sh = valid[is_small & is_h]
        sm = valid[is_small & ~is_h & ~is_l]
        sl = valid[is_small & is_l]
        bh = valid[is_big & is_h]
        bm_p = valid[is_big & ~is_h & ~is_l]
        bl = valid[is_big & is_l]

        def vw(g):
            return _vwret(g, "報酬率％") if len(g) > 0 else np.nan

        r_sh, r_sm, r_sl = vw(sh), vw(sm), vw(sl)
        r_bh, r_bm, r_bl = vw(bh), vw(bm_p), vw(bl)

        smb = np.nanmean([r_sh, r_sm, r_sl]) - np.nanmean([r_bh, r_bm, r_bl])
        hml = np.nanmean([r_sh, r_bh]) - np.nanmean([r_sl, r_bl])

        # WML_ep
        ep_h = valid[is_ep_h]
        ep_l = valid[is_ep_l]
        wml_ep = vw(ep_h) - vw(ep_l) if len(ep_h) > 0 and len(ep_l) > 0 else np.nan

        # WML_dy
        dy_h = valid[is_dy_h]
        dy_l = valid[is_dy_l]
        wml_dy = vw(dy_h) - vw(dy_l) if len(dy_h) > 0 and len(dy_l) > 0 else np.nan

        # UMD
        umd_h = valid[is_mom_h]
        umd_l = valid[is_mom_l]
        umd = vw(umd_h) - vw(umd_l) if len(umd_h) > 0 and len(umd_l) > 0 else np.nan

        # STR（低過去1月做多 - 高做空）
        str_h = valid[is_str_h]
        str_l = valid[is_str_l]
        str_ret = vw(str_l) - vw(str_h) if len(str_l) > 0 and len(str_h) > 0 else np.nan

        # Rm - Rf（使用 mkt_ser，index 為 datetime）
        try:
            rm = mkt_ser.loc[di] if di in mkt_ser.index else np.nan
        except (KeyError, TypeError):
            rm = np.nan
        if pd.isna(rm) and len(mkt_ser) > 0:
            try:
                rm = mkt_ser.asof(di)
            except (TypeError, ValueError):
                rm = np.nan
        rf_val = 0.0
        if rf_series is not None and len(rf_series) > 0:
            try:
                if di in rf_series.index:
                    rf_val = rf_series.loc[di]
                else:
                    rf_val = rf_series.asof(di) if hasattr(rf_series, "asof") else 0.0
            except (KeyError, IndexError, TypeError):
                rf_val = 0.0
        rf_val = float(rf_val) / 100.0 if rf_val is not None and not (isinstance(rf_val, float) and np.isnan(rf_val)) else 0.0
        rm_rf = (rm - rf_val) * 100 if not pd.isna(rm) else np.nan

        results.append({
            "年月日": int(di.strftime("%Y%m%d")),
            "Rm_Rf": round(rm_rf, 4) if not np.isnan(rm_rf) else None,
            "SMB": round(smb, 4) if not np.isnan(smb) else None,
            "HML": round(hml, 4) if not np.isnan(hml) else None,
            "WML_ep": round(wml_ep, 4) if not np.isnan(wml_ep) else None,
            "WML_dy": round(wml_dy, 4) if not np.isnan(wml_dy) else None,
            "UMD": round(umd, 4) if not np.isnan(umd) else None,
            "STR": round(str_ret, 4) if not np.isnan(str_ret) else None,
        })

    out = pd.DataFrame(results)
    out = out.dropna(subset=["年月日"])
    return out


def main():
    print("=" * 55)
    print("因子報酬 CSV 產生腳本（A. 因子報酬）")
    print("=" * 55)

    print("\n[1/4] 載入股價資料...")
    df = load_stock_data()
    print(f"      合計 {len(df):,} 筆，個股 {df[df['證券代碼'].str.match(_STOCK_CODE_RE, na=False)]['證券代碼'].nunique():,} 檔")

    print("\n[2/4] 載入無風險利率...")
    rf = load_risk_free()
    if rf is not None:
        print(f"      有效日期 {len(rf):,} 天")
    else:
        print("      使用 0")

    print("\n[3/4] 建構因子報酬...")
    factors = build_factor_returns(df, rf)

    print(f"\n[4/4] 儲存至：{OUTPUT_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    factors.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"      完成！共 {len(factors):,} 筆")
    print("=" * 55)


if __name__ == "__main__":
    main()
