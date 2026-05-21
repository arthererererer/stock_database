"""
load_tej.py — TEJ CSV 批次匯入 PostgreSQL

用法：
    # 匯入單一資料表
    python load_tej.py --table tej_stock_price
    python load_tej.py --table tej_chip

    # 匯入全部資料表
    python load_tej.py --all

環境變數：
    DATABASE_URL  PostgreSQL 連線字串
                  範例：postgresql://user:pass@localhost:5432/findb

注意：
    - 排除國內銀行匯率資料夾（改由 load_crawler_fx.py 處理）
    - 使用 INSERT ... ON CONFLICT DO NOTHING 避免重複匯入
    - 每個 CSV 完成後更新 meta.security_master 證券代碼對照表
"""

import argparse
import calendar
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras

# ──────────────────────────────────────────────
# 基礎設定
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent / "All_Data"

# 不匯入的資料夾（匯率改由爬蟲資料替代）
EXCLUDED_FOLDERS = {"國內銀行利率(日)_國內銀行匯率"}

# ──────────────────────────────────────────────
# 各資料表組態：資料夾路徑、日期欄位類型
# ──────────────────────────────────────────────
TABLE_CONFIG: dict[str, dict] = {
    "tej_stock_price": {
        "folder": BASE_DIR / "日資料" / "TEJ 股價資料庫",
        "date_col": "年月日",
        "date_type": "daily",   # YYYYMMDD
        "schema": "raw",
        "db_date_col": "date",  # 資料庫實際欄位名稱（migrate_rename_date_cols.sql 後）
    },
    "tej_chip": {
        "folder": BASE_DIR / "日資料" / "TEJ 籌碼資料庫",
        "date_col": "年月日",
        "date_type": "daily",
        "schema": "raw",
        "db_date_col": "date",
    },
    "tej_market_stats": {
        "folder": BASE_DIR / "日資料" / "大盤統計" / "大盤統計資訊",
        "date_col": "年月日",
        "date_type": "daily",
        "schema": "raw",
        "db_date_col": "date",
    },
    "tej_intl_index": {
        "folder": BASE_DIR / "日資料" / "國際股價指數",
        "date_col": "年月日",
        "date_type": "daily",
        "schema": "raw",
        "db_date_col": "date",
    },
    "tej_director_monthly": {
        "folder": BASE_DIR / "月資料" / "董監全體持股狀況",
        "date_col": "年月",
        "date_type": "monthly",  # YYYYMM → 月底 DATE
        "schema": "raw",
        "db_date_col": "month",
    },
    "tej_quarterly": {
        "folder": BASE_DIR / "季資料" / "以合併為主簡表(單季)-全產業",
        "date_col": "年月",
        "date_type": "monthly",
        "schema": "raw",
        "db_date_col": "season",
    },
}

# ──────────────────────────────────────────────
# 欄位對應表（CSV 中文名 → PostgreSQL 英文欄位名）
# ──────────────────────────────────────────────
COLUMN_MAP_STOCK_PRICE: dict[str, str] = {
    "證券代碼":        "security_code",
    "年月日":          "date",
    "開盤價(元)":      "open",
    "最高價(元)":      "high",
    "最低價(元)":      "low",
    "收盤價(元)":      "close",
    "成交量(千股)":    "volume_k_shares",
    "成交值(千元)":    "turnover_k_twd",
    "報酬率％":        "return_pct",
    "報酬率-Ln":       "return_ln",
    "週轉率％":        "turnover_rate_pct",
    "流通在外股數(千股)": "shares_outstanding_k",
    "市值(百萬元)":    "market_cap_m",
    "市值比重％":      "market_cap_weight_pct",
    "成交值比重％":    "turnover_value_weight_pct",
    "成交筆數(筆)":    "trade_count",
    "本益比-TSE":      "pe_tse",
    "股價淨值比-TSE":  "pb_tse",
    "股價營收比-TEJ":  "ps_tej",
    "股利殖利率-TSE":  "div_yield_tse",
    "現金股利率":      "cash_div_rate",
    "股價漲跌(元)":    "price_change",
    "高低價差%":       "hl_spread_pct",
    "注意股票(A)":     "alert_a",
    "處置股票(D)":     "disposition_d",
    "全額交割(Y)":     "full_delivery_y",
    "超額報酬(日)-大盤": "excess_return_daily",
    "CAPM_Beta 一年":  "capm_beta_1y",
    "漲跌停":          "price_limit",
}

