# -*- coding: utf-8 -*-
"""
跨市場相關性與回歸分析：各國大盤（USD 總報酬）vs 美股（SB23）

輸入：international_index_decomposition_tableau.csv（由 build_intl_index_april_decomposition.py 產生）

輸出（專案根目錄）：
  intl_cross_market_corr.csv          — 全市場相關係數矩陣（daily_total_pct）
  intl_cross_market_regression.csv    — 每市場對美股的 OLS 回歸摘要
  intl_cross_market_conditional.csv   — 條件統計：當市場X「股漲+幣升」時，美股的平均表現

使用方式：
  python scripts/analyze_intl_cross_market.py
  python scripts/analyze_intl_cross_market.py --input path/to/tableau.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

US_CODE = "SB23"


def load_and_pivot(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    讀取主 CSV，回傳三個 wide DataFrame（index = date）：
      wide_total   — daily_total_pct per market
      wide_index   — daily_index_pct per market（本幣漲跌）
      wide_fx      — daily_fx_pct per market（匯率漲跌）
    """
    df = pd.read_csv(csv_path, dtype=str)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    for col in ("daily_total_pct", "daily_index_pct", "daily_fx_pct"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def pivot(value_col: str) -> pd.DataFrame:
        return (
            df.pivot_table(index="date", columns="index_code", values=value_col, aggfunc="first")
            .sort_index()
        )

    return pivot("daily_total_pct"), pivot("daily_index_pct"), pivot("daily_fx_pct")


def build_corr(wide_total: pd.DataFrame) -> pd.DataFrame:
    """全市場 Pearson 相關係數矩陣（daily_total_pct）。"""
    return wide_total.corr(method="pearson").round(4)


def build_regression(wide_total: pd.DataFrame) -> pd.DataFrame:
    """
    對每個非美市場 X，執行 OLS：
        daily_total_US = α + β × daily_total_X + ε
    回傳逐市場回歸摘要。
    """
    if US_CODE not in wide_total.columns:
        raise ValueError(f"找不到美股欄位 {US_CODE}，請確認 CSV 內容")

    us = wide_total[US_CODE]
    rows = []

    for code in wide_total.columns:
        if code == US_CODE:
            continue
        x_raw = wide_total[code]
        mask = us.notna() & x_raw.notna()
        us_m, x_m = us[mask], x_raw[mask]
        n = int(mask.sum())
        if n < 20:
            rows.append({"index_code": code, "n_obs": n, "note": "樣本不足"})
            continue

        # OLS with constant
        X = sm.add_constant(x_m.values)
        model = sm.OLS(us_m.values, X).fit()

        alpha, beta = float(model.params[0]), float(model.params[1])
        p_alpha, p_beta = float(model.pvalues[0]), float(model.pvalues[1])
        r2 = float(model.rsquared)
        t_beta = float(model.tvalues[1])

        # 相關係數
        corr = float(us_m.corr(x_m))

        rows.append({
            "index_code":   code,
            "n_obs":        n,
            "corr_with_us": round(corr, 4),
            "alpha":        round(alpha, 6),
            "beta":         round(beta, 6),
            "t_stat_beta":  round(t_beta, 4),
            "p_value_beta": round(p_beta, 4),
            "p_value_alpha":round(p_alpha, 4),
            "r_squared":    round(r2, 4),
            "interpretation": (
                "顯著正向（市場同步）" if p_beta < 0.05 and beta > 0 else
                "顯著負向（反向）"     if p_beta < 0.05 and beta < 0 else
                "不顯著"
            ),
        })

    return pd.DataFrame(rows)


def build_conditional(
    wide_total: pd.DataFrame,
    wide_index: pd.DataFrame,
    wide_fx: pd.DataFrame,
) -> pd.DataFrame:
    """
    條件分析：對每個非美市場 X，分四個情境統計美股當日平均報酬：
      1. 股漲 + 幣升（cum_cross 方向正）
      2. 股漲 + 幣貶
      3. 股跌 + 幣升
      4. 股跌 + 幣貶
    """
    if US_CODE not in wide_total.columns:
        raise ValueError(f"找不到美股欄位 {US_CODE}")

    us = wide_total[US_CODE]
    rows = []

    scenarios = {
        "股漲_幣升": (lambda idx, fx: (idx > 0) & (fx > 0)),
        "股漲_幣貶": (lambda idx, fx: (idx > 0) & (fx < 0)),
        "股跌_幣升": (lambda idx, fx: (idx < 0) & (fx > 0)),
        "股跌_幣貶": (lambda idx, fx: (idx < 0) & (fx < 0)),
    }

    for code in wide_total.columns:
        if code == US_CODE:
            continue
        if code not in wide_index.columns or code not in wide_fx.columns:
            continue

        idx_col = wide_index[code]
        fx_col  = wide_fx[code]

        row: dict = {"index_code": code}
        for label, cond_fn in scenarios.items():
            mask = cond_fn(idx_col, fx_col) & us.notna()
            n = int(mask.sum())
            if n == 0:
                row[f"{label}_n"]           = 0
                row[f"{label}_us_mean_pct"] = ""
                row[f"{label}_us_pos_rate"] = ""
            else:
                us_sub = us[mask]
                row[f"{label}_n"]           = n
                row[f"{label}_us_mean_pct"] = round(float(us_sub.mean()), 4)
                row[f"{label}_us_pos_rate"] = round(float((us_sub > 0).mean()), 4)

        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="跨市場相關性與回歸分析")
    parser.add_argument(
        "--input", type=str, default="",
        help="主 CSV 路徑（預設：專案根目錄 international_index_decomposition_tableau.csv）",
    )
    args = parser.parse_args()

    here = Path(__file__).resolve().parent   # 指數儀錶板/
    csv_path = Path(args.input) if args.input else here / "international_index_decomposition_tableau.csv"

    if not csv_path.is_file():
        raise SystemExit(f"找不到輸入檔：{csv_path}\n請先執行 build_intl_index_april_decomposition.py")

    print(f"讀取：{csv_path}")
    wide_total, wide_index, wide_fx = load_and_pivot(csv_path)
    print(f"  市場：{list(wide_total.columns)}")
    print(f"  日期：{wide_total.index[0]} ～ {wide_total.index[-1]}（{len(wide_total)} 個交易日）")

    # 1. 相關矩陣
    corr_df = build_corr(wide_total)
    corr_path = here / "intl_cross_market_corr.csv"
    corr_df.to_csv(corr_path, encoding="utf-8-sig")
    print(f"\n[1/3] 相關係數矩陣：{corr_path}")

    # 2. OLS 回歸
    reg_df = build_regression(wide_total)
    reg_path = here / "intl_cross_market_regression.csv"
    reg_df.to_csv(reg_path, index=False, encoding="utf-8-sig")
    print(f"[2/3] OLS 回歸摘要：{reg_path}")
    print(reg_df[["index_code", "corr_with_us", "beta", "p_value_beta", "r_squared", "interpretation"]].to_string(index=False))

    # 3. 條件統計
    cond_df = build_conditional(wide_total, wide_index, wide_fx)
    cond_path = here / "intl_cross_market_conditional.csv"
    cond_df.to_csv(cond_path, index=False, encoding="utf-8-sig")
    print(f"\n[3/3] 條件統計（股漲/跌 × 幣升/貶 → 美股表現）：{cond_path}")

    # 印出重點：「股漲+幣升」時美股平均
    focus_cols = ["index_code", "股漲_幣升_n", "股漲_幣升_us_mean_pct", "股漲_幣升_us_pos_rate"]
    print("\n  [股漲 + 幣升] 情境下，美股（SB23）日均報酬：")
    print(cond_df[focus_cols].to_string(index=False))


if __name__ == "__main__":
    main()
