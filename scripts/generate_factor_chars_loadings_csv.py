"""
generate_factor_chars_loadings_csv.py
產生因子特徵（B）與因子載荷（C）CSV。

因子特徵（B）：每檔個股、每天的原始特徵值
  - 規模：市值(百萬元)
  - 淨值市價比：1/股價淨值比 (B/M)
  - 益本比：1/本益比 (E/P)
  - 股利殖利率：股利殖利率-TSE 或 現金股利率
  - 動能：過去 12–1 月累積報酬(%)
  - 短期反轉：過去 1 月累積報酬(%)

因子載荷（C）：每檔個股對各因子報酬的 beta（滾動 252 日迴歸）
  - beta_Rm_Rf, beta_SMB, beta_HML, beta_WML_ep, beta_WML_dy, beta_UMD, beta_STR

需先執行 generate_factor_returns_csv.py 產生因子報酬.csv。

輸出：All_Data/事件資料/因子特徵與載荷.csv
  欄位：證券代碼, 年月日, 規模, 淨值市價比, 益本比, 股利殖利率, 動能, 短期反轉,
        beta_Rm_Rf, beta_SMB, beta_HML, beta_WML_ep, beta_WML_dy, beta_UMD, beta_STR
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).resolve().parent.parent
STOCK_PRICE_DIR  = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
FACTOR_RET_PATH  = BASE_DIR / "All_Data" / "事件資料" / "因子報酬.csv"
OUTPUT_DIR       = BASE_DIR / "All_Data" / "事件資料"
OUTPUT_PATH      = OUTPUT_DIR / "因子特徵與載荷.csv"

_STOCK_CODE_RE = r"^\d{4}"
_MOM_LOOKBACK = 252 - 21
_STR_LOOKBACK = 21
_ROLLING_WIN   = 252  # 因子載荷滾動視窗
_MIN_OBS       = 60   # 迴歸最少有效觀測數


def _extract_code(full: str) -> str:
    return str(full).strip().split()[0]


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
            combined[c] = pd.to_numeric(
                combined[c].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )

    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined.sort_values(["證券代碼", "date"], inplace=True)
    return combined


def load_factor_returns() -> pd.DataFrame:
    """讀取因子報酬 CSV。"""
    if not FACTOR_RET_PATH.exists():
        raise FileNotFoundError(
            f"找不到因子報酬檔：{FACTOR_RET_PATH}\n"
            "請先執行：python scripts/generate_factor_returns_csv.py"
        )
    df = pd.read_csv(FACTOR_RET_PATH, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["年月日"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    return df


def compute_characters(df: pd.DataFrame) -> pd.DataFrame:
    """計算每檔股票每天的因子特徵。"""
    df = df.copy()
    df["ret"] = df["報酬率％"] / 100.0
    df["規模"] = df["市值(百萬元)"]
    df["淨值市價比"] = np.where(
        (df["股價淨值比-TSE"].notna()) & (df["股價淨值比-TSE"] > 0),
        1.0 / df["股價淨值比-TSE"],
        np.nan,
    )
    df["益本比"] = np.where(
        (df["本益比-TSE"].notna()) & (df["本益比-TSE"] > 0),
        (1.0 / df["本益比-TSE"]).clip(upper=1.0),
        np.nan,
    )
    df["股利殖利率"] = df["股利殖利率-TSE"].fillna(df["現金股利率"])
    df["動能"] = np.nan
    df["短期反轉"] = np.nan

    for code, grp in df.groupby("證券代碼"):
        grp = grp.sort_values("date").reset_index(drop=True)
        ret_arr = grp["ret"].values
        n = len(grp)
        for i in range(n):
            start_mom = max(0, i - _MOM_LOOKBACK)
            end_mom = max(0, i - _STR_LOOKBACK)
            if end_mom > start_mom:
                sub = 1.0 + np.array(ret_arr[start_mom:end_mom])
                sub = sub[~np.isnan(sub)]
                if len(sub) > 0:
                    df.loc[grp.index[i], "動能"] = (np.prod(sub) - 1) * 100

            start_str = max(0, i - _STR_LOOKBACK)
            if start_str < i:
                sub = 1.0 + np.array(ret_arr[start_str:i])
                sub = sub[~np.isnan(sub)]
                if len(sub) > 0:
                    df.loc[grp.index[i], "短期反轉"] = (np.prod(sub) - 1) * 100

    return df


def compute_loadings(
    stock_df: pd.DataFrame, factor_df: pd.DataFrame
) -> pd.DataFrame:
    """對每檔股票滾動迴歸，估計因子載荷。"""
    factor_cols = [c for c in factor_df.columns if c not in ["年月日", "date"]]
    factor_cols = [c for c in factor_cols if factor_df[c].notna().any()]
    if not factor_cols:
        return stock_df

    dates = sorted(stock_df["date"].dropna().unique())
    factor_df = factor_df.set_index("date")
    results = []

    for code, grp in stock_df.groupby("證券代碼"):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)
        betas = {f"beta_{c}": np.nan for c in factor_cols}

        for i in range(_ROLLING_WIN, n):
            win = grp.iloc[i - _ROLLING_WIN : i]
            ret = win["ret"].values
            if np.isnan(ret).sum() > _ROLLING_WIN - _MIN_OBS:
                continue

            win_dates = win["date"].values
            fmat = factor_df.reindex(win_dates)
            fmat = fmat[factor_cols].ffill().bfill()
            if fmat.isna().any().any() or len(fmat) < _MIN_OBS:
                continue

            X = fmat.values
            y = ret
            valid = ~(np.isnan(y) | np.isnan(X).any(axis=1))
            if valid.sum() < _MIN_OBS:
                continue

            X = np.column_stack([np.ones(valid.sum()), X[valid]])
            y = y[valid]
            try:
                b = np.linalg.lstsq(X, y, rcond=None)[0]
                for j, c in enumerate(factor_cols):
                    betas[f"beta_{c}"] = b[j + 1] if j + 1 < len(b) else np.nan
            except (np.linalg.LinAlgError, ValueError):
                pass

            row = {
                "證券代碼": _extract_code(grp.iloc[i]["證券代碼"]),
                "年月日": int(grp.iloc[i]["date"].strftime("%Y%m%d")),
            }
            row.update(betas)
            results.append(row)

    if not results:
        for c in factor_cols:
            stock_df[f"beta_{c}"] = np.nan
        return stock_df

    load_df = pd.DataFrame(results)
    load_df["date"] = pd.to_datetime(load_df["年月日"].astype(str), format="%Y%m%d")
    return load_df


def main():
    print("=" * 55)
    print("因子特徵與載荷 CSV 產生腳本（B+C）")
    print("=" * 55)

    print("\n[1/4] 載入股價資料...")
    df = load_stock_data()
    is_stock = df["證券代碼"].str.match(_STOCK_CODE_RE, na=False)
    df = df[is_stock].copy()
    print(f"      個股 {df['證券代碼'].nunique():,} 檔，共 {len(df):,} 筆")

    print("\n[2/4] 計算因子特徵...")
    chars = compute_characters(df)

    out_cols = ["證券代碼", "年月日", "規模", "淨值市價比", "益本比", "股利殖利率", "動能", "短期反轉"]
    result = chars[["證券代碼", "date", "規模", "淨值市價比", "益本比", "股利殖利率", "動能", "短期反轉"]].copy()
    result["證券代碼"] = result["證券代碼"].apply(_extract_code)
    result["年月日"] = result["date"].dt.strftime("%Y%m%d").astype(int)
    result = result[["證券代碼", "年月日", "規模", "淨值市價比", "益本比", "股利殖利率", "動能", "短期反轉"]]

    print("\n[3/4] 載入因子報酬並計算因子載荷...")
    try:
        factor_df = load_factor_returns()
        load_df = compute_loadings(chars, factor_df)
        if len(load_df) > 0:
            beta_cols = [c for c in load_df.columns if c.startswith("beta_")]
            result = result.merge(
                load_df[["證券代碼", "年月日"] + beta_cols],
                on=["證券代碼", "年月日"],
                how="left",
            )
        else:
            for c in ["Rm_Rf", "SMB", "HML", "WML_ep", "WML_dy", "UMD", "STR"]:
                result[f"beta_{c}"] = np.nan
    except FileNotFoundError as e:
        print(f"      {e}", file=sys.stderr)
        for c in ["Rm_Rf", "SMB", "HML", "WML_ep", "WML_dy", "UMD", "STR"]:
            result[f"beta_{c}"] = np.nan

    print(f"\n[4/4] 儲存至：{OUTPUT_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"      完成！共 {len(result):,} 筆")
    print("=" * 55)


if __name__ == "__main__":
    main()