# 籌碼：主要欄位映射（其餘進 extras JSONB）
COLUMN_MAP_CHIP_MAIN: dict[str, str] = {
    "證券代碼":                "security_code",
    "年月日":                  "date",
    "外資買賣超(張)":          "fi_net_buy_lot",
    "投信買賣超(張)":          "it_net_buy_lot",
    "自營買賣超(張)":          "dt_net_buy_lot",
    "合計買賣超(張)":          "total_net_buy_lot",
    "外資買賣超日數":          "fi_net_days",
    "投信買賣超日數":          "it_net_days",
    "自營買賣超日數":          "dt_net_days",
    "法人買賣超日數":          "inst_net_days",
    "外資總投資股率%":         "fi_holding_pct",
    "投信持股率%":             "it_holding_pct",
    "合計持股率%":             "total_holding_pct",
    "融資餘額(張)":            "margin_balance_lot",
    "融資買進(張)":            "margin_buy_lot",
    "融資賣出(張)":            "margin_sell_lot",
    "融資使用率":              "margin_usage_pct",
    "融資維持率":              "margin_maint_ratio",
    "融券餘額(張)":            "short_balance_lot",
    "融券賣出(張)":            "short_sell_lot",
    "融券使用率":              "short_usage_pct",
    "券資比":                  "short_margin_ratio",
    "借券賣出餘額(張)":        "sec_lending_balance_lot",
    "借券賣出(張)":            "sec_lending_sell_lot",
    # ── 新增正式欄位（原本在 extras）──
    "融券買進(張)":            "short_buy_lot",
    "融券維持率":              "short_maint_ratio",
    "整戶維持率":              "overall_maint_ratio",
    "融資限額":                "margin_limit_lot",
    "融券限額":                "short_limit_lot",
    "融券(買+賣)/成交量 %":    "short_vol_ratio_pct",
    "融資(買+賣)/成交量 %":    "margin_vol_ratio_pct",
}

# 籌碼：不寫入資料庫的欄位（與股價/基本面重複，從 extras 亦排除）
CHIP_IGNORE_COLS: set[str] = {
    "當日收盤",
    "未調整收盤價(元)",
    "流通在外股數(千股)",
    "外資買賣超(千股)",
    "投信買賣超(千股)",
    "自營買賣超(千股)",
    "合計買賣超(千股)",
}

COLUMN_MAP_MARKET_STATS: dict[str, str] = {
    "證券代碼":       "security_code",
    "年月日":         "date",
    "成交金額":       "trade_amount",
    "成交數量":       "trade_volume",
    "成交筆數":       "trade_count",
    "總委買數量":     "total_bid_volume",
    "總委買筆數":     "total_bid_count",
    "總委賣數量":     "total_ask_volume",
    "總委賣筆數":     "total_ask_count",
    "漲停委買數量":   "limit_up_bid_volume",
    "漲停委買筆數":   "limit_up_bid_count",
    "漲停委賣數量":   "limit_up_ask_volume",
    "漲停委賣筆數":   "limit_up_ask_count",
    "跌停委買數量":   "limit_down_bid_volume",
    "跌停委買筆數":   "limit_down_bid_count",
    "跌停委賣數量":   "limit_down_ask_volume",
    "跌停委賣筆數":   "limit_down_ask_count",
    "上漲家數":       "advance_count",
    "下跌家數":       "decline_count",
    "持平家數":       "unchanged_count",
    "未成交家數":     "no_trade_count",
    "漲停家數":       "limit_up_count",
    "跌停家數":       "limit_down_count",
}

COLUMN_MAP_INTL_INDEX: dict[str, str] = {
    "證券代碼": "security_code",
    "年月日":   "date",
    "指數":     "index_value",
}

