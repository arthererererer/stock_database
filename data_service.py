"""
data_service.py
資料存取層 — 目前讀取 CSV，未來可替換為 API 串接，只需修改此檔。
"""

import math
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

# ── 資料來源路徑（切換 API 時改這裡）──────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SECTOR_LIST_CSV = BASE_DIR / "Variable_setting" / "類股清單.csv"
STOCK_MARKET_CSV = BASE_DIR / "Variable_setting" / "股票市場別.csv"
DATA_DIR = BASE_DIR / "All_Data" / "日資料" / "大盤統計" / "大盤統計資訊"
# 由大盤統計衍生、與原始 TEJ 匯出檔分開存放（不覆寫 大盤統計資訊 內檔案）
UNIFIED_BREADTH_CSV = BASE_DIR / "All_Data" / "日資料" / "大盤統計" / "合併廣度_上市櫃興櫃.csv"
MARKET_AMP_JSON = BASE_DIR / "All_Data" / "事件資料" / "市場振幅比例.json"
STOCK_PERSIST_PROB_CSV = BASE_DIR / "All_Data" / "事件資料" / "股票持續性機率.csv"

# 數值欄位清單
NUMERIC_COLS = [
    "成交金額", "成交數量", "成交筆數",
    "總委買數量", "總委買筆數", "總委賣數量", "總委賣筆數",
    "漲停委買數量", "漲停委買筆數", "漲停委賣數量", "漲停委賣筆數",
    "跌停委買數量", "跌停委買筆數", "跌停委賣數量", "跌停委賣筆數",
    "上漲家數", "下跌家數", "持平家數", "未成交家數", "漲停家數", "跌停家數",
]

# 標的顯示名稱對照
SECURITY_LABELS = {
    "OTC992 上櫃-股票": "上櫃",
    "REG991 興櫃-一般版": "興櫃",
    "Y99992 上市-股票": "上市",
}

# 合併廣度 B 之滾動標準差 σ_t = std(B_{t-n+1},…,B_t) 的視窗長度 n（交易日）
UNIFIED_BREADTH_STD_WINDOW = 10

# σ 與振幅大比例交叉相關：API 預設滯後區間與單邊上限（交易日）
BREADTH_AMP_CORR_LAG_DEFAULT_MIN = -20
BREADTH_AMP_CORR_LAG_DEFAULT_MAX = 20
BREADTH_AMP_CORR_LAG_ABS_CAP = 60


# ── 工具函數 ────────────────────────────────────────────────────────────

def _clean(v):
    """將 NaN / Inf 轉為 None，供 JSON 序列化。"""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _clean_list(lst: list) -> list:
    return [_clean(x) for x in lst]


def _rolling_std_last_n_valid(s: pd.Series, n: int) -> pd.Series:
    """
    對序列 s 逐日計算「最近 n 個有效（非 NaN）數值」的樣本標準差（ddof=1）。
    廣度 B 缺值之日不納入視窗；當日若 B 為 NaN，仍可用此前已累積之 n 個有效 B 輸出 σ（若已滿 n 個）。
    未滿 n 個有效值前回傳 NaN。
    """
    if n < 1:
        raise ValueError("n 須 >= 1")
    arr = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    m = len(arr)
    out = np.empty(m, dtype=float)
    out[:] = np.nan
    buf: list[float] = []
    for i in range(m):
        v = arr[i]
        if not math.isnan(v):
            buf.append(float(v))
            if len(buf) > n:
                buf.pop(0)
        if len(buf) == n:
            out[i] = float(np.std(buf, ddof=1))
    return pd.Series(out, index=s.index)


def _load_stock_market_map() -> dict[str, str]:
    """
    可選：Variable_setting/股票市場別.csv
    欄位：證券代碼（四位或「代碼 名稱」）、市場（TSE=上市 / OTC=上櫃，大小寫不拘）
    若檔案不存在或無效則回傳空 dict（三大法人僅能顯示全市場合計）。
    """
    if not STOCK_MARKET_CSV.is_file():
        return {}
    try:
        raw = pd.read_csv(STOCK_MARKET_CSV, dtype=str, encoding="utf-8-sig")
    except Exception:
        try:
            raw = pd.read_csv(STOCK_MARKET_CSV, dtype=str, encoding="utf-8")
        except Exception:
            return {}
    if raw.empty:
        return {}
    # 欄位名容錯
    code_col = None
    mkt_col = None
    for c in raw.columns:
        cs = str(c).strip()
        if cs in ("證券代碼", "代碼", "code"):
            code_col = c
        if cs in ("市場", "上市別", "market", "tse_otc"):
            mkt_col = c
    if code_col is None:
        code_col = raw.columns[0]
    if mkt_col is None or mkt_col == code_col:
        if len(raw.columns) < 2:
            return {}
        mkt_col = raw.columns[1]
    out: dict[str, str] = {}
    for _, row in raw.iterrows():
        cell = row.get(code_col)
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            continue
        full = str(cell).strip()
        m = re.match(r"^(\d{4})\b", full)
        if not m:
            continue
        code = m.group(1)
        mv = row.get(mkt_col)
        if mv is None or (isinstance(mv, float) and pd.isna(mv)):
            continue
        tag = str(mv).strip().upper()
        if tag in ("TSE", "上市", "TWSE"):
            out[code] = "TSE"
        elif tag in ("OTC", "上櫃", "TPEx", "TPEX"):
            out[code] = "OTC"
    return out


def _daily_returns_to_cumulative_pct(values: list) -> list:
    """日報酬率％序列轉為自區間起始之複利累積報酬率％；缺值日不參與複利且該日為 null。"""
    w = 1.0
    out: list = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if math.isnan(x) or math.isinf(x):
            out.append(None)
            continue
        w *= 1.0 + x / 100.0
        out.append(_clean((w - 1.0) * 100.0))
    return out


def _to_int(v):
    try:
        f = float(v)
        return None if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None


# ── 資料載入 ────────────────────────────────────────────────────────────

