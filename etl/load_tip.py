"""
load_tip.py — TIP 臺灣指數 CSV → PostgreSQL (raw.tip_index_history)

用法：
    # 載入全部歷史（預設讀 all_history.csv）
    python load_tip.py

    # 只載入今日爬下來的 daily CSV（日頻排程用）
    python load_tip.py --file "TIP台灣指數爬蟲/output/tip_20260519_20260519.csv"

環境變數：
    DATABASE_URL  PostgreSQL 連線字串
                  範例：postgresql://user:pass@localhost:5432/findb

資料表：raw.tip_index_history
    PRIMARY KEY (index_code, trade_date)
    匯入策略：INSERT ... ON CONFLICT DO UPDATE（重複以新值覆寫）

CSV 欄位（scrape_tip_history.py 輸出格式）：
    指數代碼, 指數名稱, 日期, 價格指數值, 報酬指數值, 漲跌點數, 漲跌百分比
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parent.parent
    / "TIP台灣指數爬蟲"
    / "output"
    / "all_history.csv"
)

# ──────────────────────────────────────────────
# Schema 建立
# ──────────────────────────────────────────────

def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw.tip_index_history (
                index_code   VARCHAR(20)   NOT NULL,
                index_name   VARCHAR(200),
                trade_date   DATE          NOT NULL,
                price_index  NUMERIC(18,4),
                return_index NUMERIC(18,4),
                change_pts   NUMERIC(14,4),
                change_pct   NUMERIC(10,4),
                updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
                PRIMARY KEY (index_code, trade_date)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tip_index_history_trade_date
            ON raw.tip_index_history (trade_date)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tip_index_history_index_code
            ON raw.tip_index_history (index_code)
        """)
    conn.commit()
    log.info("已確認 schema：raw.tip_index_history")


# ──────────────────────────────────────────────
# 備份
# ──────────────────────────────────────────────

def backup_table(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'raw' AND table_name = 'tip_index_history'
            )
        """)
        exists: bool = cur.fetchone()[0]
        if not exists:
            log.info("資料表不存在，略過備份")
            return

        cur.execute("SELECT COUNT(*) FROM raw.tip_index_history")
        count: int = cur.fetchone()[0]
        if count == 0:
            log.info("資料表為空，略過備份")
            return

        cur.execute("CREATE SCHEMA IF NOT EXISTS backup")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"tip_index_history_{ts}"
        cur.execute(
            f"CREATE TABLE backup.{backup_name} AS SELECT * FROM raw.tip_index_history"
        )
        conn.commit()
    log.info("備份完成：backup.%s（%d 筆）", backup_name, count)


# ──────────────────────────────────────────────
# 清洗工具
# ──────────────────────────────────────────────

def clean_numeric(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip().replace(",", "").replace("+", "")
    if s in ("", "NA", "N/A", "--", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(val) -> object:
    """YYYY/MM/DD 或 YYYY-MM-DD → datetime.date；無效回 NaT"""
    s = str(val).strip().replace("/", "-")
    return pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").date()


# ──────────────────────────────────────────────
# 匯入邏輯
# ──────────────────────────────────────────────

def load_tip(file_path: Path, conn: psycopg2.extensions.connection) -> int:
    if not file_path.exists():
        log.error("找不到 CSV：%s", file_path)
        sys.exit(1)

    backup_table(conn)
    ensure_schema(conn)

    log.info("讀取 TIP CSV：%s", file_path)
    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required = {"指數代碼", "指數名稱", "日期", "價格指數值", "報酬指數值", "漲跌點數", "漲跌百分比"}
    missing = required - set(df.columns)
    if missing:
        log.error("CSV 缺少必要欄位：%s", missing)
        sys.exit(1)

    df["指數代碼"] = df["指數代碼"].astype(str).str.strip()
    df["指數名稱"] = df["指數名稱"].fillna("").astype(str).str.strip()
    df["trade_date"]   = df["日期"].apply(parse_date)
    df["price_index"]  = df["價格指數值"].apply(clean_numeric)
    df["return_index"] = df["報酬指數值"].apply(clean_numeric)
    df["change_pts"]   = df["漲跌點數"].apply(clean_numeric)
    df["change_pct"]   = df["漲跌百分比"].apply(clean_numeric)

    bad = df["trade_date"].isna() | (df["指數代碼"] == "")
    if bad.any():
        log.warning("略過 %d 筆（代碼或日期無效）", int(bad.sum()))
        df = df[~bad].copy()

    if df.empty:
        log.warning("沒有可匯入的資料列")
        return 0

    rows = [
        (
            row["指數代碼"],
            row["指數名稱"] or None,
            row["trade_date"],
            row["price_index"],
            row["return_index"],
            row["change_pts"],
            row["change_pct"],
        )
        for _, row in df.iterrows()
    ]

    sql = """
        INSERT INTO raw.tip_index_history
            (index_code, index_name, trade_date,
             price_index, return_index, change_pts, change_pct)
        VALUES %s
        ON CONFLICT (index_code, trade_date) DO UPDATE SET
            index_name   = EXCLUDED.index_name,
            price_index  = EXCLUDED.price_index,
            return_index = EXCLUDED.return_index,
            change_pts   = EXCLUDED.change_pts,
            change_pct   = EXCLUDED.change_pct,
            updated_at   = now()
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=1000)
    conn.commit()

    log.info("✓ 成功 upsert %d 筆至 raw.tip_index_history", len(rows))
    _print_summary(df)
    _report_db_range(conn)
    return len(rows)


# ──────────────────────────────────────────────
# 統計報表
# ──────────────────────────────────────────────

def _print_summary(df: pd.DataFrame) -> None:
    n_codes = df["指數代碼"].nunique()
    date_min = df["trade_date"].min()
    date_max = df["trade_date"].max()
    print("\n" + "=" * 55)
    print("  TIP 指數匯入統計報表")
    print("=" * 55)
    print(f"  總筆數    ：{len(df):,}")
    print(f"  指數支數  ：{n_codes}")
    print(f"  日期範圍  ：{date_min}  →  {date_max}")
    null_price = df["price_index"].isna().sum()
    if null_price:
        print(f"  ⚠ 價格指數缺值：{null_price} 筆")
    print("=" * 55 + "\n")


def _report_db_range(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT index_code),
                   COUNT(*),
                   MIN(trade_date),
                   MAX(trade_date)
            FROM raw.tip_index_history
        """)
        n_codes, total, min_d, max_d = cur.fetchone()
    log.info(
        "資料庫 tip_index_history：%d 支指數 / %d 筆 / %s → %s",
        n_codes, total, min_d, max_d,
    )


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TIP 臺灣指數 CSV → PostgreSQL (raw.tip_index_history)"
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"CSV 路徑（預設：{DEFAULT_CSV_PATH}）",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("環境變數 DATABASE_URL 未設定，請先設定 DATABASE_URL=postgresql://...")
        sys.exit(1)

    log.info("連線至 PostgreSQL：%s", db_url.split("@")[-1])
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.OperationalError as exc:
        log.error("資料庫連線失敗：%s", exc)
        sys.exit(1)

    try:
        n = load_tip(args.file.resolve(), conn)
    finally:
        conn.close()

    log.info("TIP 指數 ETL 完成（%d 筆）。", n)


if __name__ == "__main__":
    main()
