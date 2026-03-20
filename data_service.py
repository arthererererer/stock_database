"""
data_service.py
資料存取層 — 目前讀取 CSV，未來可替換為 API 串接，只需修改此檔。
"""

import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

# ── 資料來源路徑（切換 API 時改這裡）──────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "All_Data" / "日資料" / "大盤統計" / "大盤統計資訊"
MARKET_AMP_JSON = BASE_DIR / "All_Data" / "事件資料" / "市場振幅比例.json"
STOCK_PERSIST_PROB_CSV = BASE_DIR / "All_Data" / "事件資料" / "股票持續性機率.csv"
BANK_RATE_DIR = BASE_DIR / "All_Data" / "日資料" / "國內銀行利率(日)_國內銀行匯率"
FACTOR_CHARS_CSV = BASE_DIR / "All_Data" / "事件資料" / "因子特徵與載荷.csv"

# 特徵溢酬監控（雙重排序 tercile LS）— 與 README / PLATFORM_SPEC 1.1 一致
FEATURE_SORT_COLS = ["規模", "淨值市價比", "益本比", "股利殖利率", "動能", "短期反轉"]
FEATURE_MIN_TERCILE = 10
FEATURE_MIN_MV = 100.0

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


# ── 工具函數 ────────────────────────────────────────────────────────────

def _clean(v):
    """將 NaN / Inf 轉為 None，供 JSON 序列化。"""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _clean_list(lst: list) -> list:
    return [_clean(x) for x in lst]


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