def load_all_data() -> pd.DataFrame:
    """
    讀取 DATA_DIR 內所有 CSV，依檔名（時間戳記）排序後合併。
    若同一（證券代碼, 年月日）在多個檔案中出現，保留最新檔案的資料。
    """
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到任何 CSV 檔案於：{DATA_DIR}")

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}")

    if not dfs:
        raise ValueError("所有 CSV 均讀取失敗")

    combined = pd.concat(dfs, ignore_index=True)
    combined["年月日"] = combined["年月日"].astype(str).str.strip()
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()

    # 去重：保留最新檔案的紀錄
    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    # 轉換數值欄位
    for col in NUMERIC_COLS:
        if col in combined.columns:
            combined[col] = pd.to_numeric(
                combined[col].str.replace(",", "", regex=False), errors="coerce"
            )

    # 日期欄位
    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined.sort_values(["date", "證券代碼"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    try:
        p = export_unified_breadth_csv(combined)
        if p:
            print(f"[資訊] 已更新合併廣度 CSV：{p}")
    except OSError as e:
        print(f"[警告] 合併廣度 CSV 寫入失敗：{e}")

    return combined


# ── 查詢函數 ────────────────────────────────────────────────────────────

def get_meta(df: pd.DataFrame) -> dict:
    return {
        "date_range": {
            "min": df["date"].min().strftime("%Y-%m-%d"),
            "max": df["date"].max().strftime("%Y-%m-%d"),
        },
        "securities": sorted(df["證券代碼"].unique().tolist()),
        "security_labels": SECURITY_LABELS,
    }


def _calc_percentile(sec_sorted: pd.DataFrame, target_date) -> float | None:
    """計算 target_date 當日成交金額在滾動一年中的百分位。"""
    one_year_ago = target_date - pd.DateOffset(years=1)
    row = sec_sorted[sec_sorted["date"] == target_date]
    if row.empty:
        return None
    val = row["成交金額"].values[0]
    if pd.isna(val):
        return None
    win = sec_sorted[
        (sec_sorted["date"] >= one_year_ago) & (sec_sorted["date"] <= target_date)
    ]["成交金額"].dropna()
    if win.empty:
        return None
    return round(float((win < val).sum() / len(win) * 100), 1)


def get_gauge_data(df: pd.DataFrame) -> list:
    """
    各標的：最新日成交金額在滾動一年資料中的百分位數，附帶四期比較。
    """
    latest_date = df["date"].max()
    one_year_ago = latest_date - pd.DateOffset(years=1)
    result = []

    for code in sorted(df["證券代碼"].unique()):
        sec = df[df["證券代碼"] == code].sort_values("date").reset_index(drop=True)
        window = sec[sec["date"] >= one_year_ago]["成交金額"].dropna()
        latest_row = sec[sec["date"] == latest_date]

        if latest_row.empty or window.empty:
            continue

        latest_val = latest_row["成交金額"].values[0]
        pct = float((window < latest_val).sum() / len(window) * 100)

        # 四期比較：當日、前一交易日、一週前（-5）、一個月前（-20）
        latest_idx = sec[sec["date"] == latest_date].index[0]
        comparisons = []
        for lbl, offset in [("當日", 0), ("前一交易日", -1), ("一週前", -5), ("一個月前", -20)]:
            idx = latest_idx + offset
            if 0 <= idx < len(sec):
                d = sec.loc[idx, "date"]
                p = _calc_percentile(sec, d)
                comparisons.append({
                    "label": lbl,
                    "date": d.strftime("%Y/%m/%d"),
                    "percentile": p,
                })
            else:
                comparisons.append({"label": lbl, "date": None, "percentile": None})

        result.append({
            "code": code,
            "label": SECURITY_LABELS.get(code, code),
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "latest_amount": _to_int(latest_val),
            "percentile": round(pct, 1),
            "one_year_min": _to_int(window.min()),
            "one_year_max": _to_int(window.max()),
            "one_year_median": _to_int(window.median()),
            "one_year_count": int(len(window)),
            "comparisons": comparisons,
        })

    return result


def _unified_breadth_daily(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    上市＋上櫃＋興櫃：按交易日加總家數，計算廣度 B 與滾動標準差。
    回傳欄位：date, 上漲家數, 下跌家數, 持平家數, 合併總家數, 廣度震盪, 滾動標準差
    """
    need = ["上漲家數", "下跌家數", "持平家數"]
    if df.empty or not all(c in df.columns for c in need):
        return None
    daily = df.groupby("date", sort=True)[need].sum().reset_index()
    daily["合併總家數"] = daily["上漲家數"] + daily["下跌家數"] + daily["持平家數"]
    tot = daily["合併總家數"].replace(0, float("nan"))
    daily["廣度震盪"] = (daily["上漲家數"] - daily["下跌家數"]) / tot * 100
    w = UNIFIED_BREADTH_STD_WINDOW
    daily["滾動標準差"] = _rolling_std_last_n_valid(daily["廣度震盪"], w)
    return daily


def export_unified_breadth_csv(df: pd.DataFrame) -> str | None:
    """
    將「市場廣度震盪指標」B 與「合併廣度 N 日滾動標準差」寫入 UNIFIED_BREADTH_CSV（UTF-8-BOM）。
    僅三欄：年月日、市場廣度震盪指標、合併廣度_{N}日滾動標準差（N 見 UNIFIED_BREADTH_STD_WINDOW）。
    """
    daily = _unified_breadth_daily(df)
    if daily is None or daily.empty:
        return None
    n = UNIFIED_BREADTH_STD_WINDOW
    col_sigma = f"合併廣度_{n}日滾動標準差"
    out = pd.DataFrame({
        "年月日": daily["date"].dt.strftime("%Y%m%d"),
        "市場廣度震盪指標": daily["廣度震盪"].round(6),
        col_sigma: daily["滾動標準差"].round(6),
    })
    UNIFIED_BREADTH_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(UNIFIED_BREADTH_CSV, index=False, encoding="utf-8-sig")
    return str(UNIFIED_BREADTH_CSV)


def _compute_unified_breadth_oscillator(filtered: pd.DataFrame) -> dict:
    """
    不區分上市／上櫃／興櫃：將同日各證券代碼之上漲、下跌、持平家數加總後計算廣度震盪。
    """
    w = UNIFIED_BREADTH_STD_WINDOW
    daily = _unified_breadth_daily(filtered)
    if daily is None:
        return {
            "label": "上市＋上櫃＋興櫃",
            "dates": [],
            "廣度震盪": [],
            "滾動標準差": [],
            "滾動標準差視窗": w,
        }

    return {
        "label": "上市＋上櫃＋興櫃",
        "dates": daily["date"].dt.strftime("%Y-%m-%d").tolist(),
        "廣度震盪": _clean_list(daily["廣度震盪"].tolist()),
        "滾動標準差": _clean_list(daily["滾動標準差"].tolist()),
        "滾動標準差視窗": w,
    }


def _classify_return_bucket(r: float, limit_txt: str) -> str | None:
    """單日報酬率％分桶（漲跌停優先，其次以門檻切分）。"""
    if math.isnan(r):
        return None
    t = (limit_txt or "").strip()
    if "漲停" in t:
        return "limit_up"
    if "跌停" in t:
        return "limit_down"
    if not t or t.lower() == "nan":
        if r >= 9.49:
            return "limit_up"
        if r <= -9.49:
            return "limit_down"
    if r > 5:
        return "gt5_up"
    if r > 2:
        return "btw_2_5_up"
    if r > 0:
        return "btw_0_2_up"
    if abs(r) < 1e-9:
        return "flat"
    if r >= -2:
        return "btw_0_2_down"
    if r >= -5:
        return "btw_2_5_down"
    return "gt5_down"


CHANGE_DIST_ORDER = [
    "limit_up", "gt5_up", "btw_2_5_up", "btw_0_2_up", "flat",
    "btw_0_2_down", "btw_2_5_down", "gt5_down", "limit_down",
]
CHANGE_DIST_LABELS = [
    "漲停", ">5%", "2～5%", "0～2%(漲)", "平盤",
    "0～2%(跌)", "2～5%(跌)", ">5%(跌)", "跌停",
]


def get_change_distribution_latest(price_df: pd.DataFrame) -> dict | None:
    """
    以 TEJ 股價資料庫「最新交易日」之普通股（證券代碼為四位數＋名稱）計算漲跌幅區間家數。
    漲跌停優先讀取「漲跌停」欄位；若無該欄則以 |報酬率％|≥9.49% 近似。
    """
    if price_df is None or price_df.empty or "報酬率％" not in price_df.columns:
        return None

    latest = price_df["date"].max()
    day = price_df[price_df["date"] == latest]
    mask = day["證券代碼"].astype(str).str.match(r"^\d{4} ", na=False)
    day = day.loc[mask]
    if day.empty:
        return None

    has_lim_col = "漲跌停" in day.columns
    buckets = {k: 0 for k in CHANGE_DIST_ORDER}

    for _, row in day.iterrows():
        raw_r = row["報酬率％"]
        try:
            r = float(raw_r)
        except (TypeError, ValueError):
            continue
        if math.isnan(r):
            continue
        lim = ""
        if has_lim_col:
            v = row["漲跌停"]
            lim = "" if pd.isna(v) else str(v).strip()
        cat = _classify_return_bucket(r, lim)
        if cat:
            buckets[cat] += 1

    adv = (
        buckets["limit_up"] + buckets["gt5_up"]
        + buckets["btw_2_5_up"] + buckets["btw_0_2_up"]
    )
    dec = (
        buckets["limit_down"] + buckets["gt5_down"]
        + buckets["btw_2_5_down"] + buckets["btw_0_2_down"]
    )
    fl = buckets["flat"]

    return {
        "status": "ok",
        "date": latest.strftime("%Y-%m-%d"),
        "labels": CHANGE_DIST_LABELS,
        "counts": [buckets[k] for k in CHANGE_DIST_ORDER],
        "advancing": adv,
        "flat": fl,
        "declining": dec,
    }


def get_timeseries_data(df: pd.DataFrame, start_date: str = None, end_date: str = None) -> dict:
    """
    各標的的時序資料，供 `/api/timeseries` 回傳；首頁主要使用漲跌比例、廣度等欄位繪圖，並含成交金額與委買委賣比等可供外部沿用。
    """
    filtered = df.copy()
    if start_date:
        filtered = filtered[filtered["date"] >= pd.to_datetime(start_date)]
    if end_date:
        filtered = filtered[filtered["date"] <= pd.to_datetime(end_date)]

    result = {}
    for code in sorted(filtered["證券代碼"].unique()):
        sec = filtered[filtered["證券代碼"] == code].copy().reset_index(drop=True)

        total = (sec["上漲家數"] + sec["持平家數"] + sec["下跌家數"]).replace(0, float("nan"))
        sell = sec["總委賣數量"].replace(0, float("nan"))
        limit_down = sec["跌停家數"].replace(0, float("nan"))

        ma5 = sec["成交金額"].rolling(5, min_periods=1).mean()
        ma20 = sec["成交金額"].rolling(20, min_periods=1).mean()

        # 歷史百分位帶（使用全資料、非僅篩選範圍，確保帶狀基準穩定）
        all_sec = df[df["證券代碼"] == code]["成交金額"]
        p20 = float(all_sec.quantile(0.2))
        p50 = float(all_sec.quantile(0.5))
        p80 = float(all_sec.quantile(0.8))

        result[code] = {
            "label": SECURITY_LABELS.get(code, code),
            "dates": sec["date"].dt.strftime("%Y-%m-%d").tolist(),
            # 成交金額
            "成交金額": _clean_list(sec["成交金額"].tolist()),
            "成交金額_MA5": _clean_list(ma5.tolist()),
            "成交金額_MA20": _clean_list(ma20.tolist()),
            "成交金額_P20": p20,
            "成交金額_P50": p50,
            "成交金額_P80": p80,
            # 漲跌比例
            "上漲比例": _clean_list((sec["上漲家數"] / total * 100).tolist()),
            "下跌比例": _clean_list((sec["下跌家數"] / total * 100).tolist()),
            "漲停比例": _clean_list((sec["漲停家數"] / total * 100).tolist()),
            "跌停比例": _clean_list((sec["跌停家數"] / total * 100).tolist()),
            # 委買委賣力道比
            "委買委賣比": _clean_list((sec["總委買數量"] / sell).tolist()),
            # 廣度震盪
            "廣度震盪": _clean_list(((sec["上漲家數"] - sec["下跌家數"]) / total * 100).tolist()),
            # 漲跌停比率
            "漲跌停比": _clean_list((sec["漲停家數"] / limit_down).tolist()),
        }

    result["unified_breadth"] = _compute_unified_breadth_oscillator(filtered)
    return result


def get_capital_flow_data(df: pd.DataFrame, start_date: str = None, end_date: str = None) -> dict:
    """
    各市場成交金額佔比（堆疊面積圖用）。
    只保留三個市場同時都有資料的日期，避免某市場缺資料時顯示 100%。
    """
    filtered = df.copy()
    if start_date:
        filtered = filtered[filtered["date"] >= pd.to_datetime(start_date)]
    if end_date:
        filtered = filtered[filtered["date"] <= pd.to_datetime(end_date)]

    pivot = filtered.pivot_table(index="date", columns="證券代碼", values="成交金額", aggfunc="sum")

    # 過濾掉任一市場缺資料的日期
    all_codes = sorted(df["證券代碼"].unique())
    existing_cols = [c for c in all_codes if c in pivot.columns]
    pivot = pivot[existing_cols].dropna(subset=existing_cols)

    pct = pivot.div(pivot.sum(axis=1), axis=0) * 100

    result = {"dates": pct.index.strftime("%Y-%m-%d").tolist()}
    for col in pct.columns:
        result[col] = _clean_list([round(v, 2) if not math.isnan(v) else None for v in pct[col].tolist()])

    return result


def get_market_amp_data(start_date: str = None, end_date: str = None) -> dict | None:
    """
    讀取 market amp JSON（由報告 a 產生時寫出），供大盤監控區振幅大個股比例圖使用。
    若檔不存在則回傳 None。
    """
    if not MARKET_AMP_JSON.exists():
        return None
    try:
        import json
        with open(MARKET_AMP_JSON, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]
    df = df.sort_values("date").reset_index(drop=True)
    return {
        "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        "amp_big_pct": _clean_list((df["amp_big_pct"] * 100).tolist()),
        "mkt_hi90": _clean_list((df["mkt_hi90"] * 100).tolist()),
        "mkt_lo10": _clean_list((df["mkt_lo10"] * 100).tolist()),
    }


def _breadth_amp_lag_label(k: int) -> str:
    if k == 0:
        return "t"
    if k > 0:
        return f"t+{k}"
    return f"t{k}"


def get_breadth_sigma_amp_correlation(
    df: pd.DataFrame,
    start_date: str = None,
    end_date: str = None,
    *,
    lag_min: int | None = None,
    lag_max: int | None = None,
    use_full_sample: bool = False,
) -> dict:
    """
    合併廣度滾動標準差 σ_t（與 unified_breadth 相同定義）與「每日振幅大個股比例」P_t
    （報告 a 產出之 market amp JSON）的皮爾森相關係數。

    滯後 k（交易日）：計算 corr(σ_t, P_{t+k})。
    - k = 0：同日
    - k > 0：振幅比例落後 σ 之 k 日（即 σ 領先）
    - k < 0：振幅比例領先 σ 之 |k| 日

    use_full_sample=True 時忽略 start_date／end_date，改用大盤統計與振幅 JSON 之全部交集。
    僅使用兩邊皆有效且日期交集之列；各滯後之有效配對數可能不同。
    """
    if not MARKET_AMP_JSON.exists():
        return {
            "status": "no_data",
            "message": "請先產生報告 a 以產生市場振幅資料（市場振幅比例.json）",
        }
    try:
        import json as _json
        with open(MARKET_AMP_JSON, encoding="utf-8") as f:
            rows = _json.load(f)
    except Exception:
        return {"status": "no_data", "message": "無法讀取市場振幅比例.json"}

    if not rows:
        return {"status": "no_data", "message": "市場振幅比例.json 為空"}

    cap = int(BREADTH_AMP_CORR_LAG_ABS_CAP)
    lo = int(BREADTH_AMP_CORR_LAG_DEFAULT_MIN if lag_min is None else lag_min)
    hi = int(BREADTH_AMP_CORR_LAG_DEFAULT_MAX if lag_max is None else lag_max)
    lo = max(-cap, min(cap, lo))
    hi = max(-cap, min(cap, hi))
    if lo > hi:
        lo, hi = hi, lo

    filtered = df.copy()
    if not use_full_sample:
        if start_date:
            filtered = filtered[filtered["date"] >= pd.to_datetime(start_date)]
        if end_date:
            filtered = filtered[filtered["date"] <= pd.to_datetime(end_date)]

    daily = _unified_breadth_daily(filtered)
    if daily is None or daily.empty:
        return {"status": "no_data", "message": "無合併廣度資料"}

    amp_df = pd.DataFrame(rows)
    amp_df["date"] = pd.to_datetime(amp_df["date"], errors="coerce")
    amp_df = amp_df.dropna(subset=["date", "amp_big_pct"])
    if not use_full_sample:
        if start_date:
            amp_df = amp_df[amp_df["date"] >= pd.to_datetime(start_date)]
        if end_date:
            amp_df = amp_df[amp_df["date"] <= pd.to_datetime(end_date)]

    merged = daily.merge(amp_df[["date", "amp_big_pct"]], on="date", how="inner").sort_values("date")
    merged = merged.rename(columns={"滾動標準差": "sigma", "amp_big_pct": "amp_pct"})
    merged["amp_pct"] = merged["amp_pct"].astype(float) * 100.0

    if merged.empty:
        return {"status": "no_data", "message": "廣度與振幅比例無交集日期"}

    sigma = merged["sigma"]
    amp = merged["amp_pct"]
    out_rows = []
    for k in range(lo, hi + 1):
        y = amp.shift(-k)
        pair = pd.DataFrame({"x": sigma, "y": y}).dropna()
        n = int(len(pair))
        r = None
        if n >= 3:
            c = pair["x"].corr(pair["y"], method="pearson")
            r = float(c) if c == c else None
        out_rows.append({"label": _breadth_amp_lag_label(k), "lag": k, "pearson_r": r, "n": n})

    dmin = merged["date"].min()
    dmax = merged["date"].max()
    n_win = int(UNIFIED_BREADTH_STD_WINDOW)

    return {
        "status": "ok",
        "method": "pearson",
        "definition": (
            f"σ_t 為合併廣度 B 之最近 {n_win} 個有效交易日樣本標準差（百分點）；"
            "P_t 為振幅大個股比例（%）。滯後 k：corr(σ_t, P_{t+k})，k 為交易日。"
        ),
        "unified_breadth_window": n_win,
        "intersection_trading_days": int(len(merged)),
        "full_sample": bool(use_full_sample),
        "lag_range": {"min": lo, "max": hi},
        "date_range": {
            "start": dmin.strftime("%Y-%m-%d"),
            "end": dmax.strftime("%Y-%m-%d"),
        },
        "lags": out_rows,
    }


# ════════════════════════════════════════════════════════════════════════
# 國際股市模組
# ════════════════════════════════════════════════════════════════════════

INTL_INDEX_DIR = BASE_DIR / "All_Data" / "日資料" / "國際股價指數"
FX_DIR = BASE_DIR / "All_Data" / "日資料" / "國內銀行利率(日)_國內銀行匯率"

# 銀行匯率欄位（TWD/外幣，即每1單位外幣兌多少台幣）
FX_COLUMNS: dict[str, tuple[str, str]] = {
    'USD': ('美元即期買入', '美元即期賣出'),
    'AUD': ('澳幣買入',     '澳幣賣出'),
    'CAD': ('加拿大幣買入', '加拿大幣賣出'),
    'CNY': ('人民幣買入',   '人民幣賣出'),
    'HKD': ('港幣買入',     '港幣賣出'),
    'KRW': ('韓元買入',     '韓元賣出'),
    'ZAR': ('南非幣買入',   '南非幣賣出'),
    'CHF': ('瑞士法郎買入', '瑞士法郎賣出'),
    'SGD': ('新加坡幣買入', '新加坡幣賣出'),
    'GBP': ('英磅買入',     '英磅賣出'),
    'JPY': ('日圓買入',     '日圓賣出'),
    'EUR': ('歐元買入',     '歐元賣出'),
}

# 指數代碼 → 計價貨幣
# 'LOCAL' = MSCI 本幣加權（已剔除匯率）；'TWD' = 新台幣；其餘均在 FX_COLUMNS 中
INDEX_CURRENCY_MAP: dict[str, str] = {
    # ── 台灣 TWD ──────────────────────────────────────────────────────
    'SB01': 'TWD', 'SB03': 'TWD', 'OC72': 'TWD',
    # ── 日本 JPY ──────────────────────────────────────────────────────
    'SB04': 'JPY', 'SB24': 'JPY',
    # ── 香港 HKD ──────────────────────────────────────────────────────
    'SB11': 'HKD', 'SB12': 'HKD',
    # ── 韓國 KRW ──────────────────────────────────────────────────────
    'SB10': 'KRW', 'SB1201': 'KRW',
    # ── 中國 CNY ──────────────────────────────────────────────────────
    'SB64': 'CNY', 'SB65': 'CNY', 'SB66': 'CNY', 'SB6603': 'CNY',
    'SB67': 'CNY', 'SB68': 'CNY', 'SB69': 'CNY',
    'SB6902': 'CNY', 'SB6903': 'CNY', 'SB6904': 'CNY',
    'SB6905': 'CNY', 'SB6906': 'CNY',
    # ── 新加坡 SGD ────────────────────────────────────────────────────
    'SB07': 'SGD', 'SB27': 'SGD',
    # ── 澳洲 AUD ──────────────────────────────────────────────────────
    'SB2501': 'AUD', 'SB2502': 'AUD', 'SB2503': 'AUD',
    # ── 英國 GBP ──────────────────────────────────────────────────────
    'SB16': 'GBP',
    # ── 歐元區 EUR ────────────────────────────────────────────────────
    'SB08':   'EUR',   # 德國 DAX
    'SB75':   'EUR',   # 法國 CAC 40
    'SB28':   'EUR',   # 荷蘭 AEX
    'SB3301': 'EUR',   # 義大利 FTSE MIB
    'SB3302': 'EUR',
    'SB1080': 'EUR',   # 奧地利 ATX
    'SB1082': 'EUR',   # 芬蘭 OMX Helsinki
    'SB93':   'EUR',   # 希臘 ASE
    'SB9303': 'EUR',   # 葡萄牙 PSI
    'SB83':   'EUR',   # 盧森堡 LuxX
    'SB8302': 'EUR',
    'SB92':   'EUR',   # 歐洲 STOXX 600
    'SB7904': 'EUR',   # MSCI AC World EUR
    'SB7936': 'EUR',   # MSCI LatAm EUR
    'SB7945': 'EUR',   # MSCI 中東 EUR
    'SB7949': 'EUR',   # MSCI DM World EUR
    'SB7953': 'EUR',   # MSCI Dev 除日本 EUR
    'SB7956': 'EUR',   # MSCI Dev Europe EUR
    'SB7959': 'EUR',   # MSCI Frontier EUR
    'SB7962': 'EUR',   # MSCI 台灣 EUR
    'SB9902': 'EUR',   # MSCI 北美 EUR
    'SB9905': 'EUR',   # MSCI 歐洲 EUR
    'SB9908': 'EUR',   # MSCI 新興 EUR
    'SB9911': 'EUR',   # MSCI 亞太中日 EUR
    # ── 瑞士 CHF ──────────────────────────────────────────────────────
    'SB72': 'CHF',
    # ── 加拿大 CAD ────────────────────────────────────────────────────
    'SB14': 'CAD', 'SB96': 'CAD', 'SB9602': 'CAD',
    # ── 南非 ZAR ──────────────────────────────────────────────────────
    'SB15': 'ZAR',
    # ── 美國 USD ──────────────────────────────────────────────────────
    'SB22': 'USD', 'SB23': 'USD',
    'SB56': 'USD', 'SB5602': 'USD', 'SB57': 'USD', 'SB60': 'USD',
    # ── MSCI Local（已為各國本幣加權，不需另行匯率調整）────────────
    'SB79':   'LOCAL', 'SB7903': 'LOCAL', 'SB7905': 'LOCAL',
    'SB7907': 'LOCAL', 'SB7909': 'LOCAL', 'SB7911': 'LOCAL',
    'SB7915': 'LOCAL', 'SB7917': 'LOCAL', 'SB7919': 'LOCAL',
    'SB7921': 'LOCAL', 'SB7925': 'LOCAL', 'SB7937': 'LOCAL',
    'SB7946': 'LOCAL', 'SB7950': 'LOCAL', 'SB7951': 'LOCAL',
    'SB7954': 'LOCAL', 'SB7957': 'LOCAL', 'SB7960': 'LOCAL',
    'SB7974': 'LOCAL', 'SB9903': 'LOCAL', 'SB9906': 'LOCAL', 'SB9909': 'LOCAL',
    # ── MSCI USD ──────────────────────────────────────────────────────
    'SB7902': 'USD', 'SB7906': 'USD', 'SB7908': 'USD', 'SB7910': 'USD',
    'SB7912': 'USD', 'SB7916': 'USD', 'SB7918': 'USD', 'SB7920': 'USD',
    'SB7922': 'USD', 'SB7926': 'USD', 'SB7935': 'USD', 'SB7944': 'USD',
    'SB7948': 'USD', 'SB7952': 'USD', 'SB7955': 'USD', 'SB7958': 'USD',
    'SB7961': 'USD', 'SB7973': 'USD',
    'SB99':   'USD', 'SB9904': 'USD', 'SB9907': 'USD', 'SB9910': 'USD',
    'SB9917': 'USD', 'SB9918': 'USD',
}

_ASIA    = {'SB04','SB24','SB11','SB12','SB10','SB1201',
            'SB64','SB65','SB66','SB6603','SB67','SB68','SB69',
            'SB6902','SB6903','SB6904','SB6905','SB6906','SB07',
            'SB2501','SB2502','SB2503'}
_EUROPE  = {'SB08','SB75','SB28','SB3301','SB3302','SB1080','SB1082',
            'SB93','SB9303','SB83','SB8302','SB92','SB72','SB16',
            'SB27','SB15'}
_AMERICA = {'SB14','SB22','SB23','SB56','SB5602','SB57','SB60','SB9602','OC72'}
_TAIWAN  = {'SB01','SB03'}


def _intl_group(code: str) -> str:
    if code in _TAIWAN:  return '台灣'
    if code in _ASIA:    return '亞洲'
    if code in _EUROPE:  return '歐洲'
    if code in _AMERICA: return '美洲'
    if code == 'SB96':   return '美洲'
    return 'MSCI'


def _intl_name_compact(s: str) -> str:
    """比對分組用：臺→台、各種連字號統一、去空白。"""
    t = (s or "").strip().replace("臺", "台")
    for dash in (
        "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212",
        "－", "–", "—", "‧",
    ):
        t = t.replace(dash, "-")
    return t.replace(" ", "").replace("　", "")


def _intl_is_taiwan_otc_index(name: str) -> bool:
    """台灣櫃買／OTC 股價指數（TEJ 名稱可能為臺灣、櫃買指數、連字號變體等）。"""
    n = (name or "").strip()
    if "MSCI" in n.upper():
        return False
    c = _intl_name_compact(n)
    cl = c.lower()
    # 明確含台灣與 OTC
    if "台灣-otc" in cl or "台灣otc" in cl:
        return True
    if "otc股價指數" in cl:
        return True
    # 證交所習慣簡稱：櫃買指數、櫃買股價指數、櫃檯買賣…
    if "櫃買指數" in n.replace("臺", "台") or "櫃買股價指數" in n.replace("臺", "台"):
        return True
    if "櫃檯買賣" in n and "指數" in n:
        return True
    if "臺灣櫃買" in n or "台灣櫃買" in n.replace("臺", "台"):
        return True
    return False


def _intl_group_refined(code: str, name: str | None = None) -> str:
    """
    國際指數在 UI 上的分組（清單區塊標題）。
    優先依證券中文名校正少數代碼與地理直覺不符的情形。
    """
    n = (name or "").strip()
    # 台灣 OTC／櫃買指數須優先於 OC72：TEJ 可能將多檔指數標成同一代碼（如 OC72），
    # 若先判 code==OC72 會把「台灣-OTC股價指數」誤歸美洲（與臺/台、連字號無關）。
    if _intl_is_taiwan_otc_index(n):
        return "台灣"
    # 美國紐約道瓊工業平均數（TEJ 常為 OC72，台幣計價仍歸美洲）
    if code == "OC72" or "美國紐約道瓊" in n or "道瓊工業平均" in n:
        return "美洲"
    # MSCI 美國房地產信託投資基金指數等（勿與區域股指混淆）
    if "MSCI" in n and ("房地產信託" in n or "REIT" in n.upper()):
        return "MSCI"
    return _intl_group(code)


def load_fx_data() -> pd.DataFrame:
    """
    讀取銀行匯率 CSV，計算每日各幣別即期中間價（買入+賣出）/2，
    並取各行平均值。回傳以 date 為索引、各幣別代碼（USD、JPY…）為欄位的
    DataFrame；值為 TWD/外幣中間匯率（每 1 單位外幣兌多少台幣）。
    """
    csv_files = sorted(FX_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到匯率 CSV：{FX_DIR}")

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"[警告] 讀取匯率 {f.name} 失敗：{e}")

    if not dfs:
        raise ValueError("所有匯率 CSV 均讀取失敗")

    combined = pd.concat(dfs, ignore_index=True)
    combined["年月日"] = combined["年月日"].astype(str).str.strip()

    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined = combined.dropna(subset=["date"])

    series_list = []
    for ccy, (buy_col, sell_col) in FX_COLUMNS.items():
        if buy_col not in combined.columns or sell_col not in combined.columns:
            continue
        buy = pd.to_numeric(
            combined[buy_col].astype(str).str.replace(",", "", regex=False).str.strip(),
            errors="coerce",
        )
        sell = pd.to_numeric(
            combined[sell_col].astype(str).str.replace(",", "", regex=False).str.strip(),
            errors="coerce",
        )
        mid  = (buy + sell) / 2
        temp = combined[["date"]].copy()
        temp[ccy] = mid
        temp = temp.dropna(subset=[ccy])
        daily = temp.groupby("date")[ccy].mean().rename(ccy)
        series_list.append(daily)

    if not series_list:
        raise ValueError("無法從匯率 CSV 中解析任何幣別資料")

    fx_df = pd.concat(series_list, axis=1).sort_index()
    return fx_df


def load_intl_index_data() -> pd.DataFrame:
    """讀取國際股價指數 CSV，合併後回傳 DataFrame。"""
    csv_files = sorted(INTL_INDEX_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到國際股指 CSV：{INTL_INDEX_DIR}")

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}")

    if not dfs:
        raise ValueError("所有國際股指 CSV 均讀取失敗")

    combined = pd.concat(dfs, ignore_index=True)
    combined["年月日"]   = combined["年月日"].astype(str).str.strip()
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()

    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    combined["指數"] = pd.to_numeric(
        combined["指數"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    combined["date"] = pd.to_datetime(combined["年月日"], format="%Y%m%d", errors="coerce")
    combined["code"] = combined["證券代碼"].str.split().str[0]

    combined.sort_values(["date", "code"], inplace=True)
    combined.reset_index(drop=True, inplace=True)
    return combined


def get_intl_indices_meta(intl_df: pd.DataFrame) -> dict:
    """
    回傳可用的國際指數清單（僅含 INDEX_CURRENCY_MAP 中有記錄的代碼）。
    """
    seen = set()
    indices = []

    for _, row in intl_df[["code", "證券代碼"]].drop_duplicates("code").iterrows():
        code = row["code"]
        if code not in INDEX_CURRENCY_MAP or code in seen:
            continue
        seen.add(code)

        full = row["證券代碼"].strip()
        parts = full.split(maxsplit=1)
        name = parts[1] if len(parts) > 1 else code

        ccy   = INDEX_CURRENCY_MAP[code]
        group = _intl_group_refined(code, name)

        indices.append({
            "code":     code,
            "name":     name,
            "currency": ccy,
            "group":    group,
        })

    group_order = {"台灣": 0, "亞洲": 1, "歐洲": 2, "美洲": 3, "MSCI": 4, "其他": 5}
    indices.sort(key=lambda x: (group_order.get(x["group"], 9), x["name"]))

    return {
        "indices": indices,
        "date_range": {
            "min": intl_df["date"].min().strftime("%Y-%m-%d"),
            "max": intl_df["date"].max().strftime("%Y-%m-%d"),
        },
    }


def get_intl_chart_data(
    intl_df: pd.DataFrame,
    fx_df: pd.DataFrame,
    codes: list[str],
    start_date: str | None,
    end_date: str | None,
    base_date: str | None,
) -> dict:
    """
    回傳各指數的原始數值、本幣累積報酬率、匯率報酬率、台幣計價總報酬率。

    欄位說明：
      raw          – 指數原始數值（各國本幣計價）
      local_return – 本幣累積報酬率 (%)：(Index_t / Index_base - 1) × 100
      fx_return    – 匯率累積報酬率 (%)：(FX_t / FX_base - 1) × 100
                     FX = TWD/外幣中間匯率（正值代表外幣升值，對台灣投資人有利）
      twd_return   – 台幣計價總報酬率 (%)：
                     [(1 + local_return/100) × (1 + fx_return/100) - 1] × 100
      can_decompose – 是否有對應匯率可進行拆解
                     False：LOCAL 指數（MSCI 已剔除匯率）或 TWD 指數（無匯率風險）
    """
    base_dt  = pd.to_datetime(base_date)  if base_date  else intl_df["date"].max()
    start_dt = pd.to_datetime(start_date) if start_date else intl_df["date"].min()
    end_dt   = pd.to_datetime(end_date)   if end_date   else intl_df["date"].max()

    result: dict = {}

    for raw_code in codes:
        code = raw_code.strip().split()[0]
        if code not in INDEX_CURRENCY_MAP:
            continue

        sec = intl_df[intl_df["code"] == code].sort_values("date").dropna(subset=["指數"])
        if sec.empty:
            continue

        full  = sec["證券代碼"].iloc[0].strip()
        parts = full.split(maxsplit=1)
        name  = parts[1] if len(parts) > 1 else code
        ccy   = INDEX_CURRENCY_MAP[code]

        # 找基準日（基準日當天或之前最近一筆；若無則取之後第一筆）
        before = sec[sec["date"] <= base_dt]
        if not before.empty:
            base_row = before.iloc[-1]
        else:
            after = sec[sec["date"] > base_dt]
            if after.empty:
                continue
            base_row = after.iloc[0]

        base_val      = float(base_row["指數"])
        base_date_act = base_row["date"]
        if base_val == 0 or math.isnan(base_val):
            continue

        # 篩選顯示範圍
        disp = sec[(sec["date"] >= start_dt) & (sec["date"] <= end_dt)]
        if disp.empty:
            continue

        vals  = disp["指數"].astype(float).tolist()
        dates = disp["date"].dt.strftime("%Y-%m-%d").tolist()

        local_ret = [round((v / base_val - 1) * 100, 4) for v in vals]

        # ── 匯率拆解 ────────────────────────────────────────────────────
        can_decompose = False
        fx_ret  = [0.0] * len(vals)
        twd_ret = [round((v / base_val - 1) * 100, 4) for v in vals]   # 預設 = local

        if ccy not in ("LOCAL", "TWD") and ccy in FX_COLUMNS and not fx_df.empty and ccy in fx_df.columns:
            fx_series = fx_df[ccy].dropna().sort_index()
            if not fx_series.empty:
                # 找基準日 FX（向前填補：取基準日當天或之前最近值）
                fx_before_base = fx_series[fx_series.index <= base_date_act]
                if fx_before_base.empty:
                    fx_after_base = fx_series[fx_series.index > base_date_act]
                    fx_base_val = float(fx_after_base.iloc[0]) if not fx_after_base.empty else None
                else:
                    fx_base_val = float(fx_before_base.iloc[-1])

                if fx_base_val and fx_base_val != 0:
                    # 對每個顯示日期取最近 FX 值（向前填補）
                    disp_dates = disp["date"].values  # numpy datetime64 array
                    all_idx    = fx_series.index      # DatetimeIndex

                    # reindex + ffill 是最有效率的方式
                    needed_idx = pd.DatetimeIndex(disp_dates)
                    combined_idx = all_idx.union(needed_idx)
                    fx_filled = fx_series.reindex(combined_idx).ffill()
                    fx_on_dates = fx_filled.reindex(needed_idx).tolist()

                    if any(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in fx_on_dates):
                        can_decompose = True
                        fx_ret  = []
                        twd_ret = []
                        for lret, fxv in zip(local_ret, fx_on_dates):
                            if fxv is None or (isinstance(fxv, float) and math.isnan(fxv)):
                                fx_ret.append(None)
                                twd_ret.append(None)
                            else:
                                fxr = (fxv / fx_base_val - 1) * 100
                                fx_ret.append(round(fxr, 4))
                                twd_ret.append(round(((1 + lret / 100) * (1 + fxr / 100) - 1) * 100, 4))

        result[code] = {
            "name":          name,
            "currency":      ccy,
            "group":         _intl_group_refined(code, name),
            "base_date":     base_date_act.strftime("%Y-%m-%d"),
            "base_value":    round(base_val, 4),
            "can_decompose": can_decompose,
            "dates":         dates,
            "raw":           [_clean(round(v, 4)) for v in vals],
            "local_return":  [_clean(v) for v in local_ret],
            "fx_return":     [_clean(v) for v in fx_ret],
            "twd_return":    [_clean(v) for v in twd_ret],
        }

    return result


# ════════════════════════════════════════════════════════════════════════
# 個股監控模組
# ════════════════════════════════════════════════════════════════════════

STOCK_PRICE_DIR = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
CHIP_DIR = BASE_DIR / "All_Data" / "日資料" / "TEJ 籌碼資料庫"
MONTHLY_DIR = BASE_DIR / "All_Data" / "月資料" / "董監全體持股狀況"
QUARTERLY_DIR = BASE_DIR / "All_Data" / "季資料" / "以合併為主簡表(單季)-全產業"

STOCK_PRICE_NUMERIC = [
    "開盤價(元)", "最高價(元)", "最低價(元)", "收盤價(元)",
    "成交量(千股)", "成交值(千元)", "報酬率％", "週轉率％",
    "流通在外股數(千股)", "市值(百萬元)", "市值比重％",
    "本益比-TSE", "股價淨值比-TSE", "股價營收比-TEJ",
    "現金股利率", "股利殖利率-TSE", "高低價差%",
    "超額報酬(日)-大盤", "CAPM_Beta 一年",
]

CHIP_NUMERIC = [
    "外資買賣超(張)", "投信買賣超(張)", "自營買賣超(張)", "合計買賣超(張)",
    "外資買賣超日數", "投信買賣超日數", "自營買賣超日數", "法人買賣超日數",
    "外資總投資股率%", "投信持股率%", "合計持股率%",
    "融資餘額(張)", "融資買進(張)", "融資賣出(張)", "融資使用率",
    "融券餘額(張)", "融券賣出(張)", "融券使用率", "券資比",
    "融資維持率", "借券賣出餘額(張)", "借券賣出(張)",
]

MONTHLY_NUMERIC = ["董監持股%", "大股東持股(TSE)%"]


def _load_csv_dir(dir_path: Path, numeric_cols: list, key_cols: list) -> pd.DataFrame:
    """通用：讀取資料夾所有 CSV，合併去重，轉換數值欄位。"""
    csv_files = sorted(dir_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到 CSV：{dir_path}")

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"[警告] 讀取 {f.name} 失敗：{e}")

    if not dfs:
        raise ValueError(f"所有 CSV 均讀取失敗：{dir_path}")

    combined = pd.concat(dfs, ignore_index=True)
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()

    # 日期欄（年月日 或 年月）
    date_col = "年月日" if "年月日" in combined.columns else "年月"
    combined[date_col] = combined[date_col].astype(str).str.strip()

    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=key_cols, keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)

    for col in numeric_cols:
        if col in combined.columns:
            combined[col] = pd.to_numeric(
                combined[col].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )

    return combined


def load_stock_price_data() -> pd.DataFrame:
    """讀取 TEJ 股價資料庫，回傳含 date 欄的 DataFrame。"""
    df = _load_csv_dir(STOCK_PRICE_DIR, STOCK_PRICE_NUMERIC, ["證券代碼", "年月日"])
    df["date"] = pd.to_datetime(df["年月日"], format="%Y%m%d", errors="coerce")
    df.sort_values(["date", "證券代碼"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _sector_cell_to_stock_code(cell) -> str | None:
    """自類股清單儲存格解析四位數證券代碼（取字串中最後一組連續四位數）。"""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    s = str(cell).strip()
    if not s:
        return None
    found = re.findall(r"\d{4}", s)
    if not found:
        return None
    code = found[-1]
    return code if code.isdigit() else None


def load_sector_classification() -> list[dict]:
    """
    讀取 Variable_setting/類股清單.csv：第一列為各類股名稱，每欄向下為該類成分。
    回傳 [{"id": "0", "name": "上市電子", "codes": ["2330", ...]}, ...]
    """
    if not SECTOR_LIST_CSV.is_file():
        return []
    try:
        raw = pd.read_csv(SECTOR_LIST_CSV, header=0, dtype=str, encoding="utf-8-sig")
    except Exception:
        try:
            raw = pd.read_csv(SECTOR_LIST_CSV, header=0, dtype=str, encoding="utf-8")
        except Exception:
            return []
    sectors = []
    for i, col in enumerate(raw.columns):
        name = str(col).strip() or f"欄位{i}"
        seen: set[str] = set()
        codes: list[str] = []
        for val in raw[col].dropna():
            c = _sector_cell_to_stock_code(val)
            if c and c not in seen:
                seen.add(c)
                codes.append(c)
        sectors.append({"id": str(i), "name": name, "codes": codes})
    return sectors


def _latest_day_stock_index(day_df: pd.DataFrame) -> dict[str, dict]:
    """最新交易日：四位數普通股 short_code -> 報酬、市值、市值比重、完整證券代碼。"""
    out: dict[str, dict] = {}
    if day_df.empty or "證券代碼" not in day_df.columns:
        return out
    for _, row in day_df.iterrows():
        full = str(row["證券代碼"]).strip()
        m = re.match(r"^(\d{4})\s", full)
        if not m:
            continue
        code = m.group(1)
        if code in out:
            continue
        r = row["報酬率％"] if "報酬率％" in day_df.columns else None
        mcap = row["市值(百萬元)"] if "市值(百萬元)" in day_df.columns else None
        wt = row["市值比重％"] if "市值比重％" in day_df.columns else None
        try:
            rv = float(r) if r is not None and not pd.isna(r) else None
        except (TypeError, ValueError):
            rv = None
        if rv is not None and isinstance(rv, float) and (math.isnan(rv) or math.isinf(rv)):
            rv = None
        try:
            mv = float(mcap) if mcap is not None and not pd.isna(mcap) else None
        except (TypeError, ValueError):
            mv = None
        if mv is not None and isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv)):
            mv = None
        try:
            wv = float(wt) if wt is not None and not pd.isna(wt) else None
        except (TypeError, ValueError):
            wv = None
        if wv is not None and isinstance(wv, float) and (math.isnan(wv) or math.isinf(wv)):
            wv = None
        name = full.split(maxsplit=1)[1] if " " in full else code
        out[code] = {
            "full": full,
            "name": name,
            "ret": rv,
            "mcap": mv,
            "weight": wv,
        }
    return out


def get_sector_performance_bootstrap(price_df: pd.DataFrame) -> dict:
    """
    大盤監控：類股橫條圖與折線圖所需之 bootstrap。
    橫條圖僅納入成分在 TEJ 最新日有效且≥3 檔之類股；平均漲跌幅以市值前 5 檔（>5 檔時）計算。
    市值占比為該類在清單內且當日有資料之成分，其「市值比重％」加總。
    """
    sectors_def = load_sector_classification()
    if not sectors_def:
        return {"status": "no_data", "message": "找不到類股清單或無法解析（請確認 Variable_setting/類股清單.csv）"}

    need = ["報酬率％", "市值(百萬元)", "證券代碼", "date"]
    if price_df is None or price_df.empty or not all(c in price_df.columns for c in need):
        return {"status": "no_data", "message": "股價資料不足"}

    latest = price_df["date"].max()
    day = price_df[price_df["date"] == latest]
    idx = _latest_day_stock_index(day)

    sector_rows = []
    bar_candidates = []

    for sdef in sectors_def:
        members = []
        for c in sdef["codes"]:
            if c not in idx:
                continue
            inf = idx[c]
            if inf["ret"] is None or inf["mcap"] is None:
                continue
            members.append(
                {
                    "code": c,
                    "name": inf["name"],
                    "full": inf["full"],
                    "mcap": inf["mcap"],
                    "weight_pct": _clean(inf["weight"]),
                    "return_pct": _clean(round(inf["ret"], 4)),
                }
            )
        n = len(members)
        members.sort(key=lambda x: -x["mcap"])
        top5 = members[:5] if n > 5 else members
        default_codes = [x["code"] for x in top5]
        for m in members:
            m["in_default_avg"] = m["code"] in default_codes

        sum_w = 0.0
        for m in members:
            w = m.get("weight_pct")
            if w is not None and isinstance(w, (int, float)) and not (math.isnan(w) or math.isinf(w)):
                sum_w += float(w)

        avg_bar = None
        if top5:
            rets_avg = [x["return_pct"] for x in top5 if x.get("return_pct") is not None]
            avg_bar = (sum(rets_avg) / len(rets_avg)) if rets_avg else None

        row = {
            "id": sdef["id"],
            "name": sdef["name"],
            "member_count": n,
            "eligible_bar": n >= 3,
            "weight_pct_sum": _clean(round(sum_w, 4)) if n else None,
            "avg_change_bar_rule": _clean(round(avg_bar, 4)) if avg_bar is not None else None,
            "default_codes": default_codes,
            "members": members,
        }
        sector_rows.append(row)
        if n >= 3 and avg_bar is not None:
            bar_candidates.append(
                {
                    "id": sdef["id"],
                    "name": sdef["name"],
                    "weight_pct_sum": row["weight_pct_sum"],
                    "avg_change_pct": row["avg_change_bar_rule"],
                    "member_count": n,
                    "n_used_for_avg": len(top5),
                }
            )

    bar_candidates.sort(
        key=lambda x: (
            float(x["avg_change_pct"]) if x["avg_change_pct"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    top8 = bar_candidates[:8]

    stock_universe = get_stock_list(price_df)

    return {
        "status": "ok",
        "as_of": latest.strftime("%Y-%m-%d"),
        "bars": top8,
        "sectors": sector_rows,
        "stock_universe": stock_universe,
    }


def get_sector_performance_lines(
    price_df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    sector_series: list,
    stock_codes: list,
) -> dict:
    """
    依使用者勾選之類股（自選成分代碼計算當日平均報酬率％）與個股代碼，回傳區間內每日序列；
    輸出值為自區間起始之**複利累積報酬率％**（由日報酬率換算）。
    sector_series: [{"id": "3", "name": "半導體", "codes": ["2330", "2454"]}, ...]
    """
    if price_df is None or price_df.empty or "報酬率％" not in price_df.columns:
        return {"status": "no_data", "message": "無股價資料", "series": []}

    code_map = {}
    for full in price_df["證券代碼"].unique():
        sc = str(full).strip().split()[0]
        if len(sc) == 4 and sc.isdigit():
            code_map[sc] = str(full).strip()

    pf = price_df.copy()
    if start_date:
        pf = pf[pf["date"] >= pd.to_datetime(start_date)]
    if end_date:
        pf = pf[pf["date"] <= pd.to_datetime(end_date)]

    # 僅保留需要的 full 代碼列
    want_full = set()
    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        for c in block.get("codes") or []:
            c = str(c).strip()
            if c in code_map:
                want_full.add(code_map[c])
    for c in stock_codes or []:
        c = str(c).strip()
        if c in code_map:
            want_full.add(code_map[c])
    if not want_full:
        return {"status": "ok", "series": [], "dates": []}

    sub = pf[pf["證券代碼"].isin(want_full)][["date", "證券代碼", "報酬率％"]].copy()
    sub["short"] = sub["證券代碼"].astype(str).str.strip().str.split().str[0]

    dates = sorted(sub["date"].dropna().unique())
    date_strs = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]

    # short -> {date -> ret}
    by_sd: dict[tuple, float] = {}
    for _, r in sub.iterrows():
        d = r["date"]
        if pd.isna(d):
            continue
        try:
            v = float(r["報酬率％"])
        except (TypeError, ValueError):
            continue
        if math.isnan(v) or math.isinf(v):
            continue
        by_sd[(r["short"], pd.Timestamp(d).normalize())] = v

    def series_for_shorts(shorts: list[str]) -> list:
        out = []
        for d in dates:
            dn = pd.Timestamp(d).normalize()
            vals = []
            for sc in shorts:
                if sc in code_map:
                    k = (sc, dn)
                    if k in by_sd:
                        vals.append(by_sd[k])
            if vals:
                out.append(sum(vals) / len(vals))
            else:
                out.append(None)
        return out

    series_out = []
    palette_i = 0
    colors = ["#58a6ff", "#d29922", "#f85149", "#3fb950", "#bc8cff", "#39d0d8", "#e3b341", "#8b949e"]

    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        codes = [str(c).strip() for c in (block.get("codes") or []) if str(c).strip() in code_map]
        if not codes:
            continue
        sid = str(block.get("id", ""))
        sname = str(block.get("name") or sid)
        label = f"{sname}（{len(codes)}檔均）"
        vals = series_for_shorts(codes)
        color = colors[palette_i % len(colors)]
        palette_i += 1
        cum_vals = _daily_returns_to_cumulative_pct([_clean(v) for v in vals])
        series_out.append(
            {
                "kind": "sector_avg",
                "id": sid,
                "label": label,
                "dates": date_strs,
                "values": cum_vals,
                "line": {"color": color, "width": 2},
            }
        )

    for c in stock_codes or []:
        c = str(c).strip()
        if c not in code_map:
            continue
        vals = series_for_shorts([c])
        name = code_map[c].split(maxsplit=1)[1] if " " in code_map[c] else c
        color = colors[palette_i % len(colors)]
        palette_i += 1
        cum_vals = _daily_returns_to_cumulative_pct([_clean(v) for v in vals])
        series_out.append(
            {
                "kind": "stock",
                "code": c,
                "label": f"{c} {name}",
                "dates": date_strs,
                "values": cum_vals,
                "line": {"color": color, "width": 1.8, "dash": "dot"},
            }
        )

    return {
        "status": "ok",
        "dates": date_strs,
        "series": series_out,
        "metric": "cumulative_return_pct",
    }


def _institutional_summary_from_group(g: pd.DataFrame) -> dict | None:
    if g is None or g.empty:
        return None
    g2 = g.sort_values("date").copy()
    for col in ("foreign_e", "trust_e", "dealer_e"):
        g2[col] = pd.to_numeric(g2[col], errors="coerce").fillna(0.0)
    last = g2.iloc[-1]
    ld = pd.Timestamp(last["date"])
    d1 = {
        "as_of": ld.strftime("%Y-%m-%d"),
        "as_of_md": ld.strftime("%m/%d"),
        "foreign": _clean(float(last["foreign_e"])),
        "trust": _clean(float(last["trust_e"])),
        "dealer": _clean(float(last["dealer_e"])),
        "total": _clean(
            float(last["foreign_e"] + last["trust_e"] + last["dealer_e"]),
        ),
    }
    t5 = g2.tail(5)
    d5 = {
        "foreign": _clean(float(t5["foreign_e"].sum())),
        "trust": _clean(float(t5["trust_e"].sum())),
        "dealer": _clean(float(t5["dealer_e"].sum())),
        "total": _clean(
            float(
                t5["foreign_e"].sum()
                + t5["trust_e"].sum()
                + t5["dealer_e"].sum(),
            ),
        ),
    }
    return {"last_day": d1, "last_5d": d5}


def _pack_institutional_market_slice(sub: pd.DataFrame) -> dict:
    if sub is None or sub.empty:
        return {
            "dates": [],
            "foreign_bn": [],
            "trust_bn": [],
            "dealer_bn": [],
            "total_bn": [],
            "summary": None,
        }
    g = (
        sub.groupby("date", as_index=False)[["foreign_e", "trust_e", "dealer_e"]]
        .sum()
        .sort_values("date")
    )
    dates = g["date"].dt.strftime("%Y-%m-%d").tolist()
    fe = _clean_list(g["foreign_e"].tolist())
    te = _clean_list(g["trust_e"].tolist())
    de = _clean_list(g["dealer_e"].tolist())
    g_num = g.copy()
    for col in ("foreign_e", "trust_e", "dealer_e"):
        g_num[col] = pd.to_numeric(g_num[col], errors="coerce").fillna(0.0)
    totals = _clean_list(
        (g_num["foreign_e"] + g_num["trust_e"] + g_num["dealer_e"]).tolist(),
    )
    return {
        "dates": dates,
        "foreign_bn": fe,
        "trust_bn": te,
        "dealer_bn": de,
        "total_bn": totals,
        "summary": _institutional_summary_from_group(g),
    }


def get_sector_institutional_lines(
    price_df: pd.DataFrame,
    chip_df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    sector_series: list,
    stock_codes: list,
) -> dict:
    """
    與累積報酬折線相同勾選：類股為成分股當日買賣超金額（億元）之**簡單平均**，個股為單一標的。
    金額＝收盤價×買賣超(張)×1000。
    """
    note = (
        "金額為當日收盤價×買賣超張數×1000 之估算值（億元）；"
        "類股折線為成分當日簡單平均，個股為單一標的。"
    )
    empty_ok: dict = {
        "status": "ok",
        "dates": [],
        "lines": [],
        "unit": "億元",
        "note": note,
    }

    need_chip = [
        "證券代碼",
        "年月日",
        "外資買賣超(張)",
        "投信買賣超(張)",
        "自營買賣超(張)",
    ]
    need_price = ["證券代碼", "date", "收盤價(元)"]

    if price_df is None or price_df.empty:
        return {**empty_ok, "status": "no_data", "message": "無股價資料"}
    if chip_df is None or chip_df.empty:
        return {**empty_ok, "status": "no_data", "message": "無籌碼資料"}
    if not all(c in chip_df.columns for c in need_chip):
        return {**empty_ok, "status": "no_data", "message": "籌碼資料缺少法人買賣超欄位"}
    if not all(c in price_df.columns for c in need_price):
        return {**empty_ok, "status": "no_data", "message": "股價資料缺少收盤價"}

    code_map: dict[str, str] = {}
    for full in price_df["證券代碼"].unique():
        sc = str(full).strip().split()[0]
        if len(sc) == 4 and sc.isdigit():
            code_map[sc] = str(full).strip()

    want_full: set[str] = set()
    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        for c in block.get("codes") or []:
            c = str(c).strip()
            if c in code_map:
                want_full.add(code_map[c])
    for c in stock_codes or []:
        c = str(c).strip()
        if c in code_map:
            want_full.add(code_map[c])
    if not want_full:
        return empty_ok

    want_shorts = {str(f).strip().split()[0] for f in want_full}

    p = price_df[["date", "證券代碼", "收盤價(元)"]].copy()
    p["short"] = p["證券代碼"].astype(str).str.strip().str.split().str[0]
    p = p.loc[p["short"].str.match(r"^\d{4}$", na=False)]

    c = chip_df[
        ["年月日", "證券代碼", "外資買賣超(張)", "投信買賣超(張)", "自營買賣超(張)"]
    ].copy()
    c["date"] = pd.to_datetime(c["年月日"], format="%Y%m%d", errors="coerce")
    c["short"] = c["證券代碼"].astype(str).str.strip().str.split().str[0]
    c = c.loc[c["short"].str.match(r"^\d{4}$", na=False)]

    if start_date:
        t0 = pd.to_datetime(start_date)
        p = p[p["date"] >= t0]
        c = c[c["date"] >= t0]
    if end_date:
        t1 = pd.to_datetime(end_date)
        p = p[p["date"] <= t1]
        c = c[c["date"] <= t1]

    merged = pd.merge(c, p, on=["date", "short"], how="inner")
    merged = merged.loc[merged["short"].isin(want_shorts)]
    if merged.empty:
        return {**empty_ok, "message": "區間內無可對齊之籌碼與股價列"}

    px = pd.to_numeric(merged["收盤價(元)"], errors="coerce")
    ff = pd.to_numeric(merged["外資買賣超(張)"], errors="coerce")
    tf = pd.to_numeric(merged["投信買賣超(張)"], errors="coerce")
    dlr = pd.to_numeric(merged["自營買賣超(張)"], errors="coerce")
    merged = merged.assign(
        foreign_e=ff.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
        trust_e=tf.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
        dealer_e=dlr.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
    )

    daily_stock = (
        merged.groupby(["date", "short"], as_index=False)[
            ["foreign_e", "trust_e", "dealer_e"]
        ]
        .mean()
        .sort_values(["date", "short"])
    )

    dates = sorted(daily_stock["date"].dropna().unique())
    date_strs = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]

    def triple_series_for_shorts(shorts: list[str]) -> tuple[list, list, list]:
        out_f: list = []
        out_t: list = []
        out_d: list = []
        for d in dates:
            rows = daily_stock[
                (daily_stock["date"] == d)
                & (daily_stock["short"].isin(shorts))
            ]
            if rows.empty:
                out_f.append(None)
                out_t.append(None)
                out_d.append(None)
            else:
                out_f.append(_clean(float(rows["foreign_e"].mean())))
                out_t.append(_clean(float(rows["trust_e"].mean())))
                out_d.append(_clean(float(rows["dealer_e"].mean())))
        return out_f, out_t, out_d

    lines_out: list = []
    palette_i = 0
    colors = [
        "#58a6ff",
        "#d29922",
        "#f85149",
        "#3fb950",
        "#bc8cff",
        "#39d0d8",
        "#e3b341",
        "#8b949e",
    ]

    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        codes = [
            str(x).strip()
            for x in (block.get("codes") or [])
            if str(x).strip() in code_map
        ]
        if not codes:
            continue
        sid = str(block.get("id", ""))
        sname = str(block.get("name") or sid)
        label = f"{sname}（{len(codes)}檔均）"
        fe, te, de = triple_series_for_shorts(codes)
        color = colors[palette_i % len(colors)]
        palette_i += 1
        lines_out.append(
            {
                "kind": "sector_avg",
                "id": sid,
                "label": label,
                "foreign_bn": fe,
                "trust_bn": te,
                "dealer_bn": de,
                "line": {"color": color, "width": 2},
            }
        )

    for c in stock_codes or []:
        c = str(c).strip()
        if c not in code_map:
            continue
        fe, te, de = triple_series_for_shorts([c])
        name = code_map[c].split(maxsplit=1)[1] if " " in code_map[c] else c
        color = colors[palette_i % len(colors)]
        palette_i += 1
        lines_out.append(
            {
                "kind": "stock",
                "code": c,
                "label": f"{c} {name}",
                "foreign_bn": fe,
                "trust_bn": te,
                "dealer_bn": de,
                "line": {"color": color, "width": 1.8, "dash": "dot"},
            }
        )

    return {
        "status": "ok",
        "dates": date_strs,
        "lines": lines_out,
        "unit": "億元",
        "note": note,
    }


def get_market_institutional_flow(
    price_df: pd.DataFrame,
    chip_df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> dict:
    """
    三大法人每日買賣超金額（億元）：以當日收盤價×買賣超(張)×1000 估算後，於全市場加總。
    若有 Variable_setting/股票市場別.csv，另回傳上市(TSE)／上櫃(OTC)分拆。
    """
    need_chip = [
        "證券代碼",
        "年月日",
        "外資買賣超(張)",
        "投信買賣超(張)",
        "自營買賣超(張)",
    ]
    need_price = ["證券代碼", "date", "收盤價(元)"]
    if chip_df is None or chip_df.empty:
        return {
            "status": "no_data",
            "message": "無籌碼資料",
            "split_available": False,
            "markets": {},
        }
    if price_df is None or price_df.empty:
        return {
            "status": "no_data",
            "message": "無股價資料",
            "split_available": False,
            "markets": {},
        }
    if not all(c in chip_df.columns for c in need_chip):
        return {
            "status": "no_data",
            "message": "籌碼資料缺少法人買賣超欄位",
            "split_available": False,
            "markets": {},
        }
    if not all(c in price_df.columns for c in need_price):
        return {
            "status": "no_data",
            "message": "股價資料缺少收盤價",
            "split_available": False,
            "markets": {},
        }

    p = price_df[["date", "證券代碼", "收盤價(元)"]].copy()
    p["short"] = p["證券代碼"].astype(str).str.strip().str.split().str[0]
    p = p.loc[p["short"].str.match(r"^\d{4}$", na=False)]

    c = chip_df[
        ["年月日", "證券代碼", "外資買賣超(張)", "投信買賣超(張)", "自營買賣超(張)"]
    ].copy()
    c["date"] = pd.to_datetime(c["年月日"], format="%Y%m%d", errors="coerce")
    c["short"] = c["證券代碼"].astype(str).str.strip().str.split().str[0]
    c = c.loc[c["short"].str.match(r"^\d{4}$", na=False)]

    if start_date:
        t0 = pd.to_datetime(start_date)
        p = p[p["date"] >= t0]
        c = c[c["date"] >= t0]
    if end_date:
        t1 = pd.to_datetime(end_date)
        p = p[p["date"] <= t1]
        c = c[c["date"] <= t1]

    merged = pd.merge(c, p, on=["date", "short"], how="inner")
    if merged.empty:
        return {
            "status": "no_data",
            "message": "區間內無可對齊之股價與籌碼列",
            "split_available": False,
            "markets": {},
        }

    px = pd.to_numeric(merged["收盤價(元)"], errors="coerce")
    ff = pd.to_numeric(merged["外資買賣超(張)"], errors="coerce")
    tf = pd.to_numeric(merged["投信買賣超(張)"], errors="coerce")
    df = pd.to_numeric(merged["自營買賣超(張)"], errors="coerce")
    merged = merged.assign(
        foreign_e=ff.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
        trust_e=tf.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
        dealer_e=df.fillna(0) * 1000.0 * px.fillna(0) / 1e8,
    )

    mm = _load_stock_market_map()
    split_available = bool(mm)
    markets: dict = {"all": _pack_institutional_market_slice(merged)}
    if split_available:
        merged = merged.assign(mkt=merged["short"].map(mm))
        markets["tse"] = _pack_institutional_market_slice(
            merged.loc[merged["mkt"] == "TSE"],
        )
        markets["otc"] = _pack_institutional_market_slice(
            merged.loc[merged["mkt"] == "OTC"],
        )

    return {
        "status": "ok",
        "unit": "億元",
        "note": "金額為當日收盤價×買賣超張數×1000 之估算值",
        "split_available": split_available,
        "markets": markets,
    }


def _metric_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def get_sector_valuation_monthly(
    price_df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    sector_series: list,
    stock_codes: list,
) -> dict:
    """
    依與報酬折線相同之勾選，回傳**月頻**簡單平均：各股取該月最後交易日之本益比-TSE、股價淨值比-TSE（由同日列讀取），
    再對類股內有效值平均（本益比／淨值比僅納入 >0）。附 PE／PB 估值帶（第一條有足夠資料之序列之 10/30/50/70/90 分位）
    與摘要表（最近月、月增、年增）。回傳之 `series` 僅含 `pe`／`pb`，不含收盤價序列。
    """
    required = ["date", "證券代碼", "本益比-TSE", "股價淨值比-TSE"]
    if price_df is None or price_df.empty:
        return {
            "status": "no_data",
            "message": "無股價資料",
            "months": [],
            "series": [],
            "pe_bands": None,
            "pb_bands": None,
            "pe_summary": [],
            "pb_summary": [],
        }
    if not all(c in price_df.columns for c in required):
        return {
            "status": "no_data",
            "message": "股價資料缺少本益比-TSE 或 股價淨值比-TSE",
            "months": [],
            "series": [],
            "pe_bands": None,
            "pb_bands": None,
            "pe_summary": [],
            "pb_summary": [],
        }

    code_map: dict[str, str] = {}
    for full in price_df["證券代碼"].unique():
        sc = str(full).strip().split()[0]
        if len(sc) == 4 and sc.isdigit():
            code_map[sc] = str(full).strip()

    pf = price_df.copy()
    if start_date:
        pf = pf[pf["date"] >= pd.to_datetime(start_date)]
    if end_date:
        pf = pf[pf["date"] <= pd.to_datetime(end_date)]

    want_full: set[str] = set()
    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        for c in block.get("codes") or []:
            c = str(c).strip()
            if c in code_map:
                want_full.add(code_map[c])
    for c in stock_codes or []:
        c = str(c).strip()
        if c in code_map:
            want_full.add(code_map[c])
    if not want_full:
        return {
            "status": "ok",
            "months": [],
            "series": [],
            "pe_bands": None,
            "pb_bands": None,
            "pe_summary": [],
            "pb_summary": [],
        }

    sub = pf[pf["證券代碼"].isin(want_full)][required].copy()
    sub["short"] = sub["證券代碼"].astype(str).str.strip().str.split().str[0]
    sub["ym"] = sub["date"].dt.to_period("M")

    all_months = sorted(sub["ym"].dropna().unique())
    month_keys: list[pd.Timestamp] = []
    for ym in all_months:
        chunk = sub.loc[sub["ym"] == ym, "date"]
        if chunk.empty:
            continue
        month_keys.append(pd.Timestamp(chunk.max()))
    month_strs = [d.strftime("%Y-%m-%d") for d in month_keys]

    def monthly_avg_for_shorts(shorts: list[str], ym) -> dict:
        pes: list[float] = []
        pbs: list[float] = []
        for sc in shorts:
            if sc not in code_map:
                continue
            sm = sub[(sub["short"] == sc) & (sub["ym"] == ym)]
            if sm.empty:
                continue
            row = sm.sort_values("date").iloc[-1]
            pe = _metric_float(row["本益比-TSE"])
            pb = _metric_float(row["股價淨值比-TSE"])
            if pe is not None and pe > 0:
                pes.append(pe)
            if pb is not None and pb > 0:
                pbs.append(pb)
        return {
            "pe": sum(pes) / len(pes) if pes else None,
            "pb": sum(pbs) / len(pbs) if pbs else None,
        }

    series_out: list[dict] = []
    palette_i = 0
    colors = ["#58a6ff", "#d29922", "#f85149", "#3fb950", "#bc8cff", "#39d0d8", "#e3b341", "#8b949e"]

    for block in sector_series or []:
        if not isinstance(block, dict):
            continue
        codes = [str(c).strip() for c in (block.get("codes") or []) if str(c).strip() in code_map]
        if not codes:
            continue
        sid = str(block.get("id", ""))
        sname = str(block.get("name") or sid)
        label = f"{sname}（{len(codes)}檔均）"
        pes, pbs = [], []
        for ym in all_months:
            r = monthly_avg_for_shorts(codes, ym)
            pes.append(_clean(round(r["pe"], 4)) if r["pe"] is not None else None)
            pbs.append(_clean(round(r["pb"], 4)) if r["pb"] is not None else None)
        col = colors[palette_i % len(colors)]
        palette_i += 1
        series_out.append(
            {
                "kind": "sector_avg",
                "id": sid,
                "label": label,
                "pe": pes,
                "pb": pbs,
                "line": {"color": col, "width": 2},
            }
        )

    for c in stock_codes or []:
        c = str(c).strip()
        if c not in code_map:
            continue
        pes, pbs = [], []
        for ym in all_months:
            r = monthly_avg_for_shorts([c], ym)
            pes.append(_clean(round(r["pe"], 4)) if r["pe"] is not None else None)
            pbs.append(_clean(round(r["pb"], 4)) if r["pb"] is not None else None)
        name = code_map[c].split(maxsplit=1)[1] if " " in code_map[c] else c
        col = colors[palette_i % len(colors)]
        palette_i += 1
        series_out.append(
            {
                "kind": "stock",
                "code": c,
                "label": f"{c} {name}",
                "pe": pes,
                "pb": pbs,
                "line": {"color": col, "width": 1.8, "dash": "dot"},
            }
        )

    pe_bands = None
    pb_bands = None
    for s in series_out:
        raw = [x for x in s["pe"] if x is not None and isinstance(x, (int, float)) and x > 0]
        if pe_bands is None and len(raw) >= 8:
            ser = pd.Series(raw, dtype="float64")
            edges = ser.quantile([0.1, 0.3, 0.5, 0.7, 0.9]).tolist()
            pe_bands = {"edges": [_clean(round(float(e), 4)) for e in edges]}
        rawb = [x for x in s["pb"] if x is not None and isinstance(x, (int, float)) and x > 0]
        if pb_bands is None and len(rawb) >= 8:
            serb = pd.Series(rawb, dtype="float64")
            edgesb = serb.quantile([0.1, 0.3, 0.5, 0.7, 0.9]).tolist()
            pb_bands = {"edges": [_clean(round(float(e), 4)) for e in edgesb]}
        if pe_bands is not None and pb_bands is not None:
            break

    def build_summary(metric: str) -> list:
        out: list[dict] = []
        for s in series_out:
            vals = s[metric]
            idx = None
            for i in range(len(vals) - 1, -1, -1):
                if vals[i] is not None:
                    idx = i
                    break
            if idx is None:
                continue
            cur = float(vals[idx])
            prev_v = float(vals[idx - 1]) if idx > 0 and vals[idx - 1] is not None else None
            d0 = month_keys[idx]
            yoy_idx = None
            for j, d in enumerate(month_keys):
                if d.year == d0.year - 1 and d.month == d0.month:
                    yoy_idx = j
            yoy_v = float(vals[yoy_idx]) if yoy_idx is not None and vals[yoy_idx] is not None else None
            mom = (cur - prev_v) if prev_v is not None else None
            yoy_d = (cur - yoy_v) if yoy_v is not None else None
            out.append(
                {
                    "label": s["label"],
                    "month": month_strs[idx],
                    "value": _clean(round(cur, 4)),
                    "mom": _clean(round(mom, 4)) if mom is not None else None,
                    "yoy": _clean(round(yoy_d, 4)) if yoy_d is not None else None,
                }
            )
        return out

    return {
        "status": "ok",
        "months": month_strs,
        "series": series_out,
        "pe_bands": pe_bands,
        "pb_bands": pb_bands,
        "pe_summary": build_summary("pe"),
        "pb_summary": build_summary("pb"),
    }


def load_chip_data() -> pd.DataFrame:
    """讀取 TEJ 籌碼資料庫。"""
    df = _load_csv_dir(CHIP_DIR, CHIP_NUMERIC, ["證券代碼", "年月日"])
    df["date"] = pd.to_datetime(df["年月日"], format="%Y%m%d", errors="coerce")
    df.sort_values(["date", "證券代碼"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def load_monthly_director_data() -> pd.DataFrame:
    """讀取董監全體持股狀況（月資料）。"""
    df = _load_csv_dir(MONTHLY_DIR, MONTHLY_NUMERIC, ["證券代碼", "年月"])
    df["年月"] = df["年月"].astype(str).str.strip()
    df.sort_values(["年月", "證券代碼"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def load_quarterly_data() -> pd.DataFrame:
    """讀取以合併為主簡表（季資料），保留所有財務欄位。"""
    csv_files = sorted(QUARTERLY_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"找不到季資料 CSV：{QUARTERLY_DIR}")

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-16", sep="\t", dtype=str)
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"[警告] 讀取季資料 {f.name} 失敗：{e}")

    combined = pd.concat(dfs, ignore_index=True)
    combined["證券代碼"] = combined["證券代碼"].astype(str).str.strip()
    combined["年月"]     = combined["年月"].astype(str).str.strip()
    combined.sort_values("_src", inplace=True)
    combined.drop_duplicates(subset=["證券代碼", "年月"], keep="last", inplace=True)
    combined.drop(columns=["_src"], inplace=True)
    combined.sort_values(["年月", "證券代碼"], inplace=True)
    combined.reset_index(drop=True, inplace=True)
    return combined


# ── 個股監控查詢函式 ─────────────────────────────────────────────────────────

def get_stock_list(price_df: pd.DataFrame) -> list:
    """
    回傳所有可用個股清單（排除純指數標的）。
    格式：[{"code": "2330", "name": "台積電", "full": "2330 台積電"}, ...]
    """
    result = []
    seen = set()
    for full in sorted(price_df["證券代碼"].unique()):
        parts = str(full).strip().split(maxsplit=1)
        code = parts[0]
        name = parts[1] if len(parts) > 1 else code
        if len(code) >= 4 and code[:4].isdigit() and code not in seen:
            seen.add(code)
            result.append({"code": code, "name": name, "full": full})
    return result


def get_quarterly_columns(quarterly_df: pd.DataFrame) -> list:
    """回傳季資料可用財務指標欄位清單（排除代碼/日期欄）。"""
    exclude = {"證券代碼", "年月"}
    return [c for c in quarterly_df.columns if c not in exclude]


def _build_code_map(price_df: pd.DataFrame, codes: list) -> dict:
    """將輸入的短代碼（如 '2330'）對應到 DataFrame 的完整欄值（'2330 台積電'）。"""
    mapping = {}
    for full in price_df["證券代碼"].unique():
        code = str(full).strip().split()[0]
        if code not in mapping:
            mapping[code] = str(full).strip()
    return {c: mapping[c] for c in codes if c in mapping}


def _col(df: pd.DataFrame, col: str, default=None):
    """安全取欄位，欄位不存在時回傳 default 序列。"""
    if col in df.columns:
        return df[col]
    n = len(df)
    return pd.Series([default] * n, index=df.index)


def get_stock_series(
    price_df: pd.DataFrame,
    chip_df: pd.DataFrame,
    codes: list,
    start_date: str = None,
    end_date: str = None,
) -> dict:
    """
    回傳各股票的日頻時序資料（股價 + 籌碼），供個股監控圖表使用。

    結構：
    {
      "2330": {
        "code": "2330", "name": "台積電",
        "dates": [...], "close": [...], ...
        "chip": { "dates": [...], "foreign_net": [...], ... }
      }
    }
    """
    code_map = _build_code_map(price_df, codes)
    if not code_map:
        return {}

    # 股票持續性機率 P(高持續性|振幅大事件)，由報告 a 產生時寫出
    persist_prob_map = {}
    persist_hi_n_map = {}
    persist_amp_n_map = {}
    if STOCK_PERSIST_PROB_CSV.exists():
        try:
            prob_df = pd.read_csv(STOCK_PERSIST_PROB_CSV, encoding="utf-8-sig")
            if "stock_code" in prob_df.columns and "stock_persist_prob" in prob_df.columns:
                prob_df = prob_df.copy()
                prob_df["stock_code"] = prob_df["stock_code"].astype(str).str.strip()
                ix = prob_df.set_index("stock_code")
                persist_prob_map = ix["stock_persist_prob"].to_dict()
                if "stock_persist_hi_n" in ix.columns:
                    persist_hi_n_map = ix["stock_persist_hi_n"].to_dict()
                if "stock_persist_amp_n" in ix.columns:
                    persist_amp_n_map = ix["stock_persist_amp_n"].to_dict()
        except Exception:
            pass

    # 日期過濾
    p = price_df
    c = chip_df
    if start_date:
        sd = pd.to_datetime(start_date)
        p = p[p["date"] >= sd]
        c = c[c["date"] >= sd]
    if end_date:
        ed = pd.to_datetime(end_date)
        p = p[p["date"] <= ed]
        c = c[c["date"] <= ed]

    result = {}
    for code, full_code in code_map.items():
        # 股價資料
        ps = p[p["證券代碼"] == full_code].sort_values("date").reset_index(drop=True)
        if ps.empty:
            continue

        # 籌碼資料（以代碼前綴匹配）
        cs = c[c["證券代碼"].astype(str).str.startswith(code + " ")].sort_values("date").reset_index(drop=True)
        if cs.empty:
            cs = c[c["證券代碼"].astype(str).str.startswith(code)].sort_values("date").reset_index(drop=True)

        # 指數化報酬（基準 = 100）
        ret = _col(ps, "報酬率％").fillna(0) / 100
        indexed = (1 + ret).cumprod() * 100

        name = full_code.split(maxsplit=1)[1] if " " in full_code else code
        dates_str = ps["date"].dt.strftime("%Y-%m-%d").tolist()

        entry = {
            "code": code,
            "name": name,
            "dates": dates_str,
            "close":        _clean_list(_col(ps, "收盤價(元)").tolist()),
            "open":         _clean_list(_col(ps, "開盤價(元)").tolist()),
            "high":         _clean_list(_col(ps, "最高價(元)").tolist()),
            "low":          _clean_list(_col(ps, "最低價(元)").tolist()),
            "volume":       _clean_list(_col(ps, "成交量(千股)").tolist()),
            "return_pct":   _clean_list(_col(ps, "報酬率％").tolist()),
            "indexed_return": _clean_list(indexed.tolist()),
            "turnover":     _clean_list(_col(ps, "週轉率％").tolist()),
            "market_cap":   _clean_list(_col(ps, "市值(百萬元)").tolist()),
            "pe":           _clean_list(_col(ps, "本益比-TSE").tolist()),
            "pb":           _clean_list(_col(ps, "股價淨值比-TSE").tolist()),
            "ps":           _clean_list(_col(ps, "股價營收比-TEJ").tolist()),
            "dividend_yield": _clean_list(_col(ps, "現金股利率").tolist()),
            "amplitude":    _clean_list(_col(ps, "高低價差%").tolist()),
            "excess_return": _clean_list(_col(ps, "超額報酬(日)-大盤").tolist()),
            "capm_beta":    _clean_list(_col(ps, "CAPM_Beta 一年").tolist()),
            "attention":    (_col(ps, "注意股票(A)").astype(str).str.strip() == "A").astype(int).tolist(),
            "disposal":     (_col(ps, "處置股票(D)").astype(str).str.strip() == "D").astype(int).tolist(),
            "full_delivery": (_col(ps, "全額交割(Y)").astype(str).str.strip() == "Y").astype(int).tolist(),
            "limit_up":     (_col(ps, "漲跌停").astype(str).str.strip() == "+").astype(int).tolist(),
            "limit_down":   (_col(ps, "漲跌停").astype(str).str.strip() == "-").astype(int).tolist(),
            "stock_persist_prob": _clean(persist_prob_map.get(code)),
            "stock_persist_hi_n": _to_int(persist_hi_n_map.get(code)),
            "stock_persist_amp_n": _to_int(persist_amp_n_map.get(code)),
        }

        # 籌碼資料
        if not cs.empty:
            entry["chip"] = {
                "dates":             cs["date"].dt.strftime("%Y-%m-%d").tolist(),
                "foreign_net":       _clean_list(_col(cs, "外資買賣超(張)").tolist()),
                "trust_net":         _clean_list(_col(cs, "投信買賣超(張)").tolist()),
                "dealer_net":        _clean_list(_col(cs, "自營買賣超(張)").tolist()),
                "total_net":         _clean_list(_col(cs, "合計買賣超(張)").tolist()),
                "margin_balance":    _clean_list(_col(cs, "融資餘額(張)").tolist()),
                "short_balance":     _clean_list(_col(cs, "融券餘額(張)").tolist()),
                "margin_maintenance": _clean_list(_col(cs, "融資維持率").tolist()),
                "foreign_pct":       _clean_list(_col(cs, "外資總投資股率%").tolist()),
                "trust_pct":         _clean_list(_col(cs, "投信持股率%").tolist()),
                "total_pct":         _clean_list(_col(cs, "合計持股率%").tolist()),
                "short_sell_balance": _clean_list(_col(cs, "借券賣出餘額(張)").tolist()),
            }

        result[code] = entry

    return result


def get_monthly_director(monthly_df: pd.DataFrame, codes: list) -> dict:
    """回傳董監持股月資料（月底頻率）。"""
    result = {}
    for code in codes:
        mask = monthly_df["證券代碼"].astype(str).str.startswith(code)
        m = monthly_df[mask].sort_values("年月").reset_index(drop=True)
        if m.empty:
            continue
        result[code] = {
            "periods":             m["年月"].tolist(),
            "director_pct":        _clean_list(_col(m, "董監持股%").tolist()),
            "major_holding_pct":   _clean_list(_col(m, "大股東持股(TSE)%").tolist()),
        }
    return result


def get_quarterly_series(quarterly_df: pd.DataFrame, codes: list, cols: list) -> dict:
    """回傳指定季財務指標的時序（使用者選定的欄位）。"""
    valid_cols = [c for c in cols if c in quarterly_df.columns]
    result = {}
    for code in codes:
        mask = quarterly_df["證券代碼"].astype(str).str.startswith(code)
        q = quarterly_df[mask].sort_values("年月").reset_index(drop=True)
        if q.empty:
            continue

        series = {}
        for col in valid_cols:
            vals = pd.to_numeric(
                q[col].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )
            series[col] = _clean_list(vals.tolist())

        result[code] = {
            "periods": q["年月"].tolist(),
            "series":  series,
        }
    return result


def get_stock_date_range(price_df: pd.DataFrame) -> dict:
    """回傳股價資料庫的日期範圍。"""
    return {
        "min": price_df["date"].min().strftime("%Y-%m-%d"),
        "max": price_df["date"].max().strftime("%Y-%m-%d"),
    }


def get_heatmap_data(df: pd.DataFrame) -> dict:
    """
    市場廣度熱力圖：各標的每日上漲家數比例。
    """
    securities = sorted(df["證券代碼"].unique().tolist())
    dates = sorted(df["date"].dropna().unique())
    date_strs = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]

    values = {}
    for code in securities:
        sec = df[df["證券代碼"] == code].set_index("date")
        row_vals = []
        for d in dates:
            ts = pd.Timestamp(d)
            if ts in sec.index:
                r = sec.loc[ts]
                total = r["上漲家數"] + r["持平家數"] + r["下跌家數"]
                row_vals.append(round(float(r["上漲家數"] / total * 100), 1) if total > 0 else None)
            else:
                row_vals.append(None)
        values[code] = row_vals

    return {
        "securities": securities,
        "labels": [SECURITY_LABELS.get(c, c) for c in securities],
        "dates": date_strs,
        "values": values,
    }

