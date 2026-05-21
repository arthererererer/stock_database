"""
load_wantgoo_monthly_revenue.py — 玩股網月營收 CSV → PostgreSQL（raw.wantgoo_monthly_revenue）

用法：
    python load_wantgoo_monthly_revenue.py
    python load_wantgoo_monthly_revenue.py --file "路徑\\月營收.csv"

環境變數：
    DATABASE_URL  PostgreSQL 連線字串

CSV 欄位（與 scrape_monthly_revenue.py 輸出一致）：
    代號, 名稱, 年度月份, 當月營收_仟元

資料表時間欄位為 **month**（月頻；查詢時請寫成 "month"），型別 DATE，
存該月第一日（yyyy-mm-dd）。

匯入策略：INSERT … ON CONFLICT (security_code, "month") DO UPDATE
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
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
    / "玩股網爬蟲"
    / "output"
    / "月營收_scheduled_latest.csv"
)


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw.wantgoo_monthly_revenue (
                security_code          VARCHAR(16)  NOT NULL,
                security_name          VARCHAR(256),
                "month"                DATE         NOT NULL,
                revenue_ntd_thousand   BIGINT       NOT NULL,
                updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
                PRIMARY KEY (security_code, "month")
            )
            """
        )

        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'raw' AND table_name = 'wantgoo_monthly_revenue'
              AND column_name = 'year_month'
            LIMIT 1
            """
        )
        if cur.fetchone():
            log.info("偵測舊欄位 year_month，重新命名為 month …")
            cur.execute("DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_ym")
            cur.execute(
                'ALTER TABLE raw.wantgoo_monthly_revenue '
                'RENAME COLUMN year_month TO "month"'
            )
        else:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'raw' AND table_name = 'wantgoo_monthly_revenue'
                  AND column_name = 'date'
                LIMIT 1
                """
            )
            if cur.fetchone():
                log.info('偵測舊欄位 "date"，重新命名為 month …')
                cur.execute("DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_date")
                cur.execute(
                    'ALTER TABLE raw.wantgoo_monthly_revenue '
                    'RENAME COLUMN "date" TO "month"'
                )

        cur.execute("DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_ym")
        cur.execute("DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_date")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wantgoo_monthly_revenue_month
            ON raw.wantgoo_monthly_revenue ("month")
            """
        )

    conn.commit()
    log.info("已確認 schema：raw.wantgoo_monthly_revenue（時間欄位：month）")


def parse_year_month_cell(val) -> date | None:
    s = str(val).strip().replace("-", "/")
    if not s or s.lower() in ("nan", "none"):
        return None
    parts = s.split("/")
    if len(parts) != 2:
        return None
    try:
        y, mo = int(parts[0]), int(parts[1])
        return date(y, mo, 1)
    except ValueError:
        return None


def load_csv(file_path: Path, conn: psycopg2.extensions.connection) -> int:
    if not file_path.exists():
        log.error("找不到 CSV：%s", file_path)
        sys.exit(1)

    ensure_schema(conn)

    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required = {"代號", "名稱", "年度月份", "當月營收_仟元"}
    missing = required - set(df.columns)
    if missing:
        log.error("CSV 缺少必要欄位：%s", missing)
        sys.exit(1)

    df["代號"] = df["代號"].astype(str).str.strip()
    df["名稱"] = df["名稱"].fillna("").astype(str).str.strip()
    df["period_date"] = df["年度月份"].apply(parse_year_month_cell)
    df["當月營收_仟元"] = (
        pd.to_numeric(df["當月營收_仟元"].astype(str).str.replace(",", ""), errors="coerce")
    )

    bad = df["period_date"].isna() | df["當月營收_仟元"].isna() | (df["代號"] == "")
    if bad.any():
        log.warning("略過 %d 筆（代號／月份／營收無效）", int(bad.sum()))
        df = df[~bad].copy()

    df["當月營收_仟元"] = df["當月營收_仟元"].astype("int64")

    rows = [
        (row["代號"], row["名稱"] or None, row["period_date"], int(row["當月營收_仟元"]))
        for _, row in df.iterrows()
    ]

    if not rows:
        log.warning("沒有可匯入的資料列")
        return 0

    sql = """
        INSERT INTO raw.wantgoo_monthly_revenue
            (security_code, security_name, "month", revenue_ntd_thousand)
        VALUES %s
        ON CONFLICT (security_code, "month") DO UPDATE SET
            security_name = EXCLUDED.security_name,
            revenue_ntd_thousand = EXCLUDED.revenue_ntd_thousand,
            updated_at = now()
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()

    log.info("已 upsert %d 筆至 raw.wantgoo_monthly_revenue", len(rows))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="玩股網月營收 CSV → PostgreSQL（raw.wantgoo_monthly_revenue）"
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"月營收 CSV 路徑（預設：{DEFAULT_CSV_PATH}）",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("環境變數 DATABASE_URL 未設定")
        sys.exit(1)

    log.info("連線至 PostgreSQL：%s", db_url.split("@")[-1])
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.OperationalError as exc:
        log.error("資料庫連線失敗：%s", exc)
        sys.exit(1)

    try:
        n = load_csv(args.file.resolve(), conn)
    finally:
        conn.close()

    log.info("玩股網月營收 ETL 完成（%d 筆）。", n)


if __name__ == "__main__":
    main()