COLUMN_MAP_DIRECTOR: dict[str, str] = {
    "證券代碼":        "security_code",
    "年月":            "month",
    "總股數":          "total_shares",
    "董監持股%":       "director_holding_pct",
    "大股東持股(TSE)%": "major_shareholder_pct",
}

# ──────────────────────────────────────────────
# 日期轉換工具
# ──────────────────────────────────────────────

def parse_daily_date(val: str) -> date | None:
    """YYYYMMDD 字串 → date 物件"""
    s = str(val).strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def parse_monthly_date(val: str) -> date | None:
    """YYYYMM 字串 → 月底 DATE（如 202603 → 2026-03-31）"""
    s = str(val).strip()
    if len(s) != 6 or not s.isdigit():
        return None
    year, month = int(s[:4]), int(s[4:6])
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


# ──────────────────────────────────────────────
# 資料清洗工具
# ──────────────────────────────────────────────

def clean_numeric(val: Any) -> Any:
    """去除千分位逗號後嘗試轉 float；無法轉換則回傳 None"""
    if pd.isna(val):
        return None
    s = str(val).strip().replace(",", "")
    if s in ("", "NA", "N/A", "--", "－", "-", "nan", "NaN", "NAN", "inf", "-inf"):
        return None
    try:
        result = float(s)
        # float('nan') / float('inf') 無法存入整數欄位，統一轉 None
        if pd.isna(result) or result == float("inf") or result == float("-inf"):
            return None
        return result
    except ValueError:
        return val  # 保留原始字串（如漲跌停旗標）


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """對所有欄位進行基本清洗：strip 空白、欄位名稱 strip"""
    df.columns = [c.strip() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
    return df


def coerce_numeric_columns(df: pd.DataFrame, skip_cols: set[str]) -> pd.DataFrame:
    """對非 skip_cols 的欄位嘗試去千分位並轉數值"""
    for col in df.columns:
        if col in skip_cols:
            continue
        df[col] = df[col].apply(clean_numeric)
    return df


# ──────────────────────────────────────────────
# 讀取 CSV
# ──────────────────────────────────────────────

def read_tej_csv(path: Path) -> pd.DataFrame:
    """以 UTF-16 + Tab 分隔讀取 TEJ CSV，並回傳清洗後的 DataFrame"""
    try:
        df = pd.read_csv(path, encoding="utf-16", sep="\t", dtype=str, low_memory=False)
    except UnicodeError:
        # 少數檔案可能為 UTF-16 LE without BOM
        df = pd.read_csv(path, encoding="utf-16-le", sep="\t", dtype=str, low_memory=False)

    df = clean_dataframe(df)
    # 移除全空白列
    df = df.dropna(how="all")
    return df


# ──────────────────────────────────────────────
# 更新 meta.security_master
# ──────────────────────────────────────────────

def upsert_security_master(cur: psycopg2.extensions.cursor, codes: list[str]) -> None:
    """
    從「XXXX 名稱」格式的 security_code 拆解 ticker/name，
    並以 INSERT ON CONFLICT DO NOTHING 寫入 meta.security_master。
    """
    rows = []
    for code in set(codes):
        parts = code.split(" ", 1)
        ticker = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        # 簡易市場辨識（上市 4 碼數字、上櫃 5 碼或英數）
        if ticker.isdigit() and len(ticker) == 4:
            market = "TSE"
        elif ticker.isdigit() and len(ticker) == 5:
            market = "OTC"
        else:
            market = "INDEX"
        rows.append((code, ticker, name, market))

    if not rows:
        return

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO meta.security_master (security_code, ticker, name, market)
        VALUES %s
        ON CONFLICT (security_code) DO NOTHING
        """,
        rows,
    )


# ──────────────────────────────────────────────
# 各資料表匯入邏輯
# ──────────────────────────────────────────────

def _apply_column_map(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """保留 col_map 有定義的欄位並重命名"""
    existing = {k: v for k, v in col_map.items() if k in df.columns}
    return df[list(existing.keys())].rename(columns=existing)


def _to_rows(df: pd.DataFrame) -> list[tuple]:
    """
    將 DataFrame 轉成 psycopg2 可用的 tuple list。
    pandas 在 object 欄位存浮點 NaN 時，itertuples 仍會回傳
    numpy.float64('nan')，psycopg2 將其格式化為 'NaN'::float8，
    PostgreSQL 試圖 cast 到 INTEGER 時拋出 "integer out of range"。
    此函式統一將所有 float NaN 還原為 Python None（→ SQL NULL）。
    """
    nan_to_none = lambda v: None if isinstance(v, float) and pd.isna(v) else v
    return [
        tuple(nan_to_none(v) for v in row)
        for row in df.itertuples(index=False, name=None)
    ]


def load_stock_price(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    df = _apply_column_map(df, COLUMN_MAP_STOCK_PRICE)
    str_cols = {"security_code", "date", "alert_a", "disposition_d", "full_delivery_y", "price_limit"}
    df = coerce_numeric_columns(df, str_cols)
    df["date"] = df["date"].apply(lambda v: parse_daily_date(str(v)))
    df = df.dropna(subset=["security_code", "date"])

    cols = [c for c in df.columns]
    update_cols = ', '.join([f'{c} = EXCLUDED.{c}' for c in cols if c not in ('security_code', 'date')])
    sql = f"""
        INSERT INTO raw.tej_stock_price ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (security_code, date) DO UPDATE SET {update_cols}
    """
    rows = _to_rows(df)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    return len(rows)


def load_chip(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    # 先拆主要欄位、再收集 extras（排除 ignore 清單）
    main_cols_in_df = {k for k in COLUMN_MAP_CHIP_MAIN if k in df.columns}
    extra_cols = [
        c for c in df.columns
        if c not in main_cols_in_df and c not in CHIP_IGNORE_COLS
    ]

    main_df = df[list(main_cols_in_df)].rename(columns=COLUMN_MAP_CHIP_MAIN)
    str_cols = {"security_code", "date"}
    main_df = coerce_numeric_columns(main_df, str_cols)
    main_df["date"] = main_df["date"].apply(lambda v: parse_daily_date(str(v)))

    # 建立 extras dict（千分位清洗後）
    extras_series = df[extra_cols].apply(
        lambda row: {
            k: clean_numeric(v)
            for k, v in row.items()
            if not pd.isna(v) and str(v).strip() not in ("", "NA", "N/A", "--")
        },
        axis=1,
    )

    main_df["extras"] = extras_series.apply(
        lambda d: json.dumps(d, ensure_ascii=False) if d else None
    )

    main_df = main_df.dropna(subset=["security_code", "date"])

    cols = [c for c in main_df.columns]
    update_cols = ', '.join([f'{c} = EXCLUDED.{c}' for c in cols if c not in ('security_code', 'date')])
    sql = f"""
        INSERT INTO raw.tej_chip ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (security_code, date) DO UPDATE SET {update_cols}
    """
    rows = _to_rows(main_df)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=300)
    return len(rows)


def load_market_stats(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    df = _apply_column_map(df, COLUMN_MAP_MARKET_STATS)
    str_cols = {"security_code", "date"}
    df = coerce_numeric_columns(df, str_cols)
    df["date"] = df["date"].apply(lambda v: parse_daily_date(str(v)))
    df = df.dropna(subset=["security_code", "date"])

    cols = [c for c in df.columns]
    update_cols = ', '.join([f'{c} = EXCLUDED.{c}' for c in cols if c not in ('security_code', 'date')])
    sql = f"""
        INSERT INTO raw.tej_market_stats ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (security_code, date) DO UPDATE SET {update_cols}
    """
    rows = _to_rows(df)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    return len(rows)


def load_intl_index(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    df = _apply_column_map(df, COLUMN_MAP_INTL_INDEX)
    df["index_value"] = df["index_value"].apply(clean_numeric)
    df["date"] = df["date"].apply(lambda v: parse_daily_date(str(v)))
    df["security_code"] = df["security_code"].astype(str).str.strip()
    df = df.dropna(subset=["security_code", "date"])

    cols = [c for c in df.columns]
    update_cols = ', '.join([f'{c} = EXCLUDED.{c}' for c in cols if c not in ('security_code', 'date')])
    sql = f"""
        INSERT INTO raw.tej_intl_index ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (security_code, date) DO UPDATE SET {update_cols}
    """
    rows = _to_rows(df)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    return len(rows)


def load_director_monthly(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    df = _apply_column_map(df, COLUMN_MAP_DIRECTOR)
    str_cols = {"security_code", "month"}
    df = coerce_numeric_columns(df, str_cols)
    df["month"] = df["month"].apply(lambda v: parse_monthly_date(str(v)))
    df = df.dropna(subset=["security_code", "month"])

    cols = [c for c in df.columns]
    update_cols = ', '.join([f'{c} = EXCLUDED.{c}' for c in cols if c not in ('security_code', 'month')])
    sql = f"""
        INSERT INTO raw.tej_director_monthly ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (security_code, month) DO UPDATE SET {update_cols}
    """
    rows = _to_rows(df)
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    return len(rows)


def load_quarterly(df: pd.DataFrame, cur: psycopg2.extensions.cursor) -> int:
    """
    季財報：security_code + season 作主鍵，
    其餘所有財務欄位序列化為 JSONB data 欄位。
    """
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(how="all")

    security_col = "證券代碼"
    date_col = "年月"
    financial_cols = [c for c in df.columns if c not in (security_col, date_col)]

    # 向量化清洗主鍵欄位（取代 iterrows 內的 isna 判斷）
    df[security_col] = df[security_col].astype(str).str.strip()
    df[date_col] = df[date_col].astype(str).str.strip()
    _null_tokens = {"nan", "NaN", "NAN", "", "None"}
    df = df[~df[security_col].isin(_null_tokens) & ~df[date_col].isin(_null_tokens)]

    # 批量日期轉換
    df["_season"] = df[date_col].apply(parse_monthly_date)
    df = df.dropna(subset=["_season"])

    # 批量清洗財務欄位（逐欄向量化，取代 inner for-loop）
    for col in financial_cols:
        df[col] = df[col].apply(clean_numeric)

    # to_dict("records") 比 iterrows 快 10–50 倍；list-comprehension 建 JSONB
    fin_records = df[financial_cols].to_dict("records")
    rows = [
        (
            code,
            season,
            json.dumps({k: v for k, v in rec.items() if v is not None}, ensure_ascii=False),
        )
        for code, season, rec in zip(df[security_col], df["_season"], fin_records)
    ]

    if not rows:
        return 0

    sql = """
        INSERT INTO raw.tej_quarterly (security_code, season, data)
        VALUES %s
        ON CONFLICT (security_code, season) DO UPDATE SET data = EXCLUDED.data
    """
    psycopg2.extras.execute_values(cur, sql, rows, page_size=200)
    return len(rows)


# ──────────────────────────────────────────────
# 資料表 → 匯入函式對應
# ──────────────────────────────────────────────
LOADER_FUNC = {
    "tej_stock_price":      load_stock_price,
    "tej_chip":             load_chip,
    "tej_market_stats":     load_market_stats,
    "tej_intl_index":       load_intl_index,
    "tej_director_monthly": load_director_monthly,
    "tej_quarterly":        load_quarterly,
}


# ──────────────────────────────────────────────
# 備份與驗證工具
# ──────────────────────────────────────────────

def backup_table(
    conn: psycopg2.extensions.connection,
    schema: str,
    table: str,
) -> tuple[str, int]:
    """
    匯入前在 backup schema 建立資料表快照。
    回傳 (備份表名稱, 備份前筆數)。
    備份表命名規則：backup.<table>_YYYYMMDD_HHMMSS
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{table}_{ts}"
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS backup")
        cur.execute(
            f"CREATE TABLE backup.{backup_name} AS SELECT * FROM {schema}.{table}"
        )
        cur.execute(f"SELECT COUNT(*) FROM backup.{backup_name}")
        count: int = cur.fetchone()[0]
        conn.commit()
    log.info("備份完成：backup.%s（%d 筆）", backup_name, count)
    return backup_name, count


def report_date_range(
    conn: psycopg2.extensions.connection,
    schema: str,
    table: str,
    db_date_col: str,
    count_before: int,
) -> None:
    """匯入後查詢資料表的最新總筆數與日期範圍，並與匯入前比較。"""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), MIN({db_date_col}), MAX({db_date_col})"
            f" FROM {schema}.{table}"
        )
        total, min_date, max_date = cur.fetchone()
    added = total - count_before
    log.info(
        "[%s.%s] 匯入後總筆數：%d（本次新增 %d 筆），日期範圍：%s → %s",
        schema, table, total, added, min_date, max_date,
    )


