"""
data_service.py
資料存取層 — 目前讀取 CSV，未來可替換為 API 串接，只需修改此檔。
"""

import math
import os
from pathlib import Path

import pandas as pd

# ── 資料來源路徑（切換 API 時改這裡）──────────────────────────────────
DATA_DIR = Path(r"C:\Users\User\Desktop\財經數據分析平台\All_Data\日資料\大盤統計\大盤統計資訊")

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
            'SB6902','SB6903','SB6904','SB6905','SB6906','SB07','SB27',
            'SB2501','SB2502','SB2503'}
_EUROPE  = {'SB08','SB75','SB28','SB3301','SB3302','SB1080','SB1082',
            'SB93','SB9303','SB83','SB8302','SB92','SB72','SB16'}
_AMERICA = {'SB14','SB22','SB23','SB56','SB5602','SB57','SB60','SB9602'}
_TAIWAN  = {'SB01','SB03','OC72'}


def _intl_group(code: str) -> str:
    if code in _TAIWAN:  return '台灣'
    if code in _ASIA:    return '亞洲'
    if code in _EUROPE:  return '歐洲'
    if code in _AMERICA: return '美洲'
    if code == 'SB96':   return '美洲'
    if code == 'SB15':   return '其他'
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