def get_timeseries_data(df: pd.DataFrame, start_date: str = None, end_date: str = None) -> dict:
    """
    各標的的時序資料，供折線圖、柱狀圖、成交金額趨勢使用。
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


# ════════════════════════════════════════════════════════════════════════
# 國際股市模組
# ════════════════════════════════════════════════════════════════════════

INTL_INDEX_DIR = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\日資料\國際股價指數")
FX_DIR         = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\日資料\國內銀行利率(日)_國內銀行匯率")

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
        group = _intl_group(code)

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
            "group":         _intl_group(code),
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

STOCK_PRICE_DIR = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\日資料\TEJ 股價資料庫")
CHIP_DIR        = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\日資料\TEJ 籌碼資料庫")
MONTHLY_DIR     = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\月資料\董監全體持股狀況")
QUARTERLY_DIR   = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\季資料\以合併為主簡表(單季)-全產業")

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
    if STOCK_PERSIST_PROB_CSV.exists():
        try:
            prob_df = pd.read_csv(STOCK_PERSIST_PROB_CSV, encoding="utf-8-sig")
            if "stock_code" in prob_df.columns and "stock_persist_prob" in prob_df.columns:
                persist_prob_map = prob_df.set_index("stock_code")["stock_persist_prob"].to_dict()
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


# ════════════════════════════════════════════════════════════════════════
# 特徵溢酬監控（月再平衡、雙重排序 tercile long–short）
# ════════════════════════════════════════════════════════════════════════


def load_risk_free_series() -> pd.Series | None:
    """
    與 generate_factor_returns_csv.load_risk_free 相同定義：
    各家銀行「一年定存」之日平均（％），索引為 date。
    """
    csv_files = sorted(BANK_RATE_DIR.glob("*.csv"))
    if not csv_files:
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
        except Exception:
            continue
    if not dfs:
        return None
    all_df = pd.concat(dfs, ignore_index=True)
    all_df["年月日"] = all_df["年月日"].astype(str).str.strip()
    rf = all_df.groupby("年月日")["一年定存"].mean()
    rf.index = pd.to_datetime(rf.index, format="%Y%m%d", errors="coerce")
    rf = rf[rf.index.notna()]
    return rf.sort_index()


def _rf_for_date(rf_series: pd.Series | None, di: pd.Timestamp) -> float:
    """無風險利率轉成與因子腳本相同之日用小數（一年定存％ ÷ 100）。"""
    if rf_series is None or len(rf_series) == 0:
        return 0.0
    try:
        if di in rf_series.index:
            v = float(rf_series.loc[di])
        else:
            v = float(rf_series.asof(di))
    except (KeyError, TypeError, ValueError):
        return 0.0
    if math.isnan(v):
        return 0.0
    return v / 100.0


_factor_chars_memo: pd.DataFrame | None = None


def invalidate_factor_chars_cache() -> None:
    global _factor_chars_memo
    _factor_chars_memo = None


def load_factor_chars_table() -> pd.DataFrame:
    """讀取因子特徵與載荷 CSV（僅保留排序用特徵欄）。啟動後快取於記憶體，更新檔案後請呼叫重新載入。"""
    global _factor_chars_memo
    if _factor_chars_memo is not None:
        return _factor_chars_memo.copy(deep=False)
    if not FACTOR_CHARS_CSV.exists():
        raise FileNotFoundError(f"找不到：{FACTOR_CHARS_CSV}（請先產生因子特徵 CSV）")
    df = pd.read_csv(FACTOR_CHARS_CSV, encoding="utf-8-sig", low_memory=False)
    df["證券代碼"] = df["證券代碼"].astype(str).str.strip()
    df["年月日"] = df["年月日"].astype(str).str.strip()
    df["date"] = pd.to_datetime(df["年月日"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    keep = ["證券代碼", "年月日", "date"] + [c for c in FEATURE_SORT_COLS if c in df.columns]
    for c in FEATURE_SORT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    out = df[keep].drop_duplicates(subset=["證券代碼", "date"], keep="last")
    _factor_chars_memo = out
    return out.copy(deep=False)


def _last_trading_day_per_month(trading_days: list) -> list:
    by_ym = {}
    for d in trading_days:
        if pd.isna(d):
            continue
        ts = pd.Timestamp(d)
        by_ym[(ts.year, ts.month)] = ts
    return sorted(by_ym.values())


def _tercile_long_short_codes(sub: pd.DataFrame, dim2: str) -> tuple[frozenset, frozenset] | None:
    """
    sub：同一第一維子樣本，需含 code, dim2。
    回傳 (高組代碼, 低組代碼)，失敗則 None。
    """
    s = sub[[dim2, "code"]].dropna(subset=[dim2])
    if len(s) < FEATURE_MIN_TERCILE * 3:
        return None
    try:
        ranks = s[dim2].rank(method="first")
        labels = pd.qcut(ranks, q=3, labels=[0, 1, 2], duplicates="drop")
    except (ValueError, TypeError):
        return None
    s = s.copy()
    s["_g"] = labels
    if s["_g"].nunique() < 3:
        return None
    vc = s.groupby("_g", observed=False).size()
    if len(vc) < 3 or vc.min() < FEATURE_MIN_TERCILE:
        return None
    hi = frozenset(s.loc[s["_g"] == 2, "code"].astype(str))
    lo = frozenset(s.loc[s["_g"] == 0, "code"].astype(str))
    if len(hi) < FEATURE_MIN_TERCILE or len(lo) < FEATURE_MIN_TERCILE:
        return None
    return hi, lo


def _formation_portfolios(
    day_panel: pd.DataFrame, dim1: str, dim2: str
) -> tuple[frozenset, frozenset, frozenset, frozenset] | None:
    """
    於 formation 日之截面，回傳 (long_A, short_A, long_B, short_B)。
    A = 第一維高組（>= 中位數），B = 低組。
    """
    need = {"code", dim1, dim2, "市值(百萬元)"}
    if not need.issubset(day_panel.columns):
        return None
    w = day_panel.dropna(subset=[dim1, dim2]).copy()
    w = w[w["市值(百萬元)"].fillna(0) >= FEATURE_MIN_MV]
    if len(w) < FEATURE_MIN_TERCILE * 6:
        return None
    med = w[dim1].median()
    if pd.isna(med):
        return None
    high = w[w[dim1] >= med]
    low = w[w[dim1] < med]
    ls_h = _tercile_long_short_codes(high, dim2)
    ls_l = _tercile_long_short_codes(low, dim2)
    if ls_h is None or ls_l is None:
        return None
    long_a, short_a = ls_h
    long_b, short_b = ls_l
    return long_a, short_a, long_b, short_b


def get_feature_premium_meta(chars_df: pd.DataFrame | None = None) -> dict:
    """特徵溢酬 API：可選維度與資料日期範圍。"""
    if chars_df is None:
        try:
            chars_df = load_factor_chars_table()
        except FileNotFoundError:
            return {
                "ok": False,
                "message": "找不到因子特徵與載荷 CSV，請先執行 generate_factor_chars_loadings_csv.py",
                "features": FEATURE_SORT_COLS,
                "date_range": None,
            }
    dr = chars_df["date"].dropna()
    if dr.empty:
        return {"ok": False, "message": "因子特徵表無有效日期", "features": FEATURE_SORT_COLS, "date_range": None}
    return {
        "ok": True,
        "features": list(FEATURE_SORT_COLS),
        "date_range": {
            "min": dr.min().strftime("%Y-%m-%d"),
            "max": dr.max().strftime("%Y-%m-%d"),
        },
    }


def get_feature_premium_series(
    price_df: pd.DataFrame,
    dim1: str,
    dim2: str,
    start: str | None = None,
    end: str | None = None,
    include_mkt: bool = True,
) -> dict:
    """
    月再平衡（月末最後交易日 formation，次一交易日起生效）、雙重排序 tercile LS（等權、個股超額％與因子腳本一致）。
    """
    dim1 = (dim1 or "").strip()
    dim2 = (dim2 or "").strip()
    if dim1 == dim2:
        return {"ok": False, "message": "第一維與第二維不可相同", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}
    if dim1 not in FEATURE_SORT_COLS or dim2 not in FEATURE_SORT_COLS:
        return {"ok": False, "message": f"無效維度，僅支援：{FEATURE_SORT_COLS}", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    try:
        chars_df = load_factor_chars_table()
    except FileNotFoundError as e:
        return {"ok": False, "message": str(e), "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    need_price = ["證券代碼", "年月日", "date", "報酬率％", "市值(百萬元)"]
    for c in need_price:
        if c not in price_df.columns:
            return {"ok": False, "message": f"股價資料缺少欄位：{c}", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    px = price_df[need_price].copy()
    px["code"] = px["證券代碼"].astype(str).str.split().str[0]
    px = px[px["code"].str.match(r"^\d{4}$", na=False)]

    chars_df = chars_df.copy()
    chars_df["code"] = chars_df["證券代碼"].astype(str).str.strip()
    ccols = ["code", "date"] + [c for c in FEATURE_SORT_COLS if c in chars_df.columns]
    merged = chars_df[ccols].merge(
        px.drop(columns=["證券代碼"], errors="ignore"),
        on=["code", "date"],
        how="inner",
    )
    if merged.empty:
        return {"ok": False, "message": "特徵與股價無法對齊（日期／代碼交集為空）", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    dr_min, dr_max = merged["date"].min(), merged["date"].max()
    if start:
        t0 = pd.to_datetime(start, errors="coerce")
        if pd.notna(t0):
            dr_min = max(dr_min, t0)
    if end:
        t1 = pd.to_datetime(end, errors="coerce")
        if pd.notna(t1):
            dr_max = min(dr_max, t1)
    merged = merged[(merged["date"] >= dr_min) & (merged["date"] <= dr_max)]
    if merged.empty:
        return {"ok": False, "message": "指定區間無資料", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    rf_series = load_risk_free_series()

    merged["date"] = pd.to_datetime(merged["date"])
    udates = merged["date"].dropna().unique()
    rf_map = {pd.Timestamp(d): _rf_for_date(rf_series, pd.Timestamp(d)) for d in udates}
    r_pct = pd.to_numeric(merged["報酬率％"], errors="coerce")
    merged["excess"] = (r_pct / 100.0 - merged["date"].map(lambda d: rf_map.get(pd.Timestamp(d), 0.0))) * 100.0

    trading_days = sorted({pd.Timestamp(d) for d in merged["date"].dropna().unique()})
    if len(trading_days) < 5:
        return {"ok": False, "message": "交易日數過少", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    next_td = {trading_days[i]: trading_days[i + 1] for i in range(len(trading_days) - 1)}
    month_ends = _last_trading_day_per_month(trading_days)
    month_ends = [pd.Timestamp(d) for d in month_ends]
    # 僅保留可作 formation 且有「次日」之月末
    reb_points = [d for d in month_ends if d in next_td]

    merged["ts"] = merged["date"].map(pd.Timestamp)

    # 每日 panel：code -> excess
    by_date = {pd.Timestamp(d): g[["code", "excess"]].copy() for d, g in merged.groupby("ts")}

    # 大盤 Y9999 超額
    mkt_daily = {}
    if include_mkt:
        mpx = price_df[price_df["證券代碼"].astype(str).str.contains("Y9999", na=False)]
        if not mpx.empty:
            mpx = mpx[["date", "報酬率％"]].drop_duplicates(subset=["date"])
            for _, rr in mpx.iterrows():
                di = rr["date"]
                if pd.isna(di) or di < dr_min or di > dr_max:
                    continue
                rff = _rf_for_date(rf_series, pd.Timestamp(di))
                rp = rr["報酬率％"]
                if pd.isna(rp):
                    mkt_daily[pd.Timestamp(di)] = math.nan
                else:
                    mkt_daily[pd.Timestamp(di)] = (float(rp) / 100.0 - rff) * 100.0

    # formation -> portfolios
    port_by_reb = {}
    for rday in reb_points:
        rts = pd.Timestamp(rday)
        if rts not in by_date:
            continue
        panel_r = merged[merged["ts"] == rts]
        ports = _formation_portfolios(panel_r, dim1, dim2)
        if ports is not None:
            port_by_reb[rts] = ports

    if not port_by_reb:
        return {"ok": False, "message": "無法於任何月末形成有效投組（樣本或分組不足）", "dates": [], "ls_daily": [], "ls_cum": [], "mkt_excess_daily": [], "mkt_excess_cum": []}

    sorted_rebs = sorted(port_by_reb.keys())

    def active_reb_for(t: pd.Timestamp):
        """最大 r 使得 next_td[r] <= t。"""
        best = None
        for r in sorted_rebs:
            nx = next_td.get(r)
            if nx is None:
                continue
            if nx <= t:
                best = r
        return best

    def ew_spread(rows: pd.DataFrame, long_c: frozenset, short_c: frozenset) -> float:
        L = rows[rows["code"].isin(long_c)]["excess"].dropna()
        S = rows[rows["code"].isin(short_c)]["excess"].dropna()
        if len(L) == 0 or len(S) == 0:
            return math.nan
        return float(L.mean() - S.mean())

    dates_out = []
    ls_daily = []
    mkt_exc = []

    cum = 1.0
    cum_m = 1.0
    ls_cum = []
    mkt_cum = []

    for t in trading_days:
        ts = pd.Timestamp(t)
        if ts < dr_min or ts > dr_max:
            continue
        rform = active_reb_for(ts)
        if rform is None or rform not in port_by_reb:
            continue
        long_a, short_a, long_b, short_b = port_by_reb[rform]
        g = by_date.get(ts)
        if g is None or g.empty:
            continue
        sp_a = ew_spread(g, long_a, short_a)
        sp_b = ew_spread(g, long_b, short_b)
        parts = [x for x in (sp_a, sp_b) if x == x]  # not nan
        if not parts:
            val = math.nan
        elif len(parts) == 1:
            val = parts[0]
        else:
            val = (parts[0] + parts[1]) / 2.0

        dates_out.append(ts.strftime("%Y-%m-%d"))
        ls_daily.append(round(val, 6) if val == val else None)

        mtv = mkt_daily.get(ts)
        if include_mkt:
            mkt_exc.append(round(mtv, 6) if mtv is not None and mtv == mtv else None)
        else:
            mkt_exc.append(None)

        if val == val:
            cum *= 1.0 + val / 100.0
        ls_cum.append(round((cum - 1.0) * 100.0, 6))
        if include_mkt and mtv is not None and mtv == mtv:
            cum_m *= 1.0 + mtv / 100.0
            mkt_cum.append(round((cum_m - 1.0) * 100.0, 6))
        else:
            mkt_cum.append(None)

    return {
        "ok": True,
        "dim1": dim1,
        "dim2": dim2,
        "rebalance_rule": "日曆月末最後交易日收盤分組，次一交易日起持有",
        "dates": dates_out,
        "ls_daily": ls_daily,
        "ls_cum": ls_cum,
        "mkt_excess_daily": mkt_exc,
        "mkt_excess_cum": mkt_cum,
        "notes": "日頻因子報酬.csv 定義不同；此為月換檔之雙重排序 tercile 等權 LS。超額報酬與因子腳本相同：報酬率％/100 − 一年定存％/100。",
    }