# ──────────────────────────────────────────────
# 主要匯入流程
# ──────────────────────────────────────────────

def process_table(
    table_name: str,
    conn: psycopg2.extensions.connection,
    skip_backup: bool = False,
) -> None:
    cfg = TABLE_CONFIG[table_name]
    folder: Path = cfg["folder"]
    schema: str = cfg["schema"]
    db_date_col: str = cfg["db_date_col"]

    if not folder.exists():
        log.warning("資料夾不存在，跳過：%s", folder)
        return

    csv_files = sorted(folder.glob("*.csv"))
    if not csv_files:
        log.warning("資料夾內無 CSV 檔案：%s", folder)
        return

    # ── 匯入前備份（--skip-backup 時略過，改只查筆數）────
    if skip_backup:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table_name}")
            count_before: int = cur.fetchone()[0]
        log.info("略過備份（skip-backup），%s.%s 現有 %d 筆", schema, table_name, count_before)
    else:
        _, count_before = backup_table(conn, schema, table_name)

    log.info("開始匯入 [%s]，資料夾：%s，共 %d 個 CSV", table_name, folder, len(csv_files))
    total_inserted = 0

    for csv_path in csv_files:
        log.info("  讀取：%s", csv_path.name)
        try:
            df = read_tej_csv(csv_path)
        except Exception as exc:
            log.error("  讀取失敗：%s — %s", csv_path.name, exc)
            continue

        if df.empty:
            log.warning("  空檔案，略過：%s", csv_path.name)
            continue

        loader = LOADER_FUNC[table_name]

        try:
            with conn.cursor() as cur:
                inserted = loader(df, cur)
                # 更新證券代碼主表（僅針對有 security_code 的資料表）
                if "證券代碼" in df.columns:
                    codes = df["證券代碼"].dropna().astype(str).str.strip().unique().tolist()
                    upsert_security_master(cur, codes)
                conn.commit()
                log.info("  ✓ 匯入 %d 筆（%s）", inserted, csv_path.name)
                total_inserted += inserted
        except Exception as exc:
            conn.rollback()
            log.error("  匯入失敗：%s — %s", csv_path.name, exc)

    log.info("[%s] 完成，合計匯入 %d 筆", table_name, total_inserted)

    # ── 匯入後日期範圍驗證 ────────────────────
    report_date_range(conn, schema, table_name, db_date_col, count_before)


def main() -> None:
    parser = argparse.ArgumentParser(description="TEJ CSV → PostgreSQL ETL")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--table",
        choices=list(TABLE_CONFIG.keys()),
        help="指定匯入的資料表名稱",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="匯入全部資料表",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="跳過匯入前的完整備份（加速增量匯入；首次或大批量匯入請勿使用）",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("環境變數 DATABASE_URL 未設定，請先 export DATABASE_URL=postgresql://...")
        sys.exit(1)

    log.info("連線至 PostgreSQL：%s", db_url.split("@")[-1])
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.OperationalError as exc:
        log.error("資料庫連線失敗：%s", exc)
        sys.exit(1)

    tables = list(TABLE_CONFIG.keys()) if args.all else [args.table]

    for table in tables:
        process_table(table, conn, skip_backup=args.skip_backup)

    conn.close()
    log.info("ETL 全部完成。")


if __name__ == "__main__":
    main()
